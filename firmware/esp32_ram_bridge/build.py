#!/usr/bin/env python3
"""Build/audit RAM bridge locally; no serial, upload or package installation."""

from __future__ import annotations
import argparse
import os
import hashlib
import json
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).resolve().parent
DEFAULT_TOOLS = Path(os.environ.get("XTENSA_TOOL_BIN", "."))
IDF = Path(os.environ.get("IDF_PATH", "."))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build(out, tools=DEFAULT_TOOLS):
    out = out.resolve()
    if not out.is_relative_to(ROOT / ".tools"):
        raise ValueError("build output must stay under project .tools")
    out.mkdir(parents=True, exist_ok=True)
    gcc = tools / "xtensa-esp32-elf-gcc"
    objdump = tools / "xtensa-esp32-elf-objdump"
    nm = tools / "xtensa-esp32-elf-nm"
    elf = out / "bridge.elf"
    command = [
        str(gcc),
        "-Os",
        "-g",
        "-ffreestanding",
        "-fno-builtin",
        "-fno-common",
        "-fno-stack-protector",
        "-fno-unwind-tables",
        "-fno-asynchronous-unwind-tables",
        "-ffunction-sections",
        "-fdata-sections",
        "-mabi=windowed",
        "-mlongcalls",
        "-mtext-section-literals",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-nostdlib",
        "-Wl,--gc-sections",
        "-Wl,-Map," + str(out / "bridge.map"),
        "-T",
        str(SOURCE / "bridge.ld"),
        str(SOURCE / "entry.S"),
        str(SOURCE / "bridge.c"),
        "-lgcc",
        "-o",
        str(elf),
    ]
    subprocess.run(command, check=True, text=True)
    raw = elf.read_bytes()
    if raw[:7] != b"\x7fELF\x01\x01\x01" or struct.unpack_from("<H", raw, 18)[0] != 94:
        raise ValueError("requires Xtensa32 little-endian ELF")
    entry, phoff = struct.unpack_from("<II", raw, 24)
    phsize, phnum = struct.unpack_from("<HH", raw, 42)
    if entry != 0x40090000 or phsize != 32:
        raise ValueError("unexpected entry/program headers")
    segments = []
    for i in range(phnum):
        kind, offset, address, physical, size, memory_size, flags, align = (
            struct.unpack_from("<8I", raw, phoff + i * phsize)
        )
        if kind != 1:
            continue
        if physical != address or size > memory_size or offset + size > len(raw):
            raise ValueError("invalid PT_LOAD mapping")
        permitted = (
            0x40090000 <= address
            and address + memory_size <= 0x40092000
            and not flags & 2
        ) or (
            0x3FFB0000 <= address
            and address + memory_size <= 0x3FFB2000
            and not flags & 1
        )
        if not permitted:
            raise ValueError("segment outside bounded executable IRAM / own8KiB DRAM")
        if not size:
            continue
        blob = raw[offset : offset + size]
        path = out / f"segment-{len(segments)}.bin"
        path.write_bytes(blob)
        segments.append(
            {
                "address": address,
                "path": str(path),
                "size": size,
                "memory_size": memory_size,
                "sha256": sha(blob),
                "flags": flags,
            }
        )
    entry_segment = next(
        s for s in segments if s["address"] <= entry < s["address"] + s["size"]
    )
    entry_blob = Path(entry_segment["path"]).read_bytes()
    if entry_blob[entry - entry_segment["address"] :][:3] != bytes.fromhex("364100"):
        raise ValueError("entry must begin windowed ENTRY a1,32")
    fixed_frames = {
        "query0102": "55000101010002a60102d241",
        "trace_enable0901": "55000101020004a3090100012343",
        "fixed_diagnostic0156": "55000102020004a2015600007803",
        "density_query0302": "55000103010002a403025121",
        "trace_restore0901": "55000104020004a0090100021812",
    }
    # Independent standard nibble-table MODBUS check of actual linked frame bytes.
    table = (
        0,
        0xCC01,
        0xD801,
        0x1400,
        0xF001,
        0x3C00,
        0x2800,
        0xE401,
        0xA001,
        0x6C00,
        0x7800,
        0xB401,
        0x5000,
        0x9C01,
        0x8801,
        0x4400,
    )
    dram_bytes = b"".join(
        Path(s["path"]).read_bytes() for s in segments if not s["flags"] & 1
    )
    for name, encoded in fixed_frames.items():
        frame = bytes.fromhex(encoded)
        crc = 0xFFFF
        for byte in frame[:-2]:
            crc ^= byte
            for _ in range(2):
                crc = (crc >> 4) ^ table[crc & 15]
        if (
            sum(frame[:8]) & 255
            or crc != int.from_bytes(frame[-2:], "little")
            or dram_bytes.count(frame) != 1
        ):
            raise ValueError("linked fixed frame/header/CRC mismatch: " + name)
    undefined = subprocess.check_output([str(nm), "-u", str(elf)], text=True).strip()
    if undefined:
        raise ValueError("unresolved external symbol: " + undefined)
    disassembly = subprocess.check_output([str(objdump), "-d", str(elf)], text=True)
    (out / "bridge.dis").write_text(disassembly)
    symbols = subprocess.check_output([str(nm), "-n", str(elf)], text=True)
    (out / "bridge.symbols").write_text(symbols)
    if not segments or not any(
        s["address"] <= entry < s["address"] + s["size"] for s in segments
    ):
        raise ValueError("entry absent from load bytes")
    # No mapped-flash section and only named ROM delay function are linked.
    source_hashes = {
        p.name: sha(p.read_bytes())
        for p in (
            SOURCE / "bridge.c",
            SOURCE / "entry.S",
            SOURCE / "bridge.ld",
            SOURCE / "build.py",
        )
    }
    evidence_paths = [
        IDF / "components/heap/port/esp32/memory_layout.c",
        IDF / "components/esp_system/ld/esp32/memory.ld.in",
        IDF / "components/esp_rom/esp32/ld/esp32.rom.ld",
        IDF / "components/hal/esp32/include/hal/uart_ll.h",
        IDF / "components/soc/esp32/rtc_io_periph.c",
        IDF / "components/soc/esp32/register/soc/rtc_io_reg.h",
        IDF / "components/soc/esp32/register/soc/rtc_cntl_reg.h",
        IDF / "components/soc/esp32/register/soc/gpio_reg.h",
    ]
    receipt = {
        "mode": "OFFLINE_RAM_BRIDGE_BUILD_NO_UPLOAD",
        "entrypoint": entry,
        "elf_path": str(elf),
        "elf_sha256": sha(raw),
        "segments": segments,
        "source_sha256": source_hashes,
        "compiler": str(gcc),
        "compiler_version": subprocess.check_output(
            [str(gcc), "--version"], text=True
        ).splitlines()[0],
        "build_command": command,
        "undefined_symbols": [],
        "memory_bounds": {
            "iram": [0x40090000, 0x40092000],
            "dram_total_including_stack": [0x3FFB0000, 0x3FFB2000],
            "stack_bytes": 4096,
        },
        "source_bindings": [
            {"path": str(p), "sha256": sha(p.read_bytes())}
            for p in evidence_paths
            if p.exists()
        ],
        "protocol": {
            "banner": "FP2RAM1\n",
            "Q": "QUERYOK\n or ERR QUERY\n; exactly one query",
            "R": "RX <4hexlength> <8hexrawIRQ> <hexdata>\n",
            "W": "W + u16le length1..1029 + rawbytes; shared2000ms host idle-poll budget; WOK or ERR WRITE; failure latches onlyX; raw UART can write radar flash",
            "P": "RX <4hexlength> <8hexrawIRQ> <hexdata>\n; max256bytes/100polls, stopafter2idle polls once dataarrives",
            "B": "BOOT <4hexlength> <8hexrawIRQ> <hexdata>\n; one stock10ms reset,1024bytes/5000polls",
            "T": "TRACE <4hexlength> <8hexrawIRQ> <hexdata>\n then RESETOK\n or ERR RESET\n; fixed0901/0156/0302/0901, one cleanupreset",
            "X": "BYE\n then idle; host reset still required",
        },
        "fixed_frame_hex": fixed_frames,
        "no_device_access": True,
        "runtime_verified": False,
    }
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".tools/esp32-ram-xmodem-bridge"
    )
    parser.add_argument("--tool-bin", type=Path, default=DEFAULT_TOOLS)
    args = parser.parse_args()
    receipt = build(args.output, args.tool_bin)
    print(
        json.dumps(
            {
                "entrypoint": receipt["entrypoint"],
                "segments": receipt["segments"],
                "receipt": str(args.output / "receipt.json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
