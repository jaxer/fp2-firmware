"""Isolated protocol fixtures, not device verification."""

from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import radar_memory_monitor as m


class Link:
    def __init__(self, capacity=0x100080):
        self.lines = SimpleNamespace(
            sent=bytearray(), received=bytearray(), pending=bytearray(b"keep")
        )
        self.capacity = capacity
        self.requests = []
        self.queue = []
        self.drop = 0
        self.fail_write = False
        self.clock_value = 0.0
        self.bad_echo = False
        self.max_received = 0

    def clock(self):
        self.clock_value += 0.01
        return self.clock_value

    def sfdp(self, address, count):
        data = bytearray(0x100)
        data[:8] = b"SFDP" + bytes([6, 1, 0, 255])
        data[8:16] = bytes([0, 6, 1, 2, 0x40, 0, 0, 255])
        data[0x44:0x48] = (self.capacity * 8 - 1).to_bytes(4, "little")
        return bytes(data[address : address + count])

    def writer(self, lines, raw):
        assert (
            m.modbus_crc(raw[:-2]) == int.from_bytes(raw[-2:], "little")
            and sum(raw[:8]) % 256 == 0
        )
        p = raw[8:-2]
        assert p[:5] == b"\x01\x02FP2" and p[6] == 1
        mode = chr(p[5])
        address = int.from_bytes(p[7:11], "big")
        count = p[11]
        self.requests.append((mode, address, count, p[12:]))
        lines.sent.extend(b"W")
        lines.received.extend(b"WOK\n")
        if self.fail_write:
            raise TimeoutError("uncertain WOK")
        if self.drop:
            self.drop -= 1
            return
        if mode == "S":
            body = self.sfdp(address, count)
        elif mode == "J":
            body = b"\xef\x40\x17"
        elif mode == "W":
            body = p[12:]
        else:
            body = bytes((address + i) & 255 for i in range(count))
        if self.bad_echo:
            body = bytes(len(body))
        echo = (
            bytes([3, ord(mode), 0])
            + address.to_bytes(4, "big")
            + bytes([count])
            + body
        )
        payload = b"\x01\x02\x05" + len(echo).to_bytes(2, "big") + echo
        reply = m.frame(payload, sequence=99, operation=4)
        # Noise/unrelated stock version frame and fragmented actual private echo.
        self.queue.extend(
            [
                b"log\r\n" + m.frame(b"\x01\x02\0\x65", operation=5) + reply[:7],
                reply[7:],
            ]
        )

    def poller(self, lines):
        raw = self.queue.pop(0) if self.queue else b""
        lines.received.extend(b"RX " + raw.hex().encode() + b"\n")
        self.max_received = max(self.max_received, len(lines.received))
        return raw

    def monitor(self, **kw):
        return m.Monitor(
            self.lines,
            timeout=0.1,
            clock=self.clock,
            writer=self.writer,
            poller=self.poller,
            **kw,
        )


class MonitorTests(unittest.TestCase):
    def test_capture_is_queued_before_waiting_on_usb_reply(self):
        from bridge_uart import write_then_poll_uart, poll_uart

        class Lines:
            def __init__(self):
                self.sent = bytearray()
                self.serial = self
                self.writes = []
                self.responses = [b"WOK", b"RX 0002 00000022 5500"]

            def write(self, data):
                self.writes.append(data)
                return len(data)

            def read(self):
                return self.responses.pop(0)

        lines = Lines()
        write_then_poll_uart(lines, b"ab")
        self.assertEqual(lines.writes, [b"W\x02\0abP"])
        self.assertEqual(poll_uart(lines), b"\x55\0")
        self.assertEqual(len(lines.writes), 1)

    def test_normal_frame_matches_real_query_and_echo_not_sequence(self):
        self.assertEqual(m.frame(b"\x01\x02").hex(), "55000101010002a60102d241")
        link = Link()
        client = link.monitor()
        self.assertEqual(client.read(0xC0000010, 128), bytes(range(16, 144)))
        self.assertEqual(link.lines.received, b"")
        self.assertEqual(link.lines.pending, b"keep")
        self.assertGreater(client.wire_receipt()["received_wire_bytes"], 0)
        self.assertEqual(client.jedec(), b"\xef\x40\x17")

    def test_retry_reads_but_never_uncertain_transport_or_ram_write(self):
        link = Link()
        link.drop = 1
        client = link.monitor(read_retries=1)
        self.assertEqual(len(client.read(0, 8)), 8)
        self.assertEqual(len(link.requests), 2)
        link = Link()
        link.fail_write = True
        with self.assertRaises(OSError):
            link.monitor().read(0, 8)
        self.assertEqual(len(link.requests), 1)
        link = Link()
        link.drop = 1
        with self.assertRaises(TimeoutError):
            link.monitor().write_ram(0x8001000, b"abcdefgh")
        self.assertEqual(len(link.requests), 1)
        link = Link()
        client = link.monitor()
        self.assertEqual(client.write_ram(0x8001000, b"abcdefgh"), b"abcdefgh")

    def test_bounds_reject_mmio_flash_writes_and_bad_metadata(self):
        link = Link()
        client = link.monitor()
        for addr, count in [
            (0xC0800000, 1),
            (0xC07FFFFF, 2),
            (0xFFFFEE00, 4),
            (0x08030000, 8),
            (0, 129),
        ]:
            with self.assertRaises(ValueError):
                client.read(addr, count)
        for addr, data in [(0xC0000000, b"abcdefgh"), (1, b"abcdefgh"), (0, b"x")]:
            with self.assertRaises(ValueError):
                client.write_ram(addr, data)
        with self.assertRaises(ValueError):
            client.sfdp(0x3FFF, 2)
        self.assertEqual(link.requests, [])
        with self.assertRaises(ValueError):
            Link(0x1000000).monitor().capacity()

    def test_density_factory_headers_then_stream_dump_and_bounded_journal(self):
        link = Link()
        client = link.monitor()
        size = link.capacity
        with tempfile.TemporaryDirectory(dir=ROOT / ".tools") as directory:
            path = Path(directory) / "dump.bin"
            receipt = client.dump(path)
            self.assertEqual(receipt["completed_bytes"], size)
            self.assertEqual(path.stat().st_size, size)
            self.assertEqual(
                receipt["sha256_prefix"], hashlib.sha256(path.read_bytes()).hexdigest()
            )
            self.assertEqual(receipt["state"], "complete")
            self.assertEqual(set(receipt["factory_headers"]), {"0x40000", "0x100000"})
            reads = [r for r in link.requests if r[0] == "M"]
            self.assertEqual(
                [r[1] for r in reads[:3]], [0xC0040000, 0xC0100000, 0xC0000000]
            )
            self.assertLess(link.max_received, 8192)
            self.assertEqual(link.lines.received, b"")
            self.assertGreater(receipt["received_wire_bytes"], 262144)
            self.assertEqual(
                json.loads(path.with_suffix(".bin.progress.json").read_text()), receipt
            )
            with self.assertRaises(ValueError):
                client.dump(path)

    def test_write_echo_mismatch_fails_once(self):
        link = Link()
        link.bad_echo = True
        with self.assertRaises(m.MonitorError):
            link.monitor().write_ram(0, b"abcdefgh")
        self.assertEqual(len(link.requests), 1)

    def test_interrupted_dump_resumes_exact_prefix_and_rejects_tampering(self):
        link = Link(capacity=512)
        client = link.monitor()
        original = client.read

        def interrupted(address, count):
            if address == 0xC0000100:
                raise TimeoutError("isolated interruption")
            return original(address, count)

        client.read = interrupted
        with tempfile.TemporaryDirectory(dir=ROOT / ".tools") as directory:
            path = Path(directory) / "dump.bin"
            with self.assertRaises(TimeoutError):
                client.dump(path)
            prefix = path.read_bytes()
            self.assertEqual(len(prefix), 256)
            path.write_bytes(b"x" + prefix[1:])
            with self.assertRaisesRegex(ValueError, "prefix hash mismatch"):
                Link(capacity=512).monitor().dump(path, resume=True)
            path.write_bytes(prefix)
            bad = Link(capacity=512)
            bad.bad_echo = True
            # Use correct metadata, but return a different live first anchor.
            bad_client = bad.monitor()
            bad_client.capacity = lambda: client.capacity()
            with self.assertRaisesRegex(ValueError, "anchors differ"):
                bad_client.dump(path, resume=True)
            receipt = Link(capacity=512).monitor().dump(path, resume=True)
            self.assertEqual(receipt["state"], "complete")
            self.assertEqual(receipt["resumed_from_bytes"], 256)
            self.assertEqual(path.read_bytes(), bytes(range(256)) * 2)


if __name__ == "__main__":
    unittest.main()
