#!/usr/bin/env python3
"""Build an offline code blob only; never accesses devices or constructs uploads."""

import os
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).resolve().parent
OUT = ROOT / ".tools/radar-export-wrapper"
PREFIX = os.environ.get("ARM_PREFIX", "arm-none-eabi-")
EXTERNAL_CALLS = {"sfdp": 0x2376D, "jedec": 0x246B9, "serialize": 0x18FD9}


def run(*args):
    return subprocess.check_output(args, text=True)


def build(out=OUT):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    elf = out / "export.elf"
    obj = out / "export.o"
    # A named object avoids random compiler temporary paths in the map/ELF.
    run(
        PREFIX + "gcc",
        "-mcpu=cortex-r4",
        "-mthumb",
        "-c",
        str(SOURCE / "export.S"),
        "-o",
        str(obj),
    )
    run(
        PREFIX + "gcc",
        "-mcpu=cortex-r4",
        "-mthumb",
        "-nostdlib",
        "-Wl,--build-id=none",
        "-Wl,-T," + str(SOURCE / "export.ld"),
        "-Wl,-Map," + str(out / "export.map"),
        str(obj),
        "-o",
        str(elf),
    )
    run(
        PREFIX + "objcopy",
        "-O",
        "binary",
        "--only-section=.text",
        str(elf),
        str(out / "export.bin"),
    )
    (out / "export.dis").write_text(run(PREFIX + "objdump", "-d", str(elf)))
    symbols = {}
    for line in run(PREFIX + "nm", "-n", str(elf)).splitlines():
        fields = line.split()
        if len(fields) == 3:
            symbols[fields[2]] = int(fields[0], 16)
    # The actual linkedELF carries the4-byte .hook andseparateTCMA .text.
    run(
        PREFIX + "objcopy",
        "-O",
        "binary",
        "--only-section=.hook",
        str(elf),
        str(out / "op1-hook.bin"),
    )
    hook = (out / "op1-hook.bin").read_bytes()
    if len(hook) != 4:
        raise ValueError("op1 patch must be exactlyone ThumbB.W instruction")
    raw = (out / "export.bin").read_bytes()
    if not raw or len(raw) > 4096:
        raise ValueError("code exceeds fixed placement window")
    manifest = {
        "status": "OFFLINE_NOT_APPROVED_FOR_UPLOAD",
        "load_address": 0x38000,
        "end_exclusive": 0x38000 + len(raw),
        "init_entry": symbols["export_init"] | 1,
        "wrapper_entry": symbols["export_handler"] | 1,
        "raw_size": len(raw),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "op1_pointer_address": 0x08028B00,
        "original_op1_entry": 0xFFE5,
        "original_post_cinit": 0x24291,
        "stack_frame_bytes": 192,
        "hook_strategy": "direct_op1_entry_branch_no_cinit_patch",
        "op1_hook_address": 0xFFE4,
        "op1_hook_expected_hex": "08b50a78",
        "op1_hook_replacement_hex": hook.hex(),
        "trampoline_entry": symbols["export_original_op1"] | 1,
        "trampoline_resume": 0xFFE9,
        "external_calls": EXTERNAL_CALLS,
        "symbols": symbols,
        "protocol_version": 3,
        "request_version": 1,
        "max_data_bytes": 128,
        "max_response_body_bytes": 136,
        "scratch_address": symbols["export_scratch"],
        "scratch_size": 32,
        "code_end_exclusive": symbols["export_code_end"],
        "read_windows": [
            [0, 0x40000],
            [0x08000000, 0x08030000],
            [0xC0000000, 0xC0800000],
        ],
        "write_windows": [[0, 0x40000], [0x08000000, 0x08030000]],
        "write_alignment": 8,
        "max_write_bytes": 32,
        "write_exclusions": "monitor section except owned scratch; active handler frame",
        "source_sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [SOURCE / "export.S", SOURCE / "export.ld", SOURCE / "build.py"]
        },
        "output_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [elf, out / "export.bin", out / "export.dis", out / "export.map"]
        },
        "compiler": run(PREFIX + "gcc", "--version").splitlines()[0],
        "gates": [
            "TCMA lifetime and runtime writers",
            "QSPI serialization and mapped mode restoration",
            "complete transitive stack headroom",
            "installed identity and loader acceptance",
            "installation and recovery; no device execution approved by this artifact",
        ],
        "status_semantics": "v3 M mapped reads/W aligned RAM stores/S SFDP/J JEDEC; status0 means bounded copy/helper returned, not hardware-success proof; legacy R status6; host bounds flash with actual SFDP",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    result = build()
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "status",
                    "raw_size",
                    "raw_sha256",
                    "init_entry",
                    "wrapper_entry",
                )
            }
        )
    )
