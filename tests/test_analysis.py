import importlib.util
import math
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("analyze", Path(__file__).resolve().parents[1] / "tools/analyze.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AnalysisTests(unittest.TestCase):
    def test_means(self):
        result = module.summarize([
            {"total_time": 2, "partial_exposure_time": 1},
            {"total_time": 4, "partial_exposure_time": 2},
        ])
        self.assertEqual(result["total_time"]["mean_s"], 3)
        self.assertEqual(result["n"], 2)

    def test_invalid_samples(self):
        for value in (-1, math.nan, math.inf, True):
            with self.assertRaises(ValueError):
                module.summarize([{"total_time": value, "partial_exposure_time": 0}])
        with self.assertRaises(ValueError):
            module.summarize([])
        with self.assertRaises(ValueError):
            module.summarize([{"total_time": 1, "partial_exposure_time": 2}])

    def test_archived_runs(self):
        result = module.report()
        self.assertEqual(result["baseline"]["n"], 10)
        self.assertEqual(result["tsdo"]["n"], 10)
        self.assertEqual(len(result["sha256"]), 10)


if __name__ == "__main__":
    unittest.main()
