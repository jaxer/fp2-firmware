import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "button_gestures_runner",
    Path(__file__).resolve().parents[1] / "tools/test_button_gestures.py",
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class ButtonGesturesTests(unittest.TestCase):
    def test_stock_gestures_and_timer_commands(self):
        self.assertEqual(runner.run_tests()["click_counts_checked"], 12)
