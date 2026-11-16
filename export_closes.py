"""Stream the SQLite close facts to a Parquet file for dbt."""
import argparse
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.parquet as pq


SCHEMA = pa.schema([
    ("run_id",pa.string()),("client_id",pa.int64()),("member_id",pa.int64()),
    ("month",pa.string()),("paid_cents",pa.int64()),("benchmark_cents",pa.int64()),
])


def export(database, output):
    output.parent.mkdir(parents=True,exist_ok=True)
    total = 0
    with TemporaryDirectory(dir=output.parent) as temp:
        work = Path(temp) / "close_fact.parquet"
        with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro",uri=True)) as db:
            cursor = db.execute("""
                SELECT f.run_id,f.client_id,f.member_id,m.starts,f.paid_cents,f.benchmark_cents
                FROM close_fact f JOIN month m ON m.id=f.month_id
                ORDER BY f.run_id,f.client_id,f.member_id,f.month_id
            """)
            with pq.ParquetWriter(work,SCHEMA,compression="zstd") as writer:
                while rows := cursor.fetchmany(50_000):
                    columns = [pa.array(values,type=field.type) for field,values in zip(SCHEMA,zip(*rows))]
                    writer.write_table(pa.Table.from_arrays(columns,schema=SCHEMA))
                    total += len(rows)
        work.replace(output)
    return total


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    print(f"Exported {export(args.database,args.out):,} close facts to {args.out}")
