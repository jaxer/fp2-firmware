#!/usr/bin/env python3
"""Load this project's bounded bridge into ESP32 RAM; never flash. Offline default."""

from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import time
import rom_transport as cp

IRAM = (0x40090000, 0x40094000)
DRAM = (0x3FFB0000, 0x3FFB2000)
BLOCK = 512
ROOT = Path(__file__).resolve().parents[1]


def elf_segments(raw):
    if len(raw) < 52 or raw[:7] != b"\x7fELF\x01\x01\x01":
        raise ValueError("requires little-endian ELF32")
    h = struct.unpack_from("<16sHHIIIIIHHHHHH", raw)
    _, kind, machine, version, entry, phoff, _, _, ehsize, phsize, count, *_ = h
    if (
        kind != 2
        or machine != 94
        or version != 1
        or ehsize != 52
        or phsize != 32
        or not 1 <= count <= 8
    ):
        raise ValueError("requires bounded executable Xtensa ELF")
    if phoff + count * phsize > len(raw) or entry != IRAM[0]:
        raise ValueError("unexpected RAM bridge entry/program header bounds")
    segments, extents = [], []
    for n in range(count):
        ptype, offset, virtual, physical, size, memory_size, flags, alignment = (
            struct.unpack_from("<8I", raw, phoff + n * phsize)
        )
        if ptype != 1:
            continue
        if (
            virtual != physical
            or size > memory_size
            or offset + size > len(raw)
            or not memory_size
            or not any(
                lo <= virtual < virtual + memory_size <= hi for lo, hi in (IRAM, DRAM)
            )
        ):
            raise ValueError("segment outside exact bridge RAM ranges")
        if any(
            virtual < end and virtual + memory_size > start for start, end in extents
        ):
            raise ValueError("overlapping bridge segments")
        extents.append((virtual, virtual + memory_size))
        if size:
            segments.append(
                {
                    "address": virtual,
                    "memory_size": memory_size,
                    "flags": flags,
                    "data": raw[offset : offset + size],
                }
            )
    if not segments or not any(
        s["address"] <= entry < s["address"] + len(s["data"]) and s["flags"] & 1
        for s in segments
    ):
        raise ValueError("entry not backed by executable RAM bytes")
    return entry, segments


def memory_commands(entry, segments):
    commands = []
    for segment in segments:
        # ROM memcpy uses byte/halfword tails for odd lengths. ESP32's IRAM
        # pool accepts word stores only; standard ESP images pad segments too.
        data = segment["data"] + bytes(-len(segment["data"]) % 4)
        address = segment["address"]
        if address % 4 or not any(
            lo <= address < address + len(data) <= hi for lo, hi in (IRAM, DRAM)
        ):
            raise ValueError("padded RAM transfer exceeds aligned bridge bounds")
        commands.append(
            (
                5,
                struct.pack(
                    "<IIII",
                    len(data),
                    (len(data) + BLOCK - 1) // BLOCK,
                    BLOCK,
                    segment["address"],
                ),
                0,
                True,
            )
        )
        for seq, start in enumerate(range(0, len(data), BLOCK)):
            chunk = data[start : start + BLOCK]
            checksum = 0xEF
            for byte in chunk:
                checksum ^= byte
            commands.append(
                (7, struct.pack("<IIII", len(chunk), seq, 0, 0) + chunk, checksum, True)
            )
    # Avoid a SLIP reader buffering away the bridge's immediately emitted banner.
    commands.append((6, struct.pack("<II", 0, entry), 0, False))
    return commands


def validated_build(path):
    path = Path(path)
    raw = path.read_bytes()
    entry, segments = elf_segments(raw)
    manifest = json.loads((path.parent / "receipt.json").read_text())
    if (
        manifest.get("mode") != "OFFLINE_RAM_BRIDGE_BUILD_NO_UPLOAD"
        or manifest.get("elf_sha256") != hashlib.sha256(raw).hexdigest()
        or manifest.get("entrypoint") != entry
    ):
        raise ValueError("bridge ELF differs from build receipt")
    sources = manifest.get("source_sha256", {})
    if set(sources) != {"bridge.c", "entry.S", "bridge.ld", "build.py"}:
        raise ValueError("unexpected RAM bridge source manifest")
    for name, expected in sources.items():
        if (
            hashlib.sha256(
                (ROOT / "firmware/esp32_ram_bridge" / name).read_bytes()
            ).hexdigest()
            != expected
        ):
            raise ValueError("RAM bridge source changed after build")
    rows = manifest.get("segments", [])
    if len(rows) != len(segments):
        raise ValueError("RAM segment manifest mismatch")
    for segment, row in zip(segments, rows):
        if (
            row.get("address") != segment["address"]
            or row.get("size") != len(segment["data"])
            or row.get("memory_size") != segment["memory_size"]
            or row.get("sha256") != hashlib.sha256(segment["data"]).hexdigest()
        ):
            raise ValueError("RAM segment bytes differ from build receipt")
    return raw, entry, segments


class RAMPolicy:
    def __init__(self, command, *, clock=time.monotonic):
        self.command = command
        self.clock = clock
        self.base = cp.CommandBudget(command, clock=clock)
        self.phase = "connect"
        self.expected = []
        self.index = 0
        self._read_deadline = self.base.deadline

    @property
    def read_deadline(self):
        return (
            self.base.read_deadline if self.phase == "connect" else self._read_deadline
        )

    @read_deadline.setter
    def read_deadline(self, value):
        self._read_deadline = value

    def prepare(self, commands):
        self.expected = list(commands)
        self.index = 0
        self.phase = "upload"
        self.upload_deadline = self.clock() + 30

    def begin_baud_calibration(self):
        if self.phase != "connect":
            raise ValueError("calibration outside checkpoint phase")
        self.calibration_registers = [0x3FF5F06C, 0x3FF5A010]
        self.phase = "baud_calibration"

    def allow_fast_baud(self, wire_baud=921600):
        if self.phase not in ("connect", "baud_calibration_done"):
            raise ValueError("baud change outside checkpoint phase")
        if not 829440 <= wire_baud <= 1013760:
            raise ValueError("ROM baud correction outside ten percent")
        self.wire_baud = wire_baud
        self.phase = "baud"

    def __call__(self, op=None, data=b"", chk=0, wait_response=True, timeout=3):
        if self.phase == "connect":
            return self.base(op, data, chk, wait_response, timeout)
        if self.phase == "baud_calibration":
            if not self.calibration_registers or (op, data, chk, wait_response) != (
                10,
                struct.pack("<I", self.calibration_registers[0]),
                0,
                True,
            ):
                raise ValueError("unexpected baud calibration read")
            self.calibration_registers.pop(0)
            if not self.calibration_registers:
                self.phase = "baud_calibration_done"
            self.read_deadline = self.clock() + 0.25
            return self.command(
                op, data, chk, wait_response, timeout=min(timeout, 0.25)
            )
        if self.phase == "baud":
            if (op, data, chk, wait_response) != (
                15,
                struct.pack("<II", self.wire_baud, 0),
                0,
                True,
            ):
                raise ValueError("unexpected ROM baud change")
            self.phase = "baud_done"  # uncertain change is never repeated
            self.read_deadline = self.clock() + 0.25
            return self.command(
                op, data, chk, wait_response, timeout=min(timeout, 0.25)
            )
        if (
            self.phase != "upload"
            or self.index >= len(self.expected)
            or (op, data, chk, wait_response) != self.expected[self.index]
        ):
            raise ValueError(
                "ROM command differs from exact verified RAM image transfer"
            )
        remaining = self.upload_deadline - self.clock()
        if remaining <= 0:
            raise TimeoutError("RAM upload deadline exhausted")
        self.index += 1  # never resend an ambiguously completed packet
        bounded = min(timeout, 0.25, remaining)
        self.read_deadline = self.clock() + bounded
        return self.command(op, data, chk, wait_response, timeout=bounded)

    def raw_mode(self):
        if self.index != len(self.expected):
            raise ValueError("RAM transfer incomplete")
        self.phase = "raw"
        self.read_deadline = self.clock() + 5


class Lines:
    def __init__(self, serial, policy, *, clock=time.monotonic):
        self.serial = serial
        self.policy = policy
        self.clock = clock
        self.pending = bytearray()
        self.received = bytearray()
        self.sent = bytearray()
        self.received_limit = 8192

    def read(self, seconds=3):
        deadline = self.clock() + seconds
        self.policy.read_deadline = deadline + 0.3
        while self.clock() < deadline:
            if b"\n" in self.pending:
                line, _, tail = self.pending.partition(b"\n")
                self.pending = bytearray(tail)
                return bytes(line)
            if len(self.pending) > 4096 or len(self.received) > self.received_limit:
                raise ValueError("bridge response size bound exceeded")
            block = self.serial.read(max(1, min(self.serial.in_waiting, 1024)))
            self.received.extend(block)
            self.pending.extend(block)
        raise TimeoutError("bridge line timeout")

    def send(self, command):
        if command not in (b"Q", b"R", b"B", b"T", b"X"):
            raise ValueError("unsupported fixed bridge command")
        if (
            command in self.sent
            or (command in (b"Q", b"B", b"T") and self.sent)
            or b"X" in self.sent
        ):
            raise ValueError("bridge command order/repetition refused")
        self.sent.extend(command)  # never retry a partial/uncertain write
        if self.serial.write(command) != 1:
            raise OSError("short bridge command write")


def _parse_capture(line, kind, maximum):
    match = re.fullmatch(
        re.escape(kind) + rb" ([0-9a-f]{4}) ([0-9a-f]{8}) ([0-9a-f]*)", line
    )
    if not match:
        raise ValueError("invalid bridge RX response")
    length = int(match[1], 16)
    data = bytes.fromhex(match[3].decode())
    if length > maximum or len(data) != length:
        raise ValueError("bridge RX length mismatch")
    return {
        "raw_bytes_hex": data.hex(),
        "byte_count": length,
        "raw_interrupt": int(match[2], 16),
        "uart_error_flags_observed": bool(int(match[2], 16) & 0x1C),
    }


def parse_rx(line):
    return _parse_capture(line, b"RX", 256)


def parse_boot(line):
    return _parse_capture(line, b"BOOT", 1024)


def parse_trace(line):
    return _parse_capture(line, b"TRACE", 1024)


def startup_banner(lines, *, clock=time.monotonic):
    # MEM_END's binary SLIP acknowledgement can itself contain newline bytes.
    # Retain it, but do not mistake its first fragment for the ASCII banner.
    deadline = clock() + 3
    fragments = []
    for _ in range(16):
        remaining = deadline - clock()
        if remaining <= 0:
            break
        line = lines.read(seconds=remaining)
        fragments.append(line)
        if b"ERR INIT" in line:
            raise ValueError("RAM bridge initialization refused")
        if line.endswith(b"FP2RAM1"):
            return b"\n".join(fragments)
    raise ValueError("RAM bridge identity banner missing/refused")


def run(
    port,
    elf,
    output,
    *,
    query_once=False,
    boot_capture=False,
    trace_capture=False,
    adapter_factory=None,
    guard=cp.session_guard,
    exchange=None,
    radar_flash_write_requested=False,
    resume_on_error=True,
    baud=115200,
):
    if baud not in (115200, 921600):
        raise ValueError("unsupported host UART baud")
    if sum((query_once, boot_capture, trace_capture, exchange is not None)) > 1:
        raise ValueError("query and radar-reset capture must be separate experiments")
    if not isinstance(port, str) or not port.startswith(
        ("/dev/cu.", "/dev/ttyUSB", "/dev/ttyACM")
    ):
        raise ValueError("requires explicit local FTDI path")
    raw, entry, segments = validated_build(elf)
    commands = memory_commands(entry, segments)
    baseline = guard()
    fd = os.open(
        output,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    result = {
        "mode": "ESP32_RAM_ONLY_BRIDGE",
        "elf_sha256": hashlib.sha256(raw).hexdigest(),
        "entrypoint": entry,
        "host_baud": baud,
        "query_requested": query_once,
        "radar_reset_requested": boot_capture,
        "stock_trace_diagnostic_requested": trace_capture,
        "success": False,
        "errors": [],
        "flash_operations": None if radar_flash_write_requested else 0,
        "esp32_flash_operations": 0,
        "radar_flash_write_requested": radar_flash_write_requested,
        "session_guard": baseline,
        "normal_boot_reset_returned": False,
        "serial_closed": False,
        "application_recovered": False,
        "segments": [
            {
                "address": s["address"],
                "size": len(s["data"]),
                "memory_size": s["memory_size"],
                "loaded_size": len(s["data"]) + (-len(s["data"]) % 4),
                "padding_bytes": -len(s["data"]) % 4,
                "sha256": hashlib.sha256(s["data"]).hexdigest(),
            }
            for s in segments
        ],
    }
    adapter = lines = policy = None
    opened = False
    try:
        try:
            adapter = (
                adapter_factory
                or (lambda p: cp.live_adapter(p, command_policy=RAMPolicy))
            )(port)
            if guard() != baseline:
                raise ValueError("study state changed before RAM experiment")
            opened = True
            adapter.open()
            adapter.connect()
            rom = adapter.reader()
            if (
                rom.IS_STUB
                or rom.sync_stub_detected
                or not isinstance(rom.command, RAMPolicy)
            ):
                raise ValueError("requires true ESP32 ROM with bounded RAM policy")
            policy = rom.command
            result["checkpoint"] = cp.checkpoint(rom)
            if baud != 115200:
                policy.begin_baud_calibration()
                frequency = rom.get_rom_cal_crystal_freq()
                nominal = 40000000 if frequency > 33000000 else 26000000
                wire_baud = int(baud * frequency // nominal)
                result["baud_calibration"] = {
                    "rom_frequency": frequency,
                    "wire_baud_command": wire_baud,
                }
                policy.allow_fast_baud(wire_baud)
                rom.command(15, struct.pack("<II", wire_baud, 0))
                rom._set_port_baudrate(baud)
                time.sleep(0.05)
                rom.flush_input()
                policy.phase = "connect"
                result["post_baud_checkpoint"] = cp.checkpoint(rom)
            policy.prepare(commands)
            for op, data, checksum, wait in commands:
                rom.check_command(
                    "bounded own-RAM bridge upload", op, data, checksum, timeout=0.25
                ) if wait else rom.command(
                    op, data, checksum, wait_response=False, timeout=0.25
                )
            policy.raw_mode()
            serial = rom._port
            lines = Lines(serial, policy)
            banner = startup_banner(lines)
            result["startup_line_hex"] = banner.hex()
            if exchange is not None:
                result["exchange"] = exchange(lines)
            elif trace_capture:
                lines.send(b"T")
                result["received"] = parse_trace(lines.read(seconds=8))
                result["radar_cleanup_reset_returned"] = lines.read() == b"RESETOK"
                if not result["radar_cleanup_reset_returned"]:
                    raise ValueError("trace cleanup radar reset not confirmed")
            elif boot_capture:
                lines.send(b"B")
                result["received"] = parse_boot(lines.read(seconds=8))
            else:
                if query_once:
                    lines.send(b"Q")
                    if lines.read() != b"QUERYOK":
                        raise ValueError("fixed version query refused/incomplete")
                lines.send(b"R")
                result["received"] = parse_rx(lines.read())
            if exchange is None:
                if result["received"]["uart_error_flags_observed"]:
                    raise ValueError("RAM bridge observed UART error flags")
                result["decoded"] = {"raw_only": True}
        except BaseException as error:
            result["errors"].append(
                {
                    "stage": "ram_bridge",
                    "type": type(error).__name__,
                    "detail": str(error)[:200],
                }
            )
        finally:
            if policy is not None:
                result["transfer_commands_attempted"] = policy.index
                result["transfer_phase"] = policy.phase
            if lines is not None and lines.sent and b"X" not in lines.sent:
                try:
                    lines.send(b"X")
                    result["bridge_register_restore_returned"] = lines.read() == b"BYE"
                    if not result["bridge_register_restore_returned"]:
                        raise ValueError("bridge restoration response missing")
                except BaseException as error:
                    result["errors"].append(
                        {"stage": "bridge_restore", "type": type(error).__name__}
                    )
            if lines is not None:
                result["host_commands_hex"] = lines.sent.hex()
                result["bridge_transport_received_hex"] = lines.received.hex()
            if adapter is not None:
                if opened and (resume_on_error or not result["errors"]):
                    try:
                        adapter.hard_reset()
                        result["normal_boot_reset_returned"] = True
                    except BaseException as error:
                        result["errors"].append(
                            {"stage": "normal_boot_reset", "type": type(error).__name__}
                        )
                elif opened:
                    result["normal_boot_reset_intentionally_skipped_after_error"] = True
                try:
                    adapter.close()
                    result["serial_closed"] = True
                except BaseException as error:
                    result["errors"].append(
                        {"stage": "serial_close", "type": type(error).__name__}
                    )
            result["success"] = (
                not result["errors"]
                and result["normal_boot_reset_returned"]
                and result["serial_closed"]
            )
    finally:
        with os.fdopen(fd, "w") as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write("\n")
    return result
