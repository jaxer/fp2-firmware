#!/usr/bin/env python3
"""Validate TI MSTR/RPRC packages in the stock ESP32 mcu_ota partition.

Reports metadata and checks CRC32 trailers, CRC64 fields and every RPRC section.
Optional ARM ELFs are analysis
containers made from exact recorded section bytes, never executable tests.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib

from inspect_flash import inspect_flash
from verify_ti_crc64 import crc64_ti


def align(value, boundary=8):
    return (value + boundary - 1) & -boundary


def rprc(data, start, length):
    limit = start + length
    if length < 24 or limit > len(data):
        raise ValueError("invalid RPRC extent")
    magic, entry, reserved, count, version = struct.unpack_from("<5I", data, start)
    if magic != 0x43525052 or not 1 <= count <= 128:
        raise ValueError("invalid RPRC header")
    cursor, sections = start + 24, []
    for _ in range(count):
        if cursor + 24 > limit:
            raise ValueError("RPRC section header out of bounds")
        address, size, r0, r1, r2 = struct.unpack_from("<Q4I", data, cursor)
        content_start, content_end = cursor + 24, cursor + 24 + size
        if content_end > limit:
            raise ValueError("RPRC section content out of bounds")
        content = data[content_start:content_end]
        sections.append(
            {
                "header_offset_in_partition": cursor,
                "data_offset_in_partition": content_start,
                "load_address": address,
                "size": size,
                "reserved": [r0, r1, r2],
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
        cursor = align(content_end)
    if cursor != limit:
        raise ValueError(
            f"RPRC parsed end {cursor:#x} differs from declared end {limit:#x}"
        )
    return {
        "entrypoint": entry,
        "version_field": version,
        "reserved": reserved,
        "sections": sections,
    }


def mstr(data, start):
    if start + 24 > len(data):
        raise ValueError("truncated MSTR header")
    magic, count, device, crc_high, crc_low, size = struct.unpack_from(
        "<6I", data, start
    )
    if magic != 0x5254534D or not 1 <= count <= 8:
        raise ValueError("invalid MSTR header")
    header_size = 24 + count * 32 + 8
    if size < header_size or start + size + 4 > len(data):
        raise ValueError("invalid MSTR image extent")
    if data[start + header_size - 4 : start + header_size] != b"MEND":
        raise ValueError("missing MEND marker")
    # TI Image Creator Figure 2: the word before MEND is bank allocation,
    # with numeric bytes BSS | MSS TCMB | MSS TCMA | DSS/L3 (MSB first).
    shared_memory_allocation = struct.unpack_from("<I", data, start + header_size - 8)[
        0
    ]
    shared_memory_banks = {
        "BSS": (shared_memory_allocation >> 24) & 0xFF,
        "MSS_TCMB": (shared_memory_allocation >> 16) & 0xFF,
        "MSS_TCMA": (shared_memory_allocation >> 8) & 0xFF,
        "DSS_L3": shared_memory_allocation & 0xFF,
    }
    header = bytearray(data[start : start + header_size])
    header[12:20] = bytes(8)
    if crc64_ti(header) != (crc_high << 32) | crc_low:
        raise ValueError("MSTR header CRC64 mismatch")
    images, intervals = [], []
    for i in range(count):
        row = struct.unpack_from("<8I", data, start + 24 + 32 * i)
        present, core, offset, hi, lo, length, r0, r1 = row
        if offset < header_size or offset + length > size or offset % 8:
            raise ValueError("invalid MSTR sub-image bounds")
        intervals.append((offset, offset + length))
        parsed = rprc(data, start + offset, length)
        payload = data[start + offset : start + offset + length]
        if crc64_ti(payload) != (hi << 32) | lo:
            raise ValueError("MSTR sub-image CRC64 mismatch")
        images.append(
            {
                "present_field": present,
                "core_magic": f"0x{core:08x}",
                "offset_in_package": offset,
                "size": length,
                "crc64_field": f"{hi:08x}{lo:08x}",
                "crc64_verified": True,
                "reserved": [r0, r1],
                "sha256": hashlib.sha256(
                    data[start + offset : start + offset + length]
                ).hexdigest(),
                "rprc": parsed,
            }
        )
    for left, right in zip(sorted(intervals), sorted(intervals)[1:]):
        if left[1] > right[0]:
            raise ValueError("overlapping MSTR sub-images")
    computed = zlib.crc32(data[start : start + size])
    trailer = struct.unpack_from("<I", data, start + size)[0]
    if computed != trailer:
        raise ValueError("MSTR appended CRC32 mismatch")
    return {
        "offset_in_partition": start,
        "declared_size": size,
        "size_with_crc32": size + 4,
        "device_id": device,
        "header_size": header_size,
        "rprc_count": count,
        "shared_memory_allocation": shared_memory_allocation,
        "shared_memory_banks": shared_memory_banks,
        "header_crc64_field": f"{crc_high:08x}{crc_low:08x}",
        "header_crc64_verified": True,
        "appended_crc32": f"0x{trailer:08x}",
        "appended_crc32_valid": True,
        "sha256": hashlib.sha256(data[start : start + size + 4]).hexdigest(),
        "images": images,
    }


def arm_elf(data, image):
    """Build ELF32 mappings; RWX flags are analysis assumptions, not observations."""
    sections = image["rprc"]["sections"]
    if any(s["load_address"] > 0xFFFFFFFF for s in sections):
        raise ValueError("ARM32 section address exceeds 32 bits")
    count = len(sections)
    blob = bytearray(52 + count * 32)
    mappings = []
    for section in sections:
        blob.extend(b"\0" * (align(len(blob), 16) - len(blob)))
        offset = len(blob)
        source = section["data_offset_in_partition"]
        blob.extend(data[source : source + section["size"]])
        mappings.append((offset, section["load_address"], section["size"]))
    names = bytearray(b"\0")
    name_offsets = []
    for i in range(count):
        name_offsets.append(len(names))
        names.extend(f".rprc{i}\0".encode())
    str_name = len(names)
    names.extend(b".shstrtab\0")
    str_offset = len(blob)
    blob.extend(names)
    blob.extend(b"\0" * (align(len(blob), 4) - len(blob)))
    shoff = len(blob)
    blob.extend(b"\0" * 40)
    for i, (offset, address, size) in enumerate(mappings):
        blob.extend(
            struct.pack(
                "<10I", name_offsets[i], 1, 7, address, offset, size, 0, 0, 4, 0
            )
        )
        struct.pack_into(
            "<8I", blob, 52 + i * 32, 1, offset, address, address, size, size, 7, 4
        )
    blob.extend(
        struct.pack("<10I", str_name, 3, 0, 0, str_offset, len(names), 0, 0, 1, 0)
    )
    ident = b"\x7fELF\x01\x01\x01" + b"\0" * 9
    struct.pack_into(
        "<16sHHIIIIIHHHHHH",
        blob,
        0,
        ident,
        2,
        40,
        1,
        image["rprc"]["entrypoint"],
        52,
        shoff,
        0x05000000,
        52,
        32,
        count,
        40,
        count + 2,
        count + 1,
    )
    return bytes(blob)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("flash", type=Path)
    parser.add_argument("--export-arm-dir", type=Path)
    args = parser.parse_args()
    try:
        flash = inspect_flash(args.flash)
        partition = next(p for p in flash["partitions"] if p["label"] == "mcu_ota")
        raw = args.flash.read_bytes()
        data = raw[partition["offset"] : partition["offset"] + partition["size"]]
        accepted, rejected, exports = [], [], []
        position = 0
        while (position := data.find(b"MSTR", position)) >= 0:
            try:
                package = mstr(data, position)
            except ValueError as error:
                # A signature embedded in code is not itself an image header.
                rejected.append({"offset": position, "reason": str(error)})
                position += 4
                continue
            accepted.append(package)
            if args.export_arm_dir:
                args.export_arm_dir.mkdir(parents=True, exist_ok=True)
                for image in package["images"]:
                    if image["core_magic"] != "0x35510000":
                        continue
                    target = args.export_arm_dir / f"mstr_{position:06x}_mss.elf"
                    if target.exists():
                        raise ValueError(f"refusing to overwrite {target}")
                    elf = arm_elf(data, image)
                    target.write_bytes(elf)
                    exports.append(
                        {
                            "path": str(target.resolve()),
                            "sha256": hashlib.sha256(elf).hexdigest(),
                            "package_offset": position,
                            "source_rprc_sha256": image["sha256"],
                        }
                    )
            position += 4
        report = {
            "source_sha256": flash["source_sha256"],
            "partition": partition,
            "validated_packages": accepted,
            "rejected_magic_candidates": rejected,
            "arm_analysis_exports": exports,
            "limitations": [
                "CRC32 and structural checks establish integrity, not cryptographic authenticity.",
                "CRC64 algorithm/coverage is verified against this artifact and stock code; it does not authenticate a publisher.",
                "Staged images are not evidence of which firmware is installed in radar QSPI.",
                "ARM ELF permissions and section names are analysis assumptions; bytes, load addresses and entrypoint come from RPRC.",
                "Mode selection, flash destinations, anti-rollback and power-failure recovery require code and runtime evidence.",
            ],
        }
        if not accepted:
            raise ValueError("no structurally and CRC32 valid TI packages found")
    except (OSError, ValueError, StopIteration, struct.error) as error:
        print(f"inspection failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
