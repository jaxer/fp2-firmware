#!/usr/bin/env python3
"""Reconstruct only the hash-bound second retained SBL's initialized RAM view."""

import argparse
import json
from pathlib import Path
import struct
from export_runtime_elf import decompress, sha
from inspect_radar_package import arm_elf

RPRC_HASH = "5d03c627ee55bd8abcbdd0949b39eddd8c9a95543fbc59d63480633c15c5b6c2"


def reconstruct(flash, manifest):
    if sha(flash) != manifest["source_sha256"]:
        raise ValueError("flash hash mismatch")
    p = manifest["partition"]
    payload = flash[p["offset"] : p["offset"] + p["size"]]
    if sha(payload) != p["sha256"]:
        raise ValueError("partition hash mismatch")
    (package,) = [
        p for p in manifest["validated_packages"] if p["offset_in_partition"] == 0xC0000
    ]
    (image,) = package["images"]
    source_start = 0xC0000 + image["offset_in_package"]
    source = payload[source_start : source_start + image["size"]]
    if (
        image["core_magic"] != "0x35510000"
        or sha(source) != RPRC_HASH
        or image["sha256"] != RPRC_HASH
    ):
        raise ValueError("this exporter only supports the exact second SBL RPRC")
    sparse = {}
    for section in image["rprc"]["sections"]:
        start = section["data_offset_in_partition"]
        raw = payload[start : start + section["size"]]
        if sha(raw) != section["sha256"]:
            raise ValueError("section hash mismatch")
        sparse.update(enumerate(raw, section["load_address"]))

    def read(a, n):
        return bytes(sparse[i] for i in range(a, a + n))

    guards = {
        0xFA54: "500f11ee0f36a0e3030080e1500f01ee0101a0e3100ae8ee00000fe11f00c0e31f0080e300f029e101008fe210ff2fe1",
        0xFA84: "0c4885460c4885446f4607208743bd460a486f4607600a48002803d07946491d8e46004700f016e800f010f800f00ae8fee7c046",
        0xF9F8: "08b50649064a0748521a00f013f80649064a0748521a00f00df808bd",
        0xFA2C: "0346101c05d011f8012b401e03f8012bf9d17047",
        0x7AF4: "f0402de9c4009fe5010070e36b09001bc4509fe5c4709fe5c4609fe5070055e10600002a0300b5e80040d0e50441a0e1044096e7010080e234ff2fe1f6ffffeaa0009fe5",
        0xABEC: "8446f8b540f6ff731cf8015b002410e0521e12f8010b7f1e01f8010bf9d103e01cf8010b01f8010b641c082c4fea5505eada6808f4d21cf8012b1cf8010b00f00f07ff1c122fc0f3031040ea021008d11cf8012b160a24bf1cf8016b66f3df12bf188342a1eb0002d2d1f8bd",
        0x5F24: "d0f803200846002104f08aba",
        0xD6FE: "0346d3f803200846d91dfbf79ebd",
    }
    for address, expected in guards.items():
        if read(address, len(bytes.fromhex(expected))).hex() != expected:
            raise ValueError(f"instruction guard differs at {address:#x}")
    tables = {
        0xFA14: (0x100, 0xD804, 0x08000000, 0xD808, 0xF9F8, 0x08018B98),
        0xFAC4: (0xF9F9,),
        0xFAD8: (0xE51FF004, 0x080079F4),
        0x7BD0: (0xFE10, 0xFE30, 0xFDEC, 0x08008E30),
        0xFDEC: (0x08005E25, 0x0800AAED, 0x0800D5FF),
        0xFE10: (
            0xFAE0,
            0x08015740,
            0xFDF8,
            0x0801ADC0,
            0xFE00,
            0x0801DFA0,
            0xFE08,
            0x0800D708,
        ),
    }
    for address, expected in tables.items():
        if (
            struct.unpack("<" + "I" * len(expected), read(address, 4 * len(expected)))
            != expected
        ):
            raise ValueError(f"literal/table guard differs at {address:#x}")
    sections, records = [], []

    def add(kind, dest, raw, **evidence):
        sections.append((dest, raw))
        records.append(
            dict(
                kind=kind,
                runtime_start=dest,
                runtime_end_exclusive=dest + len(raw),
                size=len(raw),
                sha256=sha(raw),
                **evidence,
            )
        )

    for i in (0, 3, 4):
        s = image["rprc"]["sections"][i]
        add(
            "unrelocated_load_bytes",
            s["load_address"],
            read(s["load_address"], s["size"]),
            rprc_section=i,
        )
    for start, end, dest in ((0x100, 0xD804, 0x08000000), (0xD808, 0xF9F8, 0x08018B98)):
        add(
            "startup_copy",
            dest,
            read(start, end - start),
            load_start=start,
            load_end_exclusive=end,
        )
    decoded, end = decompress(sparse, 0xFAE1, 0xFDEC)
    if (
        end != 0xFDEA
        or read(end, 2) != b"\0\0"
        or len(decoded) != 0x3458
        or read(0xFAE0, 1) != b"\x01"
    ):
        raise ValueError("compressed initialization extent differs")
    add(
        "decompressed_initialization",
        0x08015740,
        decoded,
        source_record_load=0xFAE0,
        compressed_end_exclusive_load=end,
        handler_load=0xABEC,
    )
    for record, dest, size in (
        (0xFDF8, 0x0801ADC0, 0x21D0),
        (0xFE00, 0x0801DFA0, 0x800),
        (0xFE08, 0x0800D708, 0x8000),
    ):
        if read(record, 8) != struct.pack("<II", 0, size):
            raise ValueError("zero record differs")
        add(
            "zero_initialization",
            dest,
            bytes(size),
            source_record_load=record,
            handler_load=0x5F24,
        )
    buffer, exported_sections = bytearray(), []
    for address, raw in sorted(sections):
        exported_sections.append(
            dict(
                load_address=address,
                data_offset_in_partition=len(buffer),
                size=len(raw),
            )
        )
        buffer.extend(raw)
    binary = arm_elf(
        buffer,
        {
            "rprc": {
                "entrypoint": image["rprc"]["entrypoint"],
                "sections": exported_sections,
            }
        },
    )
    return binary, dict(
        scope="second retained SBL only, package offset 0xc0000; static initialized view",
        source_sha256=sha(flash),
        partition_sha256=sha(payload),
        source_rprc_sha256=sha(source),
        runtime_elf_sha256=sha(binary),
        runtime_sections=records,
        instruction_byte_guards={hex(k): v for k, v in guards.items()},
        literal_guards={hex(k): [hex(x) for x in v] for k, v in tables.items()},
        limitations=[
            "Analysis ELF, not firmware or live RAM; RWX flags are assumptions.",
            "No global instruction mode or global address delta.",
            "Original copied sources omitted; gaps remain unmapped.",
            "Receiver/commit/recovery and installed version are not established.",
        ],
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("flash", type=Path)
    p.add_argument("--manifest", type=Path, default=Path(".tools/radar-package.json"))
    p.add_argument("--output", type=Path)
    p.add_argument("--report", type=Path)
    a = p.parse_args()
    binary, report = reconstruct(
        a.flash.read_bytes(), json.loads(a.manifest.read_text())
    )
    if a.output:
        with a.output.open("xb") as f:
            f.write(binary)
        report["runtime_elf_path"] = str(a.output)
    if a.report:
        a.report.write_text(json.dumps(report, indent=2) + "\n")
    else:
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
