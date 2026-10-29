#!/usr/bin/env python3
"""Private research-monitor client for an already-owned RAM-bridge session.
No port opening, image installation, flash writes, reset or live CLI is provided.

Use Monitor(existing_lines).read(address,count), write_ram(address,data),
sfdp(offset,count), jedec(), or dump(new_path_under_tools, repeat=False).
A dump records actual identification/BFPT bytes, fixed factory headers, rolling
wire SHA256 and progress. Error responses and uncertain transport writes are not
retried. Echo correlation cannot certify freshness of a delayed duplicate reply;
repeat=True compares matching byte replies, not an authenticated snapshot.
"""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
import struct
import time
from audit_capture import modbus_crc
from bridge_uart import write_then_poll_uart, poll_uart

ROOT = Path(__file__).resolve().parents[1]
RAM = ((0, 0x40000), (0x08000000, 0x08030000))
READ = RAM + ((0xC0000000, 0xC0800000),)


def within(address, count, ranges):
    return (
        type(address) is int
        and type(count) is int
        and count > 0
        and any(lo <= address and count <= hi - address for lo, hi in ranges)
    )


def frame(payload, sequence=1, operation=1):
    head = bytearray(
        b"\x55\0\1" + bytes([sequence, operation]) + len(payload).to_bytes(2, "big")
    )
    head.append((-sum(head)) & 255)
    raw = bytes(head) + payload
    return raw + modbus_crc(raw).to_bytes(2, "little")


class MonitorError(RuntimeError):
    def __init__(self, message, *, status=None):
        super().__init__(message)
        self.status = status


class Monitor:
    def __init__(
        self,
        lines,
        *,
        timeout=0.5,
        read_retries=2,
        clock=time.monotonic,
        writer=write_then_poll_uart,
        poller=poll_uart,
        event=lambda row: None,
    ):
        if not 0 < timeout <= 10 or not 0 <= read_retries <= 3:
            raise ValueError("invalid bounded policy")
        if b"X" in lines.sent:
            raise ValueError("bridge already exited")
        self.lines = lines
        self.timeout = timeout
        self.retries = read_retries
        self.clock = clock
        serial = getattr(lines, "serial", None)
        if serial is not None:
            serial.timeout = 0.005
        self.writer = writer
        self.poller = poller
        self.event = event
        self.sequence = 0
        self.pending = bytearray()
        self.wire_hash = hashlib.sha256()
        self.wire_bytes = 0
        self.requests = 0
        self.rejected = 0
        self.last_frames = []
        # Per-response buffers are cleared after harvesting; Lines.pending is preserved.
        lines.received_limit = 8192
        self._harvest()

    def _harvest(self):
        data = bytes(self.lines.received)
        self.wire_hash.update(data)
        self.wire_bytes += len(data)
        self.lines.received.clear()

    def wire_receipt(self):
        return {
            "received_wire_bytes": self.wire_bytes,
            "received_wire_sha256": self.wire_hash.hexdigest(),
            "requests": self.requests,
            "rejected_frames": self.rejected,
            "last_frame_hex": self.last_frames,
        }

    def _frames(self):
        b = self.pending
        while len(b) >= 3:
            start = b.find(b"\x55\0\1")
            if start < 0:
                del b[:-2]
                return
            if start:
                del b[:start]
            if len(b) < 8:
                return
            n = int.from_bytes(b[5:7], "big")
            if sum(b[:8]) & 255 or n > 512:
                del b[0]
                self.rejected += 1
                continue
            total = n + 10
            if len(b) < total:
                return
            raw = bytes(b[:total])
            del b[:total]
            if modbus_crc(raw[:-2]) != int.from_bytes(raw[-2:], "little"):
                self.rejected += 1
                continue
            self.last_frames.append(raw.hex())
            self.last_frames = self.last_frames[-8:]
            yield raw[4], raw[8:-2]

    def _exchange_once(self, mode, address, count, data=b""):
        self.sequence = (self.sequence + 1) & 255
        request = (
            b"\x01\x02FP2"
            + mode.encode()
            + b"\x01"
            + struct.pack(">I", address)
            + bytes([count])
            + data
        )
        self.requests += 1
        try:
            self.writer(self.lines, frame(request, self.sequence))
        except TimeoutError as exc:
            raise OSError("uncertain bridge W completion; request not retried") from exc
        finally:
            self._harvest()
        deadline = self.clock() + self.timeout
        while self.clock() < deadline:
            try:
                chunk = self.poller(self.lines)
            finally:
                self._harvest()
            self.pending.extend(chunk)
            if len(self.pending) > 4096:
                raise ValueError("monitor receive buffer bound")
            for operation, payload in self._frames():
                if operation != 4 or payload[:3] != b"\x01\x02\x05" or len(payload) < 5:
                    continue
                raw = payload[5:]
                if int.from_bytes(payload[3:5], "big") != len(raw) or len(raw) < 8:
                    continue
                if (
                    raw[:2] != b"\x03" + mode.encode()
                    or int.from_bytes(raw[3:7], "big") != address
                ):
                    continue
                status, n = raw[2], raw[7]
                if len(raw) != 8 + n:
                    continue
                if status:
                    if n:
                        raise ValueError("error reply includes data")
                    raise MonitorError(
                        f"monitor status {status} for {mode}@{address:08x}",
                        status=status,
                    )
                if n != count:
                    continue
                body = raw[8:]
                if mode == "W" and body != data:
                    raise MonitorError("write echo differs; never retry")
                self.event(
                    {
                        "mode": mode,
                        "address": address,
                        "count": count,
                        "data_sha256": hashlib.sha256(body).hexdigest(),
                    }
                )
                return body
        raise TimeoutError(f"no correlated monitor reply for {mode}@{address:08x}")

    def _exchange(self, mode, address, count, data=b""):
        # A failed raw W bridge write is uncertain, even for a read request: never
        # retry that transport write. Only an unanswered completed READ may repeat.
        for attempt in range(1 + (0 if mode == "W" else self.retries)):
            try:
                return self._exchange_once(mode, address, count, data)
            except TimeoutError:
                if mode == "W" or attempt == self.retries:
                    raise

    def read(self, address, count):
        if not 1 <= count <= 128 or not within(address, count, READ):
            raise ValueError("read outside RAM/QSPI window")
        return self._exchange("M", address, count)

    def write_ram(self, address, data):
        data = bytes(data)
        if (
            address % 8
            or len(data) not in (8, 16, 24, 32)
            or not within(address, len(data), RAM)
        ):
            raise ValueError("write must be aligned8 and wholly inside RAM")
        # Firmware additionally excludes its own image and active handler stack.
        return self._exchange("W", address, len(data), data)

    def sfdp(self, offset, count):
        if not 1 <= count <= 128 or not within(offset, count, ((0, 0x4000),)):
            raise ValueError("SFDP bound")
        return self._exchange("S", offset, count)

    def jedec(self):
        return self._exchange("J", 0, 3)

    def capacity(self):
        jedec = self.jedec()
        header = self.sfdp(0, 8)
        if header[:4] != b"SFDP" or header[5] != 1 or header[6] >= 32:
            raise ValueError("unsupported SFDP header")
        headers = (
            self.sfdp(8, 8 * (header[6] + 1))
            if header[6] < 16
            else b"".join(
                self.sfdp(8 + i * 8, min(16, header[6] + 1 - i) * 8)
                for i in range(0, header[6] + 1, 16)
            )
        )
        choices = []
        for i in range(header[6] + 1):
            h = headers[8 * i : 8 * i + 8]
            if h[0] == 0 and h[7] == 0xFF and h[2] == 1 and h[3] >= 2:
                pointer = int.from_bytes(h[4:7], "little")
                if within(pointer, 8, ((0, 0x4000),)):
                    choices.append((h[2], h[1], pointer, h))
        if not choices:
            raise ValueError("no bounded BFPT")
        _, _, pointer, parameter = max(choices)
        table = self.sfdp(pointer, 8)
        density = int.from_bytes(table[4:8], "little")
        if density & 0x80000000:
            exponent = density & 0x7FFFFFFF
            if not 3 <= exponent <= 26:
                raise ValueError("density exceeds supported 8MiB mapped window")
            bits = 1 << exponent
        else:
            bits = density + 1
        if bits % 8 or not 0 < bits // 8 <= 0x800000:
            raise ValueError("invalid/beyond-mapping density")
        return {
            "capacity_bytes": bits // 8,
            "jedec_hex": jedec.hex(),
            "sfdp_header_hex": header.hex(),
            "parameter_headers_hex": headers.hex(),
            "bfpt_pointer": pointer,
            "bfpt_header_hex": parameter.hex(),
            "bfpt_first8_hex": table.hex(),
        }

    def dump(self, path, *, repeat=False, resume=False):
        path = Path(path).resolve()
        if not path.is_relative_to(ROOT / ".tools"):
            raise ValueError("dump must stay under ignored .tools")
        progress = path.with_suffix(path.suffix + ".progress.json")
        previous = None
        if resume:
            if not path.exists() or not progress.exists():
                raise ValueError(
                    "resume requires existing captured prefix and progress"
                )
            previous = json.loads(progress.read_text())
            if previous.get("state") not in ("incomplete", "reading"):
                raise ValueError("not an incomplete capture")
        elif path.exists() or progress.exists():
            raise ValueError("new dump path required")
        metadata = self.capacity()
        size = metadata["capacity_bytes"]
        headers = {}
        for offset in (0x40000, 0x100000):
            if offset + 128 <= size:
                data = self.read(0xC0000000 + offset, 128)
                headers[hex(offset)] = {
                    "bytes_hex": data.hex(),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
        path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        completed = 0
        if previous is not None:
            completed = previous["completed_bytes"]
            if (
                type(completed) is not int
                or not 0 < completed < size
                or completed % 128
                or path.stat().st_size != completed
                or previous["metadata"] != metadata
            ):
                raise ValueError("resume prefix size or chip metadata mismatch")
            with path.open("rb") as captured:
                while data := captured.read(1024 * 1024):
                    digest.update(data)
                captured.seek(0)
                first = captured.read(128)
                captured.seek(completed - 128)
                last = captured.read(128)
            if digest.hexdigest() != previous["sha256_prefix"]:
                raise ValueError("captured prefix hash mismatch")
            if (
                self.read(0xC0000000, 128) != first
                or self.read(0xC0000000 + completed - 128, 128) != last
            ):
                raise ValueError("resume flash anchors differ")
        resumed_from = completed

        def record(state, error=None):
            row = {
                "state": state,
                "dump_path": str(path),
                "completed_bytes": completed,
                "sha256_prefix": digest.hexdigest(),
                "sha256": digest.hexdigest() if state == "complete" else None,
                "metadata": metadata,
                "factory_headers": headers,
                "repeat_each_chunk": repeat,
                "resumed_from_bytes": resumed_from,
                **self.wire_receipt(),
            }
            if error is not None:
                row["error"] = str(error)
            temporary = progress.with_suffix(progress.suffix + ".tmp")
            temporary.write_text(json.dumps(row, indent=2) + "\n")
            temporary.replace(progress)
            return row

        record("starting")
        try:
            with path.open("ab" if resume else "xb") as output:
                path.chmod(0o600)
                while completed < size:
                    n = min(128, size - completed)
                    address = 0xC0000000 + completed
                    data = self.read(address, n)
                    if repeat and self.read(address, n) != data:
                        raise MonitorError("repeated chunk mismatch")
                    output.write(data)
                    digest.update(data)
                    completed += n
                    if completed % 65536 == 0:
                        output.flush()
                        record("reading")
                output.flush()
        except Exception as exc:
            record("incomplete", exc)
            raise
        return record("complete")


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "mode": "OFFLINE_LIBRARY_NO_DEVICE_ACCESS",
                "operations": [
                    "M bounded RAM/QSPI read",
                    "W aligned RAM-only write",
                    "S SFDP",
                    "J JEDEC",
                ],
                "live_entrypoint": None,
                "dump": "Monitor(existing_owned_lines).dump(new_ignored_path)",
            }
        )
    )
