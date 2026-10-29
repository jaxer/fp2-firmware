"""Offline installation guards; all buffers/files are isolated synthetic inputs."""

import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from install_plan import selector


class InstallBoundaries(unittest.TestCase):
    def test_stock_selector_validates_crc_and_chooses_current_slot(self):
        data = bytearray(b"\xff" * 0x13000)
        parts = [
            {"label": "otadata", "offset": 0x11000},
            {"label": "a", "type": 0, "subtype": 16},
            {"label": "b", "type": 0, "subtype": 17},
        ]
        # The selector ignores non-app entries using type/subtype.
        parts[0].update(type=1, subtype=0)

        def record(offset, seq):
            struct.pack_into("<I", data, offset, seq)
            struct.pack_into("<I", data, offset + 24, 2)
            struct.pack_into(
                "<I",
                data,
                offset + 28,
                zlib.crc32(data[offset : offset + 4], 0xFFFFFFFF),
            )

        record(0x11000, 1)
        record(0x12000, 2)
        self.assertEqual(selector(data, parts)[0]["label"], "b")
        data[0x12000 + 28] ^= 1
        self.assertEqual(selector(data, parts)[0]["label"], "a")
        data[0x11000 + 28] ^= 1
        with self.assertRaises(ValueError):
            selector(data, parts)

    def test_research_default_has_no_hardware_access(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/research.py"), "install"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertFalse(json.loads(result.stdout)["hardware_access"])

    def test_live_action_requires_explicit_inputs(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/research.py"), "install", "--execute"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--port, --backup, --output", result.stderr)

    def test_unknown_backup_cannot_create_install_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            backup = Path(temporary) / "unsupported.bin"
            backup.write_bytes(b"not a device backup")
            output = Path(temporary) / "out"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/install_plan.py"),
                    str(backup),
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())
