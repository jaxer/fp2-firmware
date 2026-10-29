"""Locate the ESPHome-installed Xtensa tools without machine-specific paths."""

import os
from pathlib import Path
import shutil


def xtensa_tool(name):
    filename = "xtensa-esp32-elf-" + name
    candidates = []
    supplied = os.environ.get("XTENSA_TOOL_BIN")
    if supplied:
        candidates.append(Path(supplied) / filename)
    found = shutil.which(filename)
    if found:
        candidates.append(Path(found))
    for cache in [
        Path.home() / ".cache/esphome/idf/tools",
        Path.home() / "Library/Caches/esphome/idf/tools",
    ]:
        if cache.exists():
            candidates.extend(sorted(cache.glob("xtensa-esp-elf/**/bin/" + filename)))
    result = next((p.resolve() for p in candidates if p.is_file()), None)
    if result is None:
        raise RuntimeError("Build the ESP32 firmware first, or set XTENSA_TOOL_BIN")
    return result
