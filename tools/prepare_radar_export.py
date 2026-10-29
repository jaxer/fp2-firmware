#!/usr/bin/env python3
"""Build an OFFLINE ONLY radar package; no device or upload support."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib

from inspect_radar_package import align, mstr
from radar_layout import (
    validate_source,
    PARTITION_OFFSET,
    PARTITION_SIZE,
    PACKAGE_OFFSETS,
    crc_words,
)

ROOT = Path(__file__).resolve().parents[1]
LOAD = 0x38000
LIMIT = 0x39000
HOOK = 0xFFE4
ORIGINAL_HOOK = bytes.fromhex("08b50a78")
STATUS = "OFFLINE_NOT_READY_FOR_UPLOAD"
SOURCES = (
    "firmware/radar_export/export.S",
    "firmware/radar_export/export.ld",
    "firmware/radar_export/build.py",
)
OUTPUTS = ("export.elf", "export.bin", "export.dis", "export.map")
VERSION_PATCHES = (
    (0x2652E, bytes.fromhex("4a7e"), bytes.fromhex("6622")),
    (0x26534, bytes.fromhex("497e"), bytes.fromhex("6621")),
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_wrapper(raw: bytes, manifest: dict) -> None:
    if manifest.get("status") != "OFFLINE_NOT_APPROVED_FOR_UPLOAD":
        raise ValueError("unexpected wrapper status")
    expected = {
        "load_address": LOAD,
        "end_exclusive": LOAD + len(raw),
        "raw_size": len(raw),
        "raw_sha256": sha(raw),
        "original_post_cinit": 0x24291,
        "op1_pointer_address": 0x08028B00,
        "original_op1_entry": 0xFFE5,
        "op1_hook_address": HOOK,
        "op1_hook_expected_hex": ORIGINAL_HOOK.hex(),
        "hook_strategy": "direct_op1_entry_branch_no_cinit_patch",
        "stack_frame_bytes": 192,
        "protocol_version": 3,
        "max_data_bytes": 128,
        "max_response_body_bytes": 136,
        "external_calls": {"sfdp": 0x2376D, "jedec": 0x246B9, "serialize": 0x18FD9},
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"wrapper manifest mismatch: {key}")
    if not raw or len(raw) > LIMIT - LOAD:
        raise ValueError("wrapper exceeds fixed TCMA capacity")
    if len(bytes.fromhex(manifest.get("op1_hook_replacement_hex", ""))) != 4:
        raise ValueError("invalid op1 hook replacement")
    scratch = manifest.get("scratch_address", 0)
    if (
        manifest.get("scratch_size") != 32
        or manifest.get("code_end_exclusive") != scratch
        or scratch % 8
        or not LOAD < scratch < scratch + 32 <= LOAD + len(raw)
    ):
        raise ValueError("invalid owned scratch bounds")
    for key in ("init_entry", "wrapper_entry", "trampoline_entry"):
        entry = manifest.get(key, 0)
        if (
            not isinstance(entry, int)
            or not entry & 1
            or not LOAD <= (entry & ~1) < LOAD + len(raw)
        ):
            raise ValueError(f"invalid Thumb {key}")


def load_wrapper(directory: Path, expected_raw: str, expected_manifest: str):
    """Require explicit hash pins and unchanged declared sources/build outputs."""
    manifest_bytes = (directory / "manifest.json").read_bytes()
    raw = (directory / "export.bin").read_bytes()
    if sha(manifest_bytes) != expected_manifest or sha(raw) != expected_raw:
        raise ValueError("wrapper/manifest differs from explicitly pinned hashes")
    manifest = json.loads(manifest_bytes)
    if set(manifest.get("source_sha256", {})) != set(SOURCES):
        raise ValueError("missing or unexpected wrapper sources")
    if set(manifest.get("output_sha256", {})) != set(OUTPUTS):
        raise ValueError("missing or unexpected wrapper outputs")
    for name in SOURCES:
        if sha((ROOT / name).read_bytes()) != manifest["source_sha256"][name]:
            raise ValueError(f"wrapper source changed: {name}")
    for name in OUTPUTS:
        if sha((directory / name).read_bytes()) != manifest["output_sha256"][name]:
            raise ValueError(f"wrapper output changed: {name}")
    validate_wrapper(raw, manifest)
    validate_elf((directory / "export.elf").read_bytes(), raw, manifest)
    return raw, manifest, sha(manifest_bytes)


def validate_elf(elf: bytes, raw: bytes, manifest: dict) -> None:
    if len(elf) < 52 or elf[:7] != b"\x7fELF\x01\x01\x01":
        raise ValueError("requires ELF32 little-endian wrapper")
    fields = struct.unpack_from("<16sHHIIIIIHHHHHH", elf)
    if fields[2] != 40 or fields[4] not in (
        manifest["init_entry"],
        manifest["init_entry"] & ~1,
    ):
        raise ValueError("unexpected ARM ELF entry")
    shoff, shsize, shnum = fields[6], fields[11], fields[12]
    if shsize != 40 or shoff + shsize * shnum > len(elf):
        raise ValueError("invalid ELF section table")
    intervals = []
    hook_found = False
    for i in range(shnum):
        _, kind, flags, address, offset, size, *_ = struct.unpack_from(
            "<10I", elf, shoff + 40 * i
        )
        if not flags & 2 or not size:
            continue
        if address == HOOK and size == 4 and kind != 8:
            if (
                hook_found
                or elf[offset : offset + size].hex()
                != manifest["op1_hook_replacement_hex"]
            ):
                raise ValueError("ELF hook bytes disagree")
            hook_found = True
            continue
        if kind == 8 or not LOAD <= address < address + size <= LOAD + len(raw):
            raise ValueError("wrapper allocated section outside raw image or has BSS")
        if (
            offset + size > len(elf)
            or elf[offset : offset + size]
            != raw[address - LOAD : address - LOAD + size]
        ):
            raise ValueError("ELF/raw bytes disagree")
        intervals.append((address, address + size))
    if (
        not hook_found
        or not intervals
        or any(a[1] > b[0] for a, b in zip(sorted(intervals), sorted(intervals)[1:]))
    ):
        raise ValueError("missing or overlapping wrapper sections")


def prepare(source: bytes, raw: bytes, manifest: dict) -> tuple[bytes, bytes, dict]:
    """Return immutable-source partition overlay, standalone package and receipt."""
    validate_source(source)
    validate_wrapper(raw, manifest)
    original = source[PARTITION_OFFSET : PARTITION_OFFSET + PARTITION_SIZE]
    if len(original) != PARTITION_SIZE:
        raise ValueError("incomplete partition")
    before = [mstr(original, p) for p in PACKAGE_OFFSETS]
    main = before[1]
    if main["shared_memory_allocation"] != 6 or main["rprc_count"] != 3:
        raise ValueError("unexpected main allocation or image count")
    mss = main["images"][0]
    if mss["core_magic"] != "0x35510000":
        raise ValueError("unexpected first core")
    matches = [
        s
        for s in mss["rprc"]["sections"]
        if s["load_address"] <= HOOK and HOOK + 4 <= s["load_address"] + s["size"]
    ]
    if len(matches) != 1:
        raise ValueError("op1 entry is not uniquely mapped")
    for s in mss["rprc"]["sections"]:
        if s["load_address"] < LIMIT and LOAD < s["load_address"] + s["size"]:
            raise ValueError("wrapper overlaps original MSS section")
    literal = matches[0]["data_offset_in_partition"] + HOOK - matches[0]["load_address"]
    if original[literal : literal + 4] != ORIGINAL_HOOK:
        raise ValueError("unexpected original op1 entry")
    start = PACKAGE_OFFSETS[1]
    rstart = start + mss["offset_in_package"]
    rend = rstart + mss["size"]
    if any(
        i["offset_in_package"] < mss["offset_in_package"] + mss["size"]
        for i in main["images"][1:]
    ):
        raise ValueError("unexpected member ordering")
    # Preserve the original inter-member padding by making RPRC growth a
    # multiple of64. The SBL rounds every member length to64, not merely8.
    section_size = ((24 + len(raw) + 63) & ~63) - 24
    if section_size > LIMIT - LOAD:
        raise ValueError("loader-aligned section exceeds placement window")
    new_section = (
        struct.pack("<Q4I", LOAD, section_size, 0, 0, 0)
        + raw
        + bytes(section_size - len(raw))
    )
    new_section += bytes(align(len(new_section)) - len(new_section))
    growth = len(new_section)
    old_end = start + main["size_with_crc32"]
    new_end = old_end + growth
    # The exact retained staging bundle pads this package gap with zeros, not FF.
    if new_end > PACKAGE_OFFSETS[2] or original[old_end : PACKAGE_OFFSETS[2]] != bytes(
        PACKAGE_OFFSETS[2] - old_end
    ):
        raise ValueError("new main package cannot fit verified zero-padding gap")
    package = bytearray(original[start:rend] + new_section + original[rend:old_end])
    hook_bytes = bytes.fromhex(manifest["op1_hook_replacement_hex"])
    package[literal - start : literal - start + 4] = hook_bytes
    version_patches = []
    for address, old, new in VERSION_PATCHES:
        owner = next(
            s
            for s in mss["rprc"]["sections"]
            if s["load_address"]
            <= address
            < address + 2
            <= s["load_address"] + s["size"]
        )
        offset = owner["data_offset_in_partition"] + address - owner["load_address"]
        if original[offset : offset + 2] != old:
            raise ValueError("unexpected version getter bytes")
        package[offset - start : offset - start + 2] = new
        version_patches.append(
            {
                "address": address,
                "partition_offset": offset,
                "before_hex": old.hex(),
                "after_hex": new.hex(),
            }
        )
    struct.pack_into(
        "<I", package, mss["offset_in_package"] + 12, len(mss["rprc"]["sections"]) + 1
    )
    struct.pack_into("<I", package, 20, main["declared_size"] + growth)
    for ordinal, image in enumerate(main["images"]):
        row = 24 + 32 * ordinal
        offset = image["offset_in_package"] + (growth if ordinal else 0)
        length = image["size"] + (growth if not ordinal else 0)
        struct.pack_into("<I", package, row + 8, offset)
        package[row + 12 : row + 20] = crc_words(package[offset : offset + length])
        struct.pack_into("<I", package, row + 20, length)
    header = bytearray(package[: main["header_size"]])
    header[12:20] = bytes(8)
    package[12:20] = crc_words(header)
    struct.pack_into("<I", package, len(package) - 4, zlib.crc32(package[:-4]))
    overlay = bytearray(original)
    overlay[start:new_end] = package
    after = [mstr(overlay, p) for p in PACKAGE_OFFSETS]
    for container in after:
        for image in container["images"]:
            if image["offset_in_package"] % 64:
                raise ValueError("member is not SBL64-aligned")
        for a, b in zip(container["images"], container["images"][1:]):
            if b["offset_in_package"] != a["offset_in_package"] + (
                (a["size"] + 63) & ~63
            ):
                raise ValueError("member gap differs from SBL64-byte padding")
    for ordinal, (a, b) in enumerate(zip(before, after)):
        if ordinal != 1 and a["sha256"] != b["sha256"]:
            raise ValueError("other package changed")
    for a, b in zip(main["images"][1:], after[1]["images"][1:]):
        if a["sha256"] != b["sha256"]:
            raise ValueError("BSS/DSS payload changed")
    new_mss = after[1]["images"][0]
    if new_mss["rprc"]["entrypoint"] != mss["rprc"]["entrypoint"]:
        raise ValueError("original entry changed")
    for a, b in zip(mss["rprc"]["sections"], new_mss["rprc"]["sections"]):
        old = original[
            a["data_offset_in_partition"] : a["data_offset_in_partition"] + a["size"]
        ]
        new = bytes(
            overlay[
                b["data_offset_in_partition"] : b["data_offset_in_partition"]
                + b["size"]
            ]
        )
        if a is matches[0]:
            patched = bytearray(old)
            off = HOOK - a["load_address"]
            patched[off : off + 4] = hook_bytes
            old = bytes(patched)
        patched = bytearray(old)
        for address, _, replacement in VERSION_PATCHES:
            if (
                a["load_address"]
                <= address
                < address + 2
                <= a["load_address"] + a["size"]
            ):
                off = address - a["load_address"]
                patched[off : off + 2] = replacement
        old = bytes(patched)
        if (
            old != new
            or a["load_address"] != b["load_address"]
            or a["size"] != b["size"]
        ):
            raise ValueError("original MSS section changed beyond literal")
    changed = [i for i, (a, b) in enumerate(zip(original, overlay)) if a != b]
    receipt = {
        "status": STATUS,
        "source_sha256": sha(source),
        "source_partition_sha256": sha(original),
        "wrapper_sha256": sha(raw),
        "partition_overlay_sha256": sha(overlay),
        "main_MSTR_sha256": sha(package),
        "partition_size": len(overlay),
        "main_MSTR_size": len(package),
        "growth": growth,
        "loader_member_alignment": 64,
        "section_payload_padding": section_size - len(raw),
        "version_marker": 102,
        "version_marker_patches": version_patches,
        "hook": {
            "address": hex(HOOK),
            "partition_offset": hex(literal),
            "before_hex": ORIGINAL_HOOK.hex(),
            "after_hex": hook_bytes.hex(),
            "source_section_load_address": hex(matches[0]["load_address"]),
            "source_section_size": matches[0]["size"],
            "source_section_data_offset": hex(matches[0]["data_offset_in_partition"]),
            "source_section_sha256": matches[0]["sha256"],
            "seam": "direct op1 entry; trampoline replays PUSH{r3,lr};LDRBr2,[r1] then returns toffe8",
        },
        "new_section": new_mss["rprc"]["sections"][-1],
        "changed_byte_count": len(changed),
        "changed_partition_interval": [start, new_end],
        "consumed_source_padding_bytes": growth,
        "before_packages": before,
        "after_packages": after,
        "MSTR_count": len(after),
        "RPRC_count": sum(p["rprc_count"] for p in after),
        "original_MSS_sections_preserved_except_declared_patches": True,
        "all_CRC64_CRC32_and_section_bounds_verified": True,
        "limitations": [
            "No upload file or device support is provided.",
            "Installed image identity, concurrency, acceptance, flash write scope and recovery remain unproved.",
            "Checksum validity is not authorization or device acceptance.",
        ],
    }
    return bytes(overlay), bytes(package), receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--wrapper-dir", type=Path, default=ROOT / ".tools/radar-export-wrapper"
    )
    parser.add_argument("--expected-wrapper-sha256", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    raw, manifest, manifest_sha = load_wrapper(
        args.wrapper_dir, args.expected_wrapper_sha256, args.expected_manifest_sha256
    )
    overlay, package, receipt = prepare(args.source.read_bytes(), raw, manifest)
    receipt["wrapper_manifest_sha256"] = manifest_sha
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for name, data in [
        ("partition-overlay-NOT-UPLOAD.bin", overlay),
        ("main-MSTR-OFFLINE-ONLY.bin", package),
    ]:
        (args.output_dir / name).write_bytes(data)
    (args.output_dir / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    (args.output_dir / "before-manifest.json").write_text(
        json.dumps(receipt["before_packages"], indent=2) + "\n"
    )
    (args.output_dir / "after-manifest.json").write_text(
        json.dumps(receipt["after_packages"], indent=2) + "\n"
    )
    summary = {
        key: receipt[key]
        for key in (
            "status",
            "hook",
            "growth",
            "new_section",
            "changed_byte_count",
            "original_MSS_sections_preserved_except_declared_patches",
            "all_CRC64_CRC32_and_section_bounds_verified",
            "limitations",
        )
    }
    summary["member_offsets"] = [
        {
            "core": a["core_magic"],
            "before": a["offset_in_package"],
            "after": b["offset_in_package"],
            "before_size": a["size"],
            "after_size": b["size"],
        }
        for a, b in zip(
            receipt["before_packages"][1]["images"],
            receipt["after_packages"][1]["images"],
        )
    ]
    (args.output_dir / "diff-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                k: receipt[k]
                for k in (
                    "status",
                    "growth",
                    "changed_byte_count",
                    "MSTR_count",
                    "RPRC_count",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
