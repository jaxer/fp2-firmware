#!/usr/bin/env python3
"""Verify the recorded FP2 TI MSTR/RPRC CRC64 fields, without hardware access.

crc64_ti(data) is the stable pure entry point: MSB-first poly 0x1b, initial 0,
no reflection or final XOR, bytes in file order. It does not add padding.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys


MASK64 = (1 << 64) - 1
POLYNOMIAL = 0x1B


def _table() -> tuple[int, ...]:
    entries = []
    for byte in range(256):
        value = byte << 56
        for _ in range(8):
            value = ((value << 1) ^ (POLYNOMIAL if value >> 63 else 0)) & MASK64
        entries.append(value)
    return tuple(entries)


TABLE = _table()


def crc64_ti(data: bytes | bytearray | memoryview) -> int:
    """Return the natural numeric CRC64, with no implicit input padding."""
    value = 0
    for byte in data:
        value = ((value << 8) & MASK64) ^ TABLE[(value >> 56) ^ byte]
    return value


def read_crc64_words(data: bytes, offset: int) -> int:
    """TI package fields store the high 32-bit word first, each word LE."""
    high, low = struct.unpack_from("<II", data, offset)
    return (high << 32) | low


def verify(flash_path: Path) -> dict:
    # Imported only by the CLI: the pure CRC entry point has no parser cycle.
    from inspect_flash import inspect_flash
    from inspect_radar_package import mstr

    flash = inspect_flash(flash_path)
    partition = next(p for p in flash["partitions"] if p["label"] == "mcu_ota")
    raw = flash_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != flash["source_sha256"]:
        raise ValueError("source changed during inspection")
    data = raw[partition["offset"] : partition["offset"] + partition["size"]]
    checks, rejected, packages = [], [], []
    position = 0
    while (position := data.find(b"MSTR", position)) >= 0:
        try:
            package = mstr(data, position)
        except ValueError as exc:
            rejected.append({"offset_in_partition": position, "reason": str(exc)})
            position += 4
            continue
        packages.append(position)
        header = bytearray(data[position : position + package["header_size"]])
        header[12:20] = bytes(8)
        computed = crc64_ti(header)
        expected = read_crc64_words(data, position + 12)
        checks.append(
            {
                "kind": "MSTR_header",
                "package_offset_in_partition": position,
                "source_offset_in_flash": partition["offset"] + position,
                "length": len(header),
                "zeroed_offsets_in_header": [12, 20],
                "checksum_input_sha256": hashlib.sha256(header).hexdigest(),
                "expected": f"{expected:016x}",
                "computed": f"{computed:016x}",
                "matches": computed == expected,
            }
        )
        for ordinal, image in enumerate(package["images"]):
            start = position + image["offset_in_package"]
            payload = data[start : start + image["size"]]
            expected = read_crc64_words(data, position + 24 + ordinal * 32 + 12)
            computed = crc64_ti(payload)
            checks.append(
                {
                    "kind": "RPRC",
                    "package_offset_in_partition": position,
                    "image_ordinal": ordinal,
                    "core_magic": image["core_magic"],
                    "source_offset_in_flash": partition["offset"] + start,
                    "length": len(payload),
                    "checksum_input_sha256": hashlib.sha256(payload).hexdigest(),
                    "expected": f"{expected:016x}",
                    "computed": f"{computed:016x}",
                    "matches": computed == expected,
                }
            )
        position += 4
    return {
        "schema_version": 1,
        "source": {
            "path": str(flash_path.resolve()),
            "sha256": flash["source_sha256"],
            "size": len(raw),
            "partition": partition,
        },
        "algorithm": {
            "width": 64,
            "polynomial": "0x000000000000001b",
            "initial": "0x0000000000000000",
            "xorout": "0x0000000000000000",
            "reflect_input": False,
            "reflect_output": False,
            "input_order": "ascending file byte order, MSB-first within each byte",
            "field_storage": "high uint32 little-endian, then low uint32 little-endian",
            "padding": "none added; all inspected extents already multiples of 8",
            "header_coverage": "complete MSTR through MEND inclusive, CRC bytes 12..19 zeroed",
            "rprc_coverage": "entire declared RPRC including its headers, data and alignment bytes",
        },
        "vendor_corroboration": {
            "document": "TI IWR14xx/16xx/18xx/68xx/64xx Technical Reference Manual, SWRU520E",
            "url": "https://www.ti.com/lit/ug/swru520e/swru520e.pdf",
            "retrieved_pdf_sha256": "0d2c58845758afe2d4e5bdd6db979cd34548d23e307b3a008a7f94e42a19d83a",
            "sections": [
                "29.3.2.3, pp.3440-3441: polynomial, MSB-first LFSR and zero-reset signature",
                "29.3.4.1, pp.3455-3456: CRC64 selection and bit/byte swap register fields",
            ],
            "scope": "Hardware polynomial and register behavior; exact file field layout and coverage are established by the inspected stock SBL and all recorded checks.",
        },
        "package_count": len(packages),
        "header_check_count": sum(x["kind"] == "MSTR_header" for x in checks),
        "rprc_check_count": sum(x["kind"] == "RPRC" for x in checks),
        "check_count": len(checks),
        "matching_count": sum(x["matches"] for x in checks),
        "unique_checksum_inputs": len({x["checksum_input_sha256"] for x in checks}),
        "all_verified": bool(checks) and all(x["matches"] for x in checks),
        "checks": checks,
        "rejected_magic_candidates": rejected,
        "limitations": [
            "Exact recorded artifact verification only; no firmware or device is executed.",
            "CRC integrity is not cryptographic authenticity, compatibility or rollback assurance.",
            "Algorithm and field layout are derived from recorded fields and stock SBL instructions; vendor hardware documentation separately corroborates the polynomial.",
            "Identical embedded RPRC payloads recur; check_count is not a count of independent unique test vectors.",
            "No claim is made about hardware behavior for unaligned data or another device's CRC configuration.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("flash", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = verify(args.flash)
    except (OSError, ValueError, StopIteration, struct.error) as exc:
        print(f"verification failed: {exc}", file=sys.stderr)
        return 1
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    else:
        print(encoded, end="")
    return 0 if report["all_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
