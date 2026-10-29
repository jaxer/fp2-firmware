"""Isolated wire contract and isolated sender tests; no live device."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "tools"))
import radar_xmodem as xm


class XmodemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Isolated synthetic payload, matching the supported envelope length only.
        cls.bundle = bytes(range(256)) * 9472 + bytes(range(17))

    def test_envelope_extent_padding_and_sequence_wrap(self):
        self.assertEqual((len(self.bundle) + 1023) // 1024, 2369)
        self.assertEqual(xm.packet(self.bundle, 255)[1:3], b"\0\xff")
        self.assertEqual(xm.packet(self.bundle, 2368)[3:20], self.bundle[-17:])
        self.assertEqual(xm.packet(self.bundle, 2368)[20:-2], b"\xff" * 1007)
        with self.assertRaises(ValueError):
            xm.packet(self.bundle, 2369)

    def test_complete_isolated_bundle_transport_and_ack_required(self):
        class Link:
            def __init__(self):
                self.writes = []
                self.start = True

            def write(self, data):
                self.writes.append(data)

            def read(self):
                if self.start:
                    self.start = False
                    return b"C"
                return b"\x06"

        link = Link()
        result = xm.send(link, self.bundle)
        self.assertEqual(result["blocks"], 2369)
        self.assertEqual(link.writes[-1], b"\x04")
        self.assertFalse(result["image_verified"])

    def test_cancel_timeout_and_ambiguous_write(self):
        class Link:
            def __init__(self, mode):
                self.mode = mode
                self.start = True
                self.writes = 0
                self.t = 0

            def now(self):
                self.t += 0.1
                return self.t

            def write(self, data):
                self.writes += 1
                if self.mode == "write":
                    raise OSError("isolated uncertain write")

            def read(self):
                if self.start:
                    self.start = False
                    return b"C"
                return b"\x18" if self.mode == "cancel" else b""

        for mode, error in [
            ("cancel", RuntimeError),
            ("timeout", TimeoutError),
            ("write", OSError),
        ]:
            link = Link(mode)
            with self.subTest(mode=mode), self.assertRaises(error):
                xm.send(link, self.bundle, clock=link.now)
            self.assertEqual(link.writes, 5 if mode == "timeout" else 1)

    def test_startup_text_is_not_updater_readiness(self):
        class Link:
            def __init__(self):
                self.t = 0
                self.writes = []

            def now(self):
                self.t += 1
                return self.t

            def read(self):
                return b"Checking CRC...\r\n"

            def write(self, data):
                self.writes.append(data)

        link = Link()
        with self.assertRaises(TimeoutError):
            xm.send(link, self.bundle, clock=link.now)
        self.assertEqual(link.writes, [])
