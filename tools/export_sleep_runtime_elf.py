#!/usr/bin/env python3
"""Export the retained 0x1a0000 sleep/vitals-labelled MSS application's static initialized view."""

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
        p
        for p in manifest["validated_packages"]
        if p["offset_in_partition"] == 0x1A0000
    )
    image = package["images"][0]
    start = 0x1A0000 + image["offset_in_package"]
    source = payload[start : start + image["size"]]
    if sha(source) != image["sha256"] or image["core_magic"] != "0x35510000":
        raise ValueError("sleep/vitals-labelled MSS source mismatch")
    if (
        sha(payload[0x1A0000 : 0x1A0000 + package["size_with_crc32"]])
        != package["sha256"]
    ):
        raise ValueError("package hash mismatch")
    original_elf = Path(".tools/radar/mstr_1a0000_mss.elf").read_bytes()
    if original_elf != arm_elf(payload, image):
        raise ValueError("original load ELF does not match retained sections")
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

    check(
        0x2879C,
        "500f11ee0f36a0e3030080e1500f01ee0101a0e3100ae8ee00000fe11f00c0e31f0080e300f029e101008fe210ff2fe10c4885460c4885446f4607208743bd460a486f4607600a48002803d07946491d8e460047fcf7e8f907f092f803f0c2f9fee7c046b8e802080008000084e80208ff290200",
    )
    check(
        0x24BC4,
        "f0b520480127f84201d007f087fa204d204f214ebd4206d203cd0478a4003459401ca047f6e71d48002800d08047164d164fbd4202d210cda047fae7f0bd",
    )
    check(
        0x2820A,
        "71b510f0030f0bd0002a82bf00f8011bb2f1010210f0030ff6d1002a08bf71bd11f0ff0141ea0121042a18d341ea0141082a0fd30e46102a08d30c460d46b2f10f0312f00f0272c0103bfcd812f0080f18bf42c012f0040f18bf40f8041b12f0020f18bf20f8021b12f0010f18bf",
    )
    check(0x287C4, "01008fe210ff2fe1")  # ARM add r0,pc,#1; bx r0
    check(0x229FE, "7047")  # startup hook returns, no relocation
    check(0x287F0, "fcf7e8f907f092f803f0c2f9")
    check(0x24BDC, "03cd0478a4003459401ca047f6e7")
    check(0x23124, "d0f803200846002105f06db8")
    check(0x2FDB2, "0346d3f803200846d91df5f7baba")
    # Handler 1 implements the same flag/back-reference algorithm as the SBL;
    # assert every instruction, including the length extension and sentinel.
    check(
        0x2921C,
        "8446f8b540f6ff731cf8015b002410e0521e12f8010b7f1e01f8010bf9d103e01cf8010b01f8010b641c082c4fea5505eada6808f4d21cf8012b1cf8010b00f00f07ff1c122fc0f3031040ea021008d11cf8012b160a24bf1cf8016b66f3df12bf188342a1eb0002d2d1f8bd",
    )
    if words(0x2880C, 1) != (0x229FF,) or words(0x24C54, 4) != (
        0x33680,
        0x336B0,
        0x3364C,
        0x2A341,
    ):
        raise ValueError("startup/dispatcher literals mismatch")
    if words(0x3364C, 3) != (0x23125, 0x2921D, 0x2FDB3):
        raise ValueError("handler table mismatch")
    table = words(0x33680, 12)
    if table != (
        0x32A60,
        0x08029020,
        0x33658,
        0x08023000,
        0x33660,
        0x0802681C,
        0x33668,
        0x51000000,
        0x33670,
        0x08028820,
        0x33678,
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
    if read(0x32A60, 1) != b"\x01":
        raise ValueError("compressed handler index mismatch")
    out, end = decompress(sparse, 0x32A61, 0x3364C)
    if len(out) != 0x5896 or end != 0x3364A:
        raise ValueError("compressed extent mismatch")
    add(
        "decompressed_initialization",
        0x08029020,
        out,
        source_record_load=0x32A60,
        compressed_end_exclusive_load=end,
        handler_load=0x2921C,
    )
    for source_record, dest, size in (
        (0x33658, 0x08023000, 0x381C),
        (0x33660, 0x0802681C, 0x2000),
        (0x33668, 0x51000000, 0x90000),
        (0x33670, 0x08028820, 0x800),
        (0x33678, 0x08000000, 0x23000),
    ):
        if words(source_record, 2) != (0, size):
            raise ValueError("zero record mismatch")
        add(
            "zero_initialization",
            dest,
            bytes(size),
            source_record_load=source_record,
            handler_load=0x23124,
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
        scope="retained package 0x1a0000 sleep/vitals-labelled MSS only; immediately after record initialization",
        source_sha256=sha(flash),
        partition_sha256=sha(payload),
        source_rprc_sha256=sha(source),
        package_sha256=sha(payload[0x1A0000 : 0x1A0000 + package["size_with_crc32"]]),
        original_load_elf_sha256=sha(
            Path(".tools/radar/mstr_1a0000_mss.elf").read_bytes()
        ),
        runtime_elf_sha256=sha(elf),
        runtime_sections=records,
        startup_evidence=dict(
            arm_entry=0x2879C,
            thumb_entry=0x287CC,
            returning_hook_pointer=0x229FF,
            initializer_dispatcher=0x24BC4,
            record_table=[0x33680, 0x336B0],
            handler_table=0x3364C,
            post_record_hook=0x2A341,
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
