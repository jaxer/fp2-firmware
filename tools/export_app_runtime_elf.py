#!/usr/bin/env python3
"""Export the retained 0x12000 main MSS application's static initialized view."""

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
        p for p in manifest["validated_packages"] if p["offset_in_partition"] == 0x12000
    )
    image = package["images"][0]
    start = 0x12000 + image["offset_in_package"]
    source = payload[start : start + image["size"]]
    if sha(source) != image["sha256"] or image["core_magic"] != "0x35510000":
        raise ValueError("main MSS source mismatch")
    sparse, sections, records = {}, [], []
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

    check(0x22ED0, "01008fe210ff2fe1")  # ARM add r0,pc,#1; bx r0
    check(0x1D6B6, "7047")  # startup hook returns, no relocation
    check(0x22EFC, "fcf732ff05f0a6fe02f06cfd")
    check(0x1FD7C, "03cd0478a4003459401ca047f6e7")
    check(0x17674, "d0f80320084600210bf04ab9")
    check(0x290E2, "0346d3f803200846d91df7f7f2b9")
    # Handler 1 implements the same flag/back-reference algorithm as the SBL;
    # assert every instruction, including the length extension and sentinel.
    check(
        0x23844,
        "8446f8b540f6ff731cf8015b002410e0521e12f8010b7f1e01f8010bf9d103e01cf8010b01f8010b641c082c4fea5505eada6808f4d21cf8012b1cf8010b00f00f07ff1c122fc0f3031040ea021008d11cf8012b160a24bf1cf8016b66f3df12bf188342a1eb0002d2d1f8bd",
    )
    if words(0x22F18, 1) != (0x1D6B7,) or words(0x1FDF4, 4) != (
        0x37610,
        0x37630,
        0x375EC,
        0x24291,
    ):
        raise ValueError("startup/dispatcher literals mismatch")
    if words(0x375EC, 3) != (0x17675, 0x23845, 0x290E3):
        raise ValueError("handler table mismatch")
    table = words(0x37610, 8)
    if table != (
        0x2AB38,
        0x0801E000,
        0x375F8,
        0x0802AC40,
        0x37600,
        0x0802DDB8,
        0x37608,
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

    # Main application executes at its original low addresses. Preserve all loads.
    for s in image["rprc"]["sections"]:
        add(
            "unrelocated_load_bytes",
            s["load_address"],
            read(s["load_address"], s["size"]),
        )
    if read(0x2AB38, 1) != b"\x01":
        raise ValueError("compressed handler index mismatch")
    out, end = decompress(sparse, 0x2AB39, 0x375EC)
    if len(out) != 0xCC3A or end != 0x375EC:
        raise ValueError("compressed extent mismatch")
    add(
        "decompressed_initialization",
        0x0801E000,
        out,
        source_record_load=0x2AB38,
        compressed_end_exclusive_load=end,
        handler_load=0x23844,
    )
    for source_record, dest, size in (
        (0x375F8, 0x0802AC40, 0x3174),
        (0x37600, 0x0802DDB8, 0x800),
        (0x37608, 0x08000000, 0x1E000),
    ):
        if words(source_record, 2) != (0, size):
            raise ValueError("zero record mismatch")
        add(
            "zero_initialization",
            dest,
            bytes(size),
            source_record_load=source_record,
            handler_load=0x17674,
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
        scope="retained package 0x12000 main MSS only; immediately after record initialization",
        source_sha256=sha(flash),
        partition_sha256=sha(payload),
        source_rprc_sha256=sha(source),
        original_load_elf_sha256=sha(
            Path(".tools/radar/mstr_012000_mss.elf").read_bytes()
        ),
        runtime_elf_sha256=sha(elf),
        runtime_sections=records,
        startup_evidence=dict(
            arm_entry=0x22EA8,
            thumb_entry=0x22ED8,
            returning_hook_pointer=0x1D6B7,
            initializer_dispatcher=0x1FD64,
            record_table=[0x37610, 0x37630],
            handler_table=0x375EC,
            post_record_hook=0x24291,
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
