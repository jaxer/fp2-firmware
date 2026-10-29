#!/usr/bin/env python3
"""Inspect an ESP32 full-flash backup offline without exposing NVS values.

Only artifact identity, partition metadata, compiled image metadata, hashes,
and selected compiled radar identifiers are emitted. No device is opened.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys


def cstring(data):
    return bytes(data).split(b"\0", 1)[0].decode("utf-8", errors="replace")


def attribute_table_candidates(data, segments):
    """Recognize this stock build's 32-byte table shape, keeping roles inferred.

    The signature is four initial IDs separated by 32 bytes in initialized RAM.
    Type 7 and zero IDs occur in reserved/application-only entries; they are not
    evidence of a seventh on-wire value encoding. Function roles and control
    bytes require separate instruction-level verification.
    """
    candidates = []
    for segment in segments:
        if not 0x3FFB0000 <= segment["address"] < 0x40000000:
            continue
        start, size = segment["file_offset"], segment["size"]
        for position in range(start, start + size - 128, 4):
            if [
                struct.unpack_from("<H", data, position + i * 32)[0] for i in range(4)
            ] != [0x101, 0x102, 0x103, 0x104]:
                continue
            rows = []
            cursor = position
            while cursor + 32 <= start + size:
                words = struct.unpack_from("<8I", data, cursor)
                attr, kind = words[0] & 0xFFFF, words[0] >> 16
                if kind > 7 or (attr and not 0x101 <= attr <= 0x2FF):
                    break
                if any(
                    pointer and not 0x40080000 <= pointer < 0x40200000
                    for pointer in words[2:4]
                ):
                    break
                hint = None
                for mapped in segments:
                    if (
                        mapped["address"]
                        <= words[1]
                        < mapped["address"] + mapped["size"]
                    ):
                        source = mapped["file_offset"] + words[1] - mapped["address"]
                        value = cstring(data[source : source + 96])
                        if re.fullmatch(r"[0-9]+(?:\.[0-9]+){2}", value):
                            hint = value
                rows.append(
                    {
                        "file_offset": cursor,
                        "attribute_id": attr,
                        "type_field": kind,
                        "property_identifier_hint": hint,
                        "handler_a": words[2],
                        "handler_b": words[3],
                        "raw_control_words": list(words[4:]),
                    }
                )
                cursor += 32
            candidates.append(
                {
                    "confidence": "structural_candidate_requires_dispatch_code_verification",
                    "file_offset": position,
                    "mapped_address": segment["address"] + position - start,
                    "record_size": 32,
                    "record_count": len(rows),
                    "nonzero_id_count": len(
                        {row["attribute_id"] for row in rows if row["attribute_id"]}
                    ),
                    "typed_records_count": sum(row["type_field"] < 7 for row in rows),
                    "rows": rows,
                }
            )
    return candidates


def inspect_image(data, offset, size):
    image = memoryview(data)[offset : offset + size]
    if len(image) < 24 or image[0] != 0xE9:
        raise ValueError(f"no ESP image at {offset:#x}")
    count = image[1]
    if not 1 <= count <= 16:
        raise ValueError("invalid ESP image segment count")
    position, checksum, segments = 24, 0xEF, []
    for _ in range(count):
        if position + 8 > len(image):
            raise ValueError("truncated image segment header")
        address, length = struct.unpack_from("<II", image, position)
        start = position + 8
        end = start + length
        if end > len(image):
            raise ValueError("image segment extends beyond partition")
        for byte in image[start:end]:
            checksum ^= byte
        segments.append(
            {"file_offset": offset + start, "address": address, "size": length}
        )
        position = end
    checksum_position = position | 15
    if checksum_position >= len(image):
        raise ValueError("missing ESP image checksum")
    checksum_valid = image[checksum_position] == checksum
    append_digest = bool(image[23])
    end = checksum_position + 1
    digest_valid = None
    if append_digest:
        if end + 32 > len(image):
            raise ValueError("missing appended ESP image SHA-256")
        digest_valid = hashlib.sha256(image[:end]).digest() == image[end : end + 32]
        end += 32
    result = {
        "offset": offset,
        "image_size": end,
        "entrypoint": struct.unpack_from("<I", image, 4)[0],
        "chip_id": struct.unpack_from("<H", image, 12)[0],
        "segments": segments,
        "checksum_valid": checksum_valid,
        "appended_sha256_valid": digest_valid,
        "sha256": hashlib.sha256(image[:end]).hexdigest(),
    }
    if len(image) >= 288 and image[32:36] == b"\x32\x54\xcd\xab":
        desc = image[32:288]
        result["description"] = {
            name: cstring(desc[start : start + length])
            for name, start, length in [
                ("version", 16, 32),
                ("project", 48, 32),
                ("build_time", 80, 16),
                ("build_date", 96, 16),
                ("idf_version_field", 112, 32),
            ]
        }
        # An identifier is only a compiled string, not proof its feature executes.
        identifiers = []
        for segment in segments:
            if not 0x3F400000 <= segment["address"] < 0x3F800000:
                continue
            start, length = segment["file_offset"], segment["size"]
            for match in re.finditer(
                rb"radar_[a-z_]{3,80}\x00", data[start : start + length]
            ):
                identifiers.append(
                    {
                        "file_offset": start + match.start(),
                        "value": match.group()[:-1].decode("ascii"),
                    }
                )
        result["compiled_radar_identifiers"] = identifiers
        result["attribute_table_candidates"] = attribute_table_candidates(
            data, segments
        )
    if not checksum_valid or digest_valid is False:
        raise ValueError(f"ESP image integrity check failed at {offset:#x}")
    return result


def inspect_flash(path):
    data = path.read_bytes()
    if len(data) != 0x1000000:
        raise ValueError("expected this unit's complete 16 MiB flash backup")
    entries, table_end = [], None
    for position in range(0x8000, 0x9000, 32):
        entry = data[position : position + 32]
        if entry[:2] == b"\xeb\xeb":
            expected = hashlib.md5(data[0x8000:position]).digest()
            if entry[16:32] != expected:
                raise ValueError("partition table MD5 mismatch")
            table_end = position + 32
            break
        if entry == b"\xff" * 32:
            break
        if entry[:2] != b"\xaa\x50":
            raise ValueError(f"invalid partition entry at {position:#x}")
        _, kind, subtype, offset, size, label, flags = struct.unpack(
            "<HBBII16sI", entry
        )
        if offset < 0x9000 or not size or offset + size > len(data):
            raise ValueError("invalid partition bounds")
        content = memoryview(data)[offset : offset + size]
        entries.append(
            {
                "label": cstring(label),
                "type": kind,
                "subtype": subtype,
                "offset": offset,
                "size": size,
                "flags": flags,
                "sha256": hashlib.sha256(content).hexdigest(),
                "non_erased_bytes": sum(byte != 0xFF for byte in content),
            }
        )
    if table_end is None:
        raise ValueError("partition table has no validated MD5 record")
    ordered = sorted(entries, key=lambda entry: entry["offset"])
    for left, right in zip(ordered, ordered[1:]):
        if left["offset"] + left["size"] > right["offset"]:
            raise ValueError("partition overlap")
    images = [inspect_image(data, 0x1000, 0x7000)]
    for entry in entries:
        if entry["type"] == 0:
            images.append(inspect_image(data, entry["offset"], entry["size"]))
    return {
        "source": str(path.resolve()),
        "source_size": len(data),
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "partition_table_offset": 0x8000,
        "partition_table_md5_valid": True,
        "partitions": entries,
        "images": images,
        "limitations": [
            "Static bytes do not establish which OTA slot or radar version is running.",
            "mcu_ota is an ESP32-side update staging region, not a backup of radar flash.",
            "No NVS values, credentials, pairing data, or factory payloads are emitted.",
            "This report does not inspect chip eFuses, security state, or live hardware.",
            "Compiled radar identifiers do not prove implemented behavior or reachability.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("flash", type=Path)
    args = parser.parse_args()
    try:
        result = inspect_flash(args.flash)
    except (OSError, ValueError, struct.error) as error:
        print(f"inspection failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
