#!/usr/bin/env python3
"""Locate the ESPHome-installed Xtensa toolchain and build the RAM bridge."""

import importlib.util
from toolchain import xtensa_tool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    compiler = xtensa_tool("gcc")
    spec = importlib.util.spec_from_file_location(
        "bridge_builder", ROOT / "firmware/esp32_ram_bridge/build.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    receipt = builder.build(
        ROOT / ".tools/esp32-ram-xmodem-bridge", compiler.parent.resolve()
    )
    print("Built RAM bridge:", receipt["elf_sha256"])


if __name__ == "__main__":
    main()
