import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "storage_guard", ROOT / "tools/storage_guard.py"
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class StorageBuildGuard(unittest.TestCase):
    def test_unknown_generated_source_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "src/esphome/components/esp32/preferences.cpp"
            target.parent.mkdir(parents=True)
            target.write_text("unreviewed preferences source")
            before = target.read_bytes()
            with self.assertRaises(RuntimeError):
                guard.patch(td)
            self.assertEqual(target.read_bytes(), before)

    def test_guard_is_idempotent_after_reviewed_replacement(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "src/esphome/components/esp32/preferences.cpp"
            target.parent.mkdir(parents=True)
            target.write_text(guard.STUB)
            hal = target.parent / "hal.cpp"
            hal.write_text(guard.HAL_REPLACEMENT)
            guard.patch(td)
            self.assertEqual(target.read_text(), guard.STUB)

    def test_unreviewed_hal_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "src/esphome/components/esp32/hal.cpp"
            target.parent.mkdir(parents=True)
            target.write_text("unreviewed HAL source")
            before = target.read_bytes()
            with self.assertRaises(RuntimeError):
                guard.patch_hal(td)
            self.assertEqual(target.read_bytes(), before)
