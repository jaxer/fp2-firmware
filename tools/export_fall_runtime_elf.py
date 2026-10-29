#!/usr/bin/env python3
"""Export the retained 0xd2000 provisional fall MSS application's static initialized view."""

import argparse
import json
from pathlib import Path
import struct
from inspect_radar_package import arm_elf
from export_runtime_elf import decompress, sha


def reconstruct(flash, manifest):
    if sha(flash) != manifest["source_sha256"]:
        raise ValueError("source hash mismatch")
    p = manifest["partition"]
    payload = flash[p["offset"] : p["offset"] + p["size"]]
    if sha(payload) != p["sha256"]:
        raise ValueError("partition hash mismatch")
    package = next(
        p for p in manifest["validated_packages"] if p["offset_in_partition"] == 0xD2000
    )
    image = package["images"][0]
    start = 0xD2000 + image["offset_in_package"]
    source = payload[start : start + image["size"]]
    if sha(arm_elf(payload, image)) != sha(
        Path(".tools/radar/mstr_0d2000_mss.elf").read_bytes()
    ):
        raise ValueError("original load ELF differs from source derivation")
    if sha(source) != image["sha256"] or image["core_magic"] != "0x35510000":
        raise ValueError("provisional fall MSS source mismatch")
    sparse, sections, records = {}, [], []
    instruction_evidence = []
    for s in image["rprc"]["sections"]:
        raw = payload[
            s["data_offset_in_partition"] : s["data_offset_in_partition"] + s["size"]
        ]
        if sha(raw) != s["sha256"]:
            raise ValueError("section hash mismatch")
        sparse.update(enumerate(raw, s["load_address"]))

    def read(a, n):
        return bytes(sparse[x] for x in range(a, a + n))

    def words(a, n):
        return struct.unpack("<" + "I" * n, read(a, n * 4))

    def check(a, expected):
        if read(a, len(bytes.fromhex(expected))).hex() != expected:
            raise ValueError(f"instruction mismatch at {a:#x}")
        instruction_evidence.append(dict(address=a, bytes=expected))

    check(
        0x178C4,
        "f0b520480127f84201d005f06ffe204d204f214ebd4206d203cd0478a4003459401ca047f6e71d48002800d08047164d164fbd4202d210cda047fae7f0bd",
    )
    check(
        0x1A9B8,
        "0c4885460c4885446f4607208743bd460a486f4607600a48002803d07946491d8e460047",
    )
    check(0x1A9B0, "01008fe210ff2fe1")  # ARM add r0,pc,#1; bx r0
    check(0x17782, "7047")  # startup hook returns, no relocation
    check(0x1A9DC, "fcf772ff05f0b8fb02f0f4fb")
    check(0x178DC, "03cd0478a4003459401ca047f6e7")
    check(0x13954, "d0f803200846002106f04abd")
    check(0x20562, "0346d3f803200846d91df7f714bd")
    # Handler 1 implements the same flag/back-reference algorithm as the SBL;
    # assert every instruction, including the length extension and sentinel.
    check(
        0x1B324,
        "8446f8b540f6ff731cf8015b002410e0521e12f8010b7f1e01f8010bf9d103e01cf8010b01f8010b641c082c4fea5505eada6808f4d21cf8012b1cf8010b00f00f07ff1c122fc0f3031040ea021008d11cf8012b160a24bf1cf8016b66f3df12bf188342a1eb0002d2d1f8bd",
    )
    if words(0x17948, 3) != (0xFFFFFFFF, 0, 0):
        raise ValueError("optional copy/constructor literals differ")
    if words(0x1A9F8, 1) != (0x17783,) or words(0x17954, 4) != (
        0x22D08,
        0x22D28,
        0x22CE4,
        0x1BD01,
    ):
        raise ValueError("startup/dispatcher literals mismatch")
    if words(0x22CE4, 3) != (0x13955, 0x1B325, 0x20563):
        raise ValueError("handler table mismatch")
    table = words(0x22D08, 8)
    if table != (
        0x22670,
        0x08019000,
        0x22CF0,
        0x0801C378,
        0x22CF8,
        0x0801F640,
        0x22D00,
        0x08000000,
    ):
        raise ValueError("initializer table mismatch")

    def add(kind, a, raw, **extra):
        sections.append((a, raw))
        records.append(
            dict(
                kind=kind,
                runtime_start=a,
                runtime_end_exclusive=a + len(raw),
                size=len(raw),
                sha256=sha(raw),
                **extra,
            )
        )

    # This application executes at its original low addresses. Preserve all loads.
    for s in image["rprc"]["sections"]:
        add(
            "unrelocated_load_bytes",
            s["load_address"],
            read(s["load_address"], s["size"]),
        )
    if read(0x22670, 1) != b"\x01":
        raise ValueError("compressed handler index mismatch")
    out, end = decompress(sparse, 0x22671, 0x22CE4)
    if read(0x22CE3, 1) != b"\x00":
        raise ValueError("compressed alignment byte differs")
    if len(out) != 0x3376 or end != 0x22CE3:
        raise ValueError("compressed extent mismatch")
    add(
        "decompressed_initialization",
        0x08019000,
        out,
        source_record_load=0x22670,
        compressed_end_exclusive_load=end,
        handler_load=0x1B324,
    )
    for source_record, dest, size in (
        (0x22CF0, 0x0801C378, 0x32C4),
        (0x22CF8, 0x0801F640, 0x800),
        (0x22D00, 0x08000000, 0x19000),
    ):
        if words(source_record, 2) != (0, size):
            raise ValueError("zero record mismatch")
        add(
            "zero_initialization",
            dest,
            bytes(size),
            source_record_load=source_record,
            handler_load=0x13954,
        )
    buffer, exports = bytearray(), []
    for a, raw in sorted(sections):
        exports.append(
            dict(load_address=a, data_offset_in_partition=len(buffer), size=len(raw))
        )
        buffer.extend(raw)
    elf = arm_elf(
        buffer, {"rprc": dict(entrypoint=image["rprc"]["entrypoint"], sections=exports)}
    )
    return elf, dict(
        scope="retained package 0xd2000 provisional fall MSS only; immediately after record initialization",
        source_sha256=sha(flash),
        partition_sha256=sha(payload),
        source_rprc_sha256=sha(source),
        original_load_elf_sha256=sha(
            Path(".tools/radar/mstr_0d2000_mss.elf").read_bytes()
        ),
        runtime_elf_sha256=sha(elf),
        runtime_sections=records,
        instruction_evidence=instruction_evidence,
        startup_evidence=dict(
            arm_entry=0x1A988,
            thumb_entry=0x1A9B8,
            returning_hook_pointer=0x17783,
            initializer_dispatcher=0x178C4,
            record_table=[0x22D08, 0x22D28],
            handler_table=0x22CE4,
            post_record_hook=0x1BD01,
        ),
        limitations=[
            "No SBL relocation formula applies: application text remains at low load addresses.",
            "Initializer stores are reconstructed static state, not live RAM.",
            "Post-record hook and subsequent startup can alter data.",
            "ELF flags and section names are analysis assumptions; mixed ARM/Thumb code remains.",
            "Only this exact retained application mapped; installed device version unverified.",
        ],
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("flash", type=Path)
    p.add_argument("--manifest", type=Path, default=Path(".tools/radar-package.json"))
    p.add_argument("--output", type=Path)
    p.add_argument("--report", type=Path)
    a = p.parse_args()
    elf, report = reconstruct(a.flash.read_bytes(), json.loads(a.manifest.read_text()))
    if a.output:
        with a.output.open("xb") as f:
            f.write(elf)
        report["runtime_elf_path"] = str(a.output)
    if a.report:
        a.report.write_text(json.dumps(report, indent=2) + "\n")
    else:
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
