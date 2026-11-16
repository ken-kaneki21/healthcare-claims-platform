import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from healthcare.experiments import FEATURES
from healthcare.monitoring import evaluate


class MonitoringTests(unittest.TestCase):
    def test_detects_feature_and_prediction_shift_by_tenant_without_reading_labels(
        self,
    ):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("Install numpy for model monitoring")
        rows = np.array([[1, 10, 1, 0, 1, 1, 1, 0], [2, 20, 1, 0, 5, 1, 1, 0]])
        bundle = {
            "version": "test",
            "features": FEATURES,
            "artifact": {
                "mean": [0] * 5,
                "scale": [1] * 5,
                "intercept": 0,
                "coefficients": [0, 0, 100, 0, 0],
            },
            "monitor_reference": {
                "feature_mean": [1, 0, 1, 1, 1],
                "feature_std": [1] * 5,
                "prediction_p50": 100,
                "prediction_p95": 100,
            },
        }
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "unused.sqlite"
            source.touch()
            with patch("train_cost.cohort", return_value=rows) as cohort:
                normal, shifted = evaluate(source, 21, bundle)["tenants"]
                self.assertFalse(cohort.call_args.kwargs["include_target"])
                self.assertFalse(normal["alert"])
                self.assertTrue(shifted["features"]["paid_3_months_usd"]["alert"])
                self.assertTrue(shifted["predictions"]["p95"]["alert"])
