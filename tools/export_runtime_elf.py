#!/usr/bin/env python3
"""Reconstruct the first retained MSS image's post-startup address view, offline.

No original artifact is modified. Bytes come only from the retained flash dump
and the instruction-proven copy/decompression/zero-init sequence. This is an
analysis container, not a firmware image or an executable emulator snapshot.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct

from inspect_radar_package import arm_elf


def sha(data):
    return hashlib.sha256(data).hexdigest()


def decompress(data, start, end):
    """Exact byte algorithm at load 0xad68 / runtime 0x0800ac68, handler 1."""
    cursor, output = start, bytearray()

    def byte():
        nonlocal cursor
        if cursor >= end:
            raise ValueError("compressed stream exceeds its retained extent")
        value = data[cursor]
        cursor += 1
        return value

    while True:
        flags = byte()
        for bit in range(8):
            if flags & (1 << bit):
                output.append(byte())
                continue
            first, second = byte(), byte()
            distance_minus_one = (first << 4) | (second >> 4)
            length = (second & 15) + 3
            if length == 18:
                extension = byte()
                if extension & 128:
                    extension = (extension & 127) | (byte() << 7)
                length += extension
            if distance_minus_one == 4095:
                return bytes(output), cursor
            distance = distance_minus_one + 1
            if distance > len(output) or len(output) + length > 0x100000:
                raise ValueError(
                    "invalid compressed back-reference or excessive output"
                )
            for _ in range(length):
                output.append(output[-distance])


def reconstruct(flash, manifest):
    if sha(flash) != manifest["source_sha256"]:
        raise ValueError("flash hash differs from the retained source manifest")
    partition = manifest["partition"]
    payload = flash[partition["offset"] : partition["offset"] + partition["size"]]
    if sha(payload) != partition["sha256"]:
        raise ValueError("partition hash mismatch")
    package = manifest["validated_packages"][0]
    image = package["images"][0]
    if package["offset_in_partition"] != 0 or image["core_magic"] != "0x35510000":
        raise ValueError("tool only implements the first retained SBL MSS image")
    source = payload[
        image["offset_in_package"] : image["offset_in_package"] + image["size"]
    ]
    if sha(source) != image["sha256"]:
        raise ValueError("RPRC hash mismatch")
    sparse = {}
    load_sections = image["rprc"]["sections"]
    for section in load_sections:
        start = section["data_offset_in_partition"]
        raw = payload[start : start + section["size"]]
        if sha(raw) != section["sha256"]:
            raise ValueError("RPRC section hash mismatch")
        sparse.update(enumerate(raw, section["load_address"]))

    def read(address, size):
        try:
            return bytes(sparse[i] for i in range(address, address + size))
        except KeyError as exc:
            raise ValueError(f"unmapped load address {exc.args[0]:#x}") from exc

    def words(address, count):
        return struct.unpack("<" + "I" * count, read(address, count * 4))

    # Lock this derivation to the actual startup instruction sequences, not
    # merely to a hypothesized mapping inferred from function-pointer names.
    if (
        read(0xFB68, 28).hex()
        != "08b50649064a0748521a00f013f80649064a0748521a00f00df808bd"
    ):
        raise ValueError("startup copy sequence differs")
    if read(0xFB9C, 20).hex() != "0346101c05d011f8012b401e03f8012bf9d17047":
        raise ValueError("startup byte-copy helper differs")
    if words(0xFB84, 6) != (0x100, 0xD974, 0x08000000, 0xD978, 0xFB68, 0x08018CD8):
        raise ValueError("startup copy literals differ")
    if words(0x7C50, 4) != (0xFF80, 0xFFA0, 0xFF58, 0x08008EB0):
        raise ValueError("runtime initialization dispatcher literals differ")
    if words(0xFF58, 3) != (0x08005D25, 0x0800AC69, 0x0800D76F):
        raise ValueError("initialization handler pointers differ")
    expected_table = (
        0xFC50,
        0x08015880,
        0xFF68,
        0x0801AF00,
        0xFF70,
        0x0801E0E0,
        0xFF78,
        0x0800D878,
    )
    if words(0xFF80, 8) != expected_table:
        raise ValueError("initialization table differs")

    sections, records = [], []

    def add(kind, address, raw, **evidence):
        sections.append((address, raw))
        records.append(
            {
                "kind": kind,
                "runtime_start": address,
                "runtime_end_exclusive": address + len(raw),
                "size": len(raw),
                "sha256": sha(raw),
                **evidence,
            }
        )

    # Preserve vectors and the low startup/initializer ranges. Omit the old low
    # text/data copies to prevent ambiguous duplicate function discovery.
    for index in (0, 3, 4):
        section = load_sections[index]
        add(
            "unrelocated_load_bytes",
            section["load_address"],
            read(section["load_address"], section["size"]),
            rprc_section=index,
        )
    for start, end, destination in (
        (0x100, 0xD974, 0x08000000),
        (0xD978, 0xFB68, 0x08018CD8),
    ):
        add(
            "startup_copy",
            destination,
            read(start, end - start),
            load_start=start,
            load_end_exclusive=end,
            copy_caller_load=0xFB68,
            copy_helper_load=0xFB9C,
        )
    decompressed, consumed_end = decompress(sparse, 0xFC51, 0xFF58)
    if consumed_end != 0xFF58 or len(decompressed) != 0x3458:
        raise ValueError("compressed initialization extent differs")
    add(
        "decompressed_initialization",
        0x08015880,
        decompressed,
        source_record_load=0xFC50,
        compressed_start_load=0xFC51,
        compressed_end_exclusive_load=consumed_end,
        handler_index=1,
        handler_runtime_pointer=0x0800AC69,
        handler_load=0xAD68,
    )
    for record, destination, expected_size in (
        (0xFF68, 0x0801AF00, 0x21D0),
        (0xFF70, 0x0801E0E0, 0x800),
        (0xFF78, 0x0800D878, 0x8000),
    ):
        if read(record, 4) != b"\0" * 4 or words(record + 4, 1)[0] != expected_size:
            raise ValueError("zero initializer differs")
        add(
            "zero_initialization",
            destination,
            bytes(expected_size),
            source_record_load=record,
            handler_index=0,
            handler_runtime_pointer=0x08005D25,
            handler_load=0x5E24,
        )
    buffer = bytearray()
    exported_sections = []
    for address, raw in sorted(sections):
        exported_sections.append(
            {
                "load_address": address,
                "data_offset_in_partition": len(buffer),
                "size": len(raw),
            }
        )
        buffer.extend(raw)
    exported = arm_elf(
        buffer,
        {
            "rprc": {
                "entrypoint": image["rprc"]["entrypoint"],
                "sections": exported_sections,
            }
        },
    )
    report = {
        "scope": "first retained MSTR package, MSS SBL only; post-startup analysis view",
        "source_sha256": sha(flash),
        "partition_sha256": sha(payload),
        "source_rprc_sha256": sha(source),
        "runtime_elf_sha256": sha(exported),
        "original_load_elf_sha256": sha(
            Path(".tools/radar/mstr_000000_mss.elf").read_bytes()
        ),
        "runtime_sections": records,
        "startup_evidence": {
            "arm_entry_load": 0xFBC4,
            "thumb_switch_load": 0xFBF4,
            "copy_call_pointer_literal_load": 0xFC34,
            "copy_call_thumb_pointer": 0xFB69,
            "init_arm_veneer_load": 0xFC48,
            "init_arm_pointer_literal_load": 0xFC4C,
            "init_arm_runtime": 0x08007A74,
            "init_arm_load": 0x7B74,
            "initializer_table_load": [0xFF80, 0xFFA0],
            "handler_pointer_table_load": 0xFF58,
            "handler_dispatch_load": [0x7B98, 0x7BB0],
        },
        "pointer_example": {
            "thumb_pointer": 0x0800ABFD,
            "runtime_instruction_address": 0x0800ABFC,
            "original_load_instruction_address": 0xACFC,
        },
        "limitations": [
            "Analysis ELF flags and generated section names are assumptions, not device permissions.",
            "No global Thumb mode: copied text contains ARM, Thumb, literal pools and inline strings.",
            "Low original text/data copies are omitted; startup source references are not backed in this post-startup container.",
            "Zero regions reflect initializer stores, not an observed live RAM dump; gaps remain unmapped.",
            "Mapping applies to this exact SBL only; other MSS packages require their own startup derivation.",
            "Staging bytes do not identify the radar's installed image or establish upgrade success.",
        ],
    }
    return exported, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("flash", type=Path)
    parser.add_argument(
        "--manifest", type=Path, default=Path(".tools/radar-package.json")
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    binary, report = reconstruct(
        args.flash.read_bytes(), json.loads(args.manifest.read_text())
    )
    if args.output:
        # Never overwrite an analysis container that somebody may have open.
        with args.output.open("xb") as target:
            target.write(binary)
        report["runtime_elf_path"] = str(args.output)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    else:
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
