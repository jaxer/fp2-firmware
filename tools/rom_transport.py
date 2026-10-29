"""Bounded ESP32 ROM transport; no session-specific state or hardware CLI."""

from __future__ import annotations


import hashlib

import os

from pathlib import Path

import struct


import math


import time

from typing import Protocol

ESPTOOL_VERSION = "5.6.0"

ESPTOOL_LOADER_SHA256 = (
    "6f178df74dc3cfc13ea8c3f41a9e79ea203efdf6e2e90af62d1d131eeb5a5c05"
)

REGISTERS = (
    ("uart0_clkdiv_metadata", 0x3FF40014),
    ("uart2_clock_enable", 0x3FF000C0),
    ("uart2_reset_enable", 0x3FF000C4),
    ("uart2_raw_interrupts", 0x3FF6E004),
    ("uart2_interrupt_enable", 0x3FF6E00C),
    ("uart2_clkdiv", 0x3FF6E014),
    ("uart2_autobaud", 0x3FF6E018),
    ("uart2_status", 0x3FF6E01C),
    ("uart2_conf0", 0x3FF6E020),
    ("uart2_conf1", 0x3FF6E024),
    ("uart2_rs485_config", 0x3FF6E044),
    ("uart2_memory_config", 0x3FF6E058),
    ("uart2_rx_memory_status", 0x3FF6E060),
    ("gpio_output_latch", 0x3FF44004),
    ("gpio_output_enable", 0x3FF44020),
    ("gpio13_pad", 0x3FF440BC),
    ("gpio18_pad", 0x3FF440D0),
    ("gpio19_pad", 0x3FF440D4),
    ("uart2_rx_matrix_signal198", 0x3FF44448),
    ("gpio13_output_matrix", 0x3FF44564),
    ("gpio18_output_matrix", 0x3FF44578),
    ("gpio19_output_matrix", 0x3FF4457C),
    ("gpio13_iomux", 0x3FF49038),
    ("gpio18_iomux", 0x3FF49070),
    ("gpio19_iomux", 0x3FF49074),
)

ALLOWLIST = frozenset(address for _, address in REGISTERS)

MAX_COMMANDS = len(REGISTERS)

COMMAND_TIMEOUT = 0.25

TOTAL_TIMEOUT = 8.0


class RegisterReader(Protocol):
    IS_STUB: bool
    CHIP_NAME: str
    sync_stub_detected: bool

    def read_reg(self, addr: int, timeout: float) -> int: ...


def read_allowed(transport: RegisterReader, address: int, timeout: float) -> int:
    if type(address) is not int or address not in ALLOWLIST:
        raise ValueError("register outside fixed nonconsuming allowlist")
    if not math.isfinite(timeout) or not 0 < timeout <= COMMAND_TIMEOUT:
        raise ValueError("timeout outside command bound")
    value = transport.read_reg(address, timeout=timeout)
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("invalid 32-bit register response")
    return value


def checkpoint(transport: RegisterReader, *, clock=time.monotonic) -> dict:
    """Use an already attached ROM reader. No opening, reset, sync or writes.

    The caller must supply esptool5.6.0's ESP32ROM, validate its provenance,
    ensure exclusive existing ROM ownership, and set finite serial write timeout.
    This function deliberately cannot establish device identity or ROM entry.
    """
    if (
        getattr(transport, "IS_STUB", None) is not False
        or getattr(transport, "CHIP_NAME", None) != "ESP32"
        or getattr(transport, "sync_stub_detected", None) is not False
    ):
        raise ValueError("requires already attached ESP32 ROM reader, not a stub")
    started = clock()
    deadline = started + TOTAL_TIMEOUT
    rows = []
    for name, address in REGISTERS:
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError("checkpoint total deadline reached; no retry")
        value = read_allowed(transport, address, min(COMMAND_TIMEOUT, remaining))
        if clock() > deadline:
            raise TimeoutError("checkpoint transport exceeded total deadline")
        rows.append(
            {"name": name, "address": f"0x{address:08x}", "value": f"0x{value:08x}"}
        )
    return {
        "mode": "FIXED_REGISTER_CHECKPOINT",
        "registers": rows,
        "commands": len(rows),
        "writes": 0,
        "reset_or_sync": False,
        "IS_STUB": transport.IS_STUB,
        "sync_stub_detected": transport.sync_stub_detected,
        "CHIP_NAME": transport.CHIP_NAME,
        "rom_identity_independently_verified": False,
        "clock_inference": "not computed: source/host baud remain independently verified metadata",
    }


SOURCE_PINS = {
    "esptool.loader": ESPTOOL_LOADER_SHA256,
    "esptool.targets.esp32": "97e6f0abb526dd0ebfa0e4a00baf22b2257e41ab43f9d9412e8d063ba1bf7d93",
    "esptool.reset": "74d0ca26430c0cb8cfcdbf78fa71c90b88385ebd8db2977590fc11c16dfa5121",
    "esp_pylib.serial_reset": "52d636ed8eff0855cf9e8c44deb1c5392ea642be153f9dee2931ad334d474b88",
}


class CommandBudget:
    """Guard esptool's entire ROM command path, including connect internals."""

    def __init__(self, command, *, clock=time.monotonic):
        self.command = command
        self.clock = clock
        self.deadline = clock() + 60
        self.count = 0
        self.read_deadline = self.deadline

    def __call__(self, op=None, data=b"", chk=0, wait_response=True, timeout=3):
        if op == 0x08:
            if data != b"\x07\x07\x12\x20" + 32 * b"\x55":
                raise ValueError("unexpected ESP ROM SYNC payload")
        elif op == 0x0A:
            if len(data) != 4 or struct.unpack("<I", data)[0] not in ALLOWLIST:
                raise ValueError("unexpected ROM register read")
        elif op is not None or data:
            raise ValueError("ROM command outside SYNC/read-only checkpoint scope")
        if chk != 0 or wait_response is not True:
            raise ValueError("unexpected ROM command flags")
        self.count += 1
        remaining = self.deadline - self.clock()
        if self.count > 112 or remaining <= 0:
            raise TimeoutError("ROM command count/deadline exhausted")
        bounded_timeout = min(timeout, COMMAND_TIMEOUT, remaining)
        self.read_deadline = self.clock() + bounded_timeout
        return self.command(op, data, chk, wait_response, timeout=bounded_timeout)


def live_adapter(port, *, command_policy=CommandBudget):
    """Import and verify installed sources before constructing an unopened port."""
    import importlib
    import importlib.metadata

    if importlib.metadata.version("esptool") != ESPTOOL_VERSION:
        raise ValueError("requires installed esptool5.6.0; no install is performed")
    modules = {}
    for name, expected in SOURCE_PINS.items():
        module = importlib.import_module(name)
        if hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() != expected:
            raise ValueError("esptool/reset source provenance mismatch: " + name)
        modules[name] = module
    loader = modules["esptool.loader"]
    for key in ("custom_reset_sequence", "custom_hard_reset_sequence", "reset_delay"):
        if loader.cfg.get(key) is not None:
            raise ValueError("custom esptool reset configuration is outside this plan")
    if os.environ.get("ESPTOOL_ENV_FPGA", "").strip() == "1":
        raise ValueError("FPGA reset override is outside this plan")
    import serial

    serial_port = serial.Serial(
        port=None,
        baudrate=115200,
        timeout=COMMAND_TIMEOUT,
        write_timeout=COMMAND_TIMEOUT,
        exclusive=True,
    )
    serial_port.port = port
    try:
        rom = modules["esptool.targets.esp32"].ESP32ROM(serial_port, baud=115200)
        serial_port.write_timeout = COMMAND_TIMEOUT
        serial_port.timeout = COMMAND_TIMEOUT
        budget = command_policy(rom.command)
        rom.command = budget
        original_read = serial_port.read

        def bounded_read(size=1):
            if time.monotonic() >= budget.read_deadline:
                raise loader.FatalError("ROM serial read deadline exhausted")
            result = original_read(size)
            if time.monotonic() > budget.read_deadline:
                raise loader.FatalError("ROM serial read exceeded deadline")
            return result

        serial_port.read = bounded_read
    except BaseException:
        serial_port.close()
        raise

    class Adapter:
        def open(self):
            serial_port.open()

        def connect(self):
            # detecting=True skips security/identity register reads and post-connect hooks.
            rom.connect(
                mode="default-reset", attempts=2, detecting=True, warnings=False
            )
            if rom.IS_STUB or rom.sync_stub_detected:
                raise ValueError("ROM SYNC identified a stub")

        def reader(self):
            return rom

        def hard_reset(self):
            rom.hard_reset()

        def close(self):
            serial_port.close()

    return Adapter()


def session_guard():
    """Compatibility hook: caller owns exclusive serial access and backup validation."""
    return {"mode": "explicit_research_session"}
