#!/usr/bin/env python3
"""Inspect the retained radar bundle envelope offline; no device access."""

import hashlib
import json
from pathlib import Path
import struct
import zlib

MARKER_OFFSET = 0x250000
MARKER = b"www.aqara.com"
CRC_OFFSET = MARKER_OFFSET + len(MARKER)
BUNDLE_SIZE = CRC_OFFSET + 4


def inspect(data):
    if len(data) < BUNDLE_SIZE or data[MARKER_OFFSET:CRC_OFFSET] != MARKER:
        raise ValueError("missing complete retained bundle envelope")
    stored = struct.unpack_from("<I", data, CRC_OFFSET)[0]
    computed = zlib.crc32(data[:CRC_OFFSET])
    if stored != computed:
        raise ValueError("bundle CRC32 mismatch")
    return {
        "size": BUNDLE_SIZE,
        "marker_offset": MARKER_OFFSET,
        "marker_hex": MARKER.hex(),
        "crc_offset": CRC_OFFSET,
        "crc32": f"{stored:08x}",
        "sha256": hashlib.sha256(data[:BUNDLE_SIZE]).hexdigest(),
        "crc_valid": True,
        "limitation": "Retained-source envelope only; no device acceptance or write-policy proof.",
    }


def envelope_candidate(original, overlay):
    """Recompute only the outer CRC of an independently prepared offline overlay."""
    inspect(original)
    if len(overlay) != len(original) or overlay[MARKER_OFFSET:CRC_OFFSET] != MARKER:
        raise ValueError("overlay changed envelope bounds or marker")
    if overlay[BUNDLE_SIZE:] != original[BUNDLE_SIZE:]:
        raise ValueError("overlay changed bytes outside retained bundle")
    result = bytearray(overlay[:BUNDLE_SIZE])
    struct.pack_into("<I", result, CRC_OFFSET, zlib.crc32(result[:CRC_OFFSET]))
    inspect(result)
    return bytes(result)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("backup", type=Path)
    a = p.parse_args()
    from radar_layout import (
        validate_source,
        PARTITION_OFFSET,
        PARTITION_SIZE,
    )

    source = a.backup.read_bytes()
    validate_source(source)
    print(
        json.dumps(
            inspect(source[PARTITION_OFFSET : PARTITION_OFFSET + PARTITION_SIZE]),
            indent=2,
        )
    )
