#!/usr/bin/env python3
"""Build pinned GNU tic6x objdump locally; never installs software."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

VERSION = "2.44"
URL = f"https://ftp.gnu.org/gnu/binutils/binutils-{VERSION}.tar.xz"
SHA256 = "ce2017e059d63e67ddb9240e9d4ec49c2893605035cd60e92ad53177f4377237"
FLAGS = [
    "--target=tic6x-none-elf",
    "--disable-nls",
    "--disable-libctf",
    "--disable-libsframe",
    "--disable-gdb",
    "--disable-gdbserver",
    "--disable-gas",
    "--disable-ld",
    "--disable-gold",
    "--disable-gprof",
    "--disable-gprofng",
    "--disable-sim",
    "--disable-doc",
    "--disable-werror",
    "--without-debuginfod",
    "--without-zstd",
    "--with-system-zlib",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, choices=range(1, 5), default=4)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    output = repo / ".tools/tic6x-binutils"
    source = repo / ".tools/tic6x-binutils-source"
    build = output / "build"
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"binutils-{VERSION}.tar.xz"
    if not archive.exists():
        temporary = archive.with_suffix(".download")
        urllib.request.urlretrieve(URL, temporary)
        temporary.rename(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != SHA256:
        raise SystemExit(f"Archive SHA256 mismatch: {digest}")
    if not source.exists():
        staging = output / "extract"
        staging.mkdir(exist_ok=True)
        with tarfile.open(archive) as package:
            package.extractall(staging, filter="data")
        (staging / f"binutils-{VERSION}").rename(source)
        staging.rmdir()
    build.mkdir(exist_ok=True)
    env = dict(
        os.environ,
        CC=shutil.which("clang") or "cc",
        CXX=shutil.which("clang++") or "c++",
    )
    commands = [
        [str(source / "configure"), *FLAGS],
        [
            "make",
            f"-j{args.jobs}",
            "all-build-libiberty",
            "all-libiberty",
            "all-bfd",
            "all-opcodes",
            "configure-binutils",
        ],
        ["make", "-C", "binutils", f"-j{args.jobs}", "objdump"],
    ]
    for index, command in enumerate(commands):
        log = output / f"{index + 1}-build.log"
        print(f"Running {command}; log: {log}", flush=True)
        with log.open("w") as stream:
            subprocess.run(
                command,
                cwd=build,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=True,
            )
    executable = build / "binutils/objdump"
    version = subprocess.check_output([str(executable), "--version"], text=True)
    receipt = {
        "source_url": URL,
        "source_sha256": digest,
        "target": "tic6x-none-elf",
        "commands": commands,
        "compiler": env["CC"],
        "objdump": str(executable),
        "version": version,
        "installed": False,
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(executable)


if __name__ == "__main__":
    main()
