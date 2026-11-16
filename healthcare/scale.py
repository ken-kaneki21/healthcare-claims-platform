"""Measure a fresh synthetic build, interrupted replay, recovery, and close parity."""

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from time import perf_counter

from build_platform import build
from healthcare.ingest import replay_feed
from healthcare.journal_close import rebuild


def peak_working_set_bytes():
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        memory = ProcessMemoryCounters()
        memory.cb = ctypes.sizeof(memory)
        query = kernel.K32GetProcessMemoryInfo
        query.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        if not query(kernel.GetCurrentProcess(), ctypes.byref(memory), memory.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return memory.PeakWorkingSetSize

    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


def run(output: Path, members: int, *, tenants: int = 2):
    output.mkdir(parents=True, exist_ok=False)
    source, journal, close = (
        output / f"{name}.sqlite" for name in ("source", "journal", "close")
    )
    started = perf_counter()
    report = build(source, members, 42, tenants)
    initial = perf_counter()
    checkpoint = replay_feed(source, journal, 1, max_batches=1)
    checkpoint_seconds = perf_counter() - initial
    recovery_start = perf_counter()
    replay = [replay_feed(source, journal, tenant) for tenant in range(1, tenants + 1)]
    recovery_seconds = perf_counter() - recovery_start
    report.update(
        {
            "checkpoint": checkpoint,
            "checkpoint_seconds": round(checkpoint_seconds, 3),
            "historical_backfill_seconds": round(recovery_seconds, 3),
            "journal_ingestion_seconds": round(
                checkpoint_seconds + recovery_seconds, 3
            ),
            "journal_bytes": journal.stat().st_size,
            "journal_unique_versions": sum(row["inserted_versions"] for row in replay)
            + checkpoint["inserted_versions"],
            "journal_deliveries_per_second": round(
                sum(row["deliveries"] for row in replay)
                / (checkpoint_seconds + recovery_seconds),
                2,
            ),
        }
    )
    report["journal_close"] = rebuild(source, journal, close)
    report["end_to_end_seconds"] = round(perf_counter() - started, 3)
    retry_start = perf_counter()
    retry = [replay_feed(source, journal, tenant) for tenant in range(1, tenants + 1)]
    report["retry_seconds"] = round(perf_counter() - retry_start, 3)
    report["retry_inserted_versions"] = sum(row["inserted_versions"] for row in retry)
    with closing(sqlite3.connect(close)) as db:
        db.execute("ATTACH DATABASE ? AS baseline", (str(source.resolve()),))
        report["close_fact_mismatches"] = sum(
            db.execute(
                f"SELECT count(*) FROM (SELECT * FROM {a}.close_fact EXCEPT SELECT * FROM {b}.close_fact)"
            ).fetchone()[0]
            for a, b in (("main", "baseline"), ("baseline", "main"))
        )
    if report["retry_inserted_versions"] or report["close_fact_mismatches"]:
        raise RuntimeError("Replay or close parity failed")
    report["peak_working_set_bytes"] = peak_working_set_bytes()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--members", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tenants", type=int, choices=(2, 3), default=2)
    args = parser.parse_args()
    report = run(args.out, args.members, tenants=args.tenants)
    result = json.dumps(report, indent=2)
    (args.out / "report.json").write_text(result + "\n", encoding="utf-8")
    print(result)
