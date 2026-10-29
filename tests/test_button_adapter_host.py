import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "button_adapter_runner",
    Path(__file__).resolve().parents[1] / "tools/test_button_adapter.py",
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class ButtonAdapterHostTests(unittest.TestCase):
    def test_local_timing_over_stock_domain(self):
        self.assertEqual(runner.run_tests()["local_timer_periods_ms"], [1000, 400])
