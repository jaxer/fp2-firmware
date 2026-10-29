import importlib.util
import pathlib
import unittest

spec = importlib.util.spec_from_file_location(
    "light_filter_runner",
    pathlib.Path(__file__).resolve().parents[1] / "tools/test_light_filter.py",
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class LightFilterTests(unittest.TestCase):
    def test_source_arithmetic_and_safe_startup(self):
        result = runner.run_tests()
        self.assertEqual(result["raw_words"], 65536)
        self.assertIn("boundaries passed", result["result"])
