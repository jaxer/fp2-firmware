#!/usr/bin/env python3
"""Prepare an app-only install plan from the owner's fresh backup; no device I/O."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import struct
import zlib
from inspect_flash import inspect_flash, inspect_image

ROOT = Path(__file__).resolve().parents[1]
BOOTLOADER_SHA256 = "c7387384a39eec2ffad214c4fe7fff17e6641b9642accf8a9dbd98ec49375ca7"


def selector(data, partitions):
    ota = next(p for p in partitions if p["label"] == "otadata")
    apps = sorted(
        (p for p in partitions if p["type"] == 0 and 0x10 <= p["subtype"] <= 0x1F),
        key=lambda p: p["subtype"],
    )
    if [p["subtype"] for p in apps] != [0x10, 0x11]:
        raise ValueError("expected contiguous stock OTA slots 0 and 1")
    records = []
    for i in range(2):
        offset = ota["offset"] + i * 0x1000
        raw = data[offset : offset + 32]
        seq, state, crc = (
            struct.unpack_from("<I", raw)[0],
            struct.unpack_from("<I", raw, 24)[0],
            struct.unpack_from("<I", raw, 28)[0],
        )
        # 0x40078eb0 rejects erased sequence and unsigned (state-3)<2.
        # 0x40078ddc calls that predicate before checking the sequence CRC.
        valid = (
            seq != 0xFFFFFFFF
            and state not in (3, 4)
            and crc == zlib.crc32(raw[:4], 0xFFFFFFFF)
        )
        records.append(
            {
                "offset": offset,
                "sequence": seq,
                "state": state,
                "crc": crc,
                "valid": valid,
            }
        )
    valid = [i for i, r in enumerate(records) if r["valid"]]
    if not valid:
        raise ValueError(
            "stock selector has no valid OTA record; fallback requires separate review"
        )
    chosen = max(valid, key=lambda i: (records[i]["sequence"], -i))
    slot = ((records[chosen]["sequence"] - 1) & 0xFFFFFFFF) % len(apps)
    return apps[slot], records, chosen


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("backup", type=Path)
    p.add_argument("--app", type=Path, default=ROOT / "artifacts/fp2-esp32.bin")
    p.add_argument("--output", type=Path, default=ROOT / ".tools/install")
    a = p.parse_args()
    stock = a.backup.read_bytes()
    if (
        len(stock) != 0x1000000
        or hashlib.sha256(stock[0x1000:0x8000]).hexdigest() != BOOTLOADER_SHA256
    ):
        p.error("Unsupported stock bootloader/backup size; do not flash")
    inventory = inspect_flash(a.backup)
    expected = []
    types = {"data": 1, "app": 0}
    subtypes = {"nvs": 2, "ota": 0, "phy": 1, "ota_0": 16, "ota_1": 17, "test": 32}
    for row in csv.reader(
        (ROOT / "firmware/stock-partitions.csv").read_text().splitlines()
    ):
        if not row or row[0].startswith("#"):
            continue
        label, kind, subtype, offset, size, flags = map(str.strip, row)
        expected.append(
            (
                label,
                types[kind],
                subtypes[subtype] if subtype in subtypes else int(subtype, 0),
                int(offset, 0),
                int(size, 0),
                0,
            )
        )
    actual = [
        tuple(x[k] for k in ["label", "type", "subtype", "offset", "size", "flags"])
        for x in inventory["partitions"]
    ]
    if actual != expected:
        p.error("Unsupported partition table")
    slot, records, selected = selector(stock, inventory["partitions"])
    app = a.app.read_bytes()
    image = inspect_image(app, 0, len(app))
    if (
        not image["checksum_valid"]
        or not image["appended_sha256_valid"]
        or image["chip_id"] != 0
        or image["image_size"] != len(app)
    ):
        p.error("Invalid ESP32 app")
    payload = app + b"\xff" * ((-len(app)) % 4096)
    if len(payload) > slot["size"]:
        p.error("App exceeds selected slot")
    a.output.mkdir(parents=True, exist_ok=False)
    target = a.output / "app.bin"
    target.write_bytes(payload)
    restore = a.output / "restore-app.bin"
    restore.write_bytes(stock[slot["offset"] : slot["offset"] + slot["size"]])
    out = {
        "offset": hex(slot["offset"]),
        "selected_slot": slot["label"],
        "bytes": len(payload),
        "backup_sha256": hashlib.sha256(stock).hexdigest(),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "payload": str(target),
        "restore_app": str(restore),
        "app_only": True,
        "precondition": "Fresh backup of this physical unit; live bootloader/table/otadata must still match. Encryption and secure boot must be disabled.",
    }
    (a.output / "plan.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
