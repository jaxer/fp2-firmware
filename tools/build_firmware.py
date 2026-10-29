#!/usr/bin/env python3
"""Build the ESP32 app with pinned storage guards; never contact hardware."""

from pathlib import Path
import hashlib
import json
import shutil
import struct
import re
import subprocess
from toolchain import xtensa_tool

from esphome import __main__ as cli, const
from esphome.core import CORE
from storage_guard import patch, STUB, HAL_CALL, HAL_REPLACEMENT
from ota_policy import audit_ota_main, audit_ota_defines

ROOT = Path(__file__).resolve().parents[1]
VERSION = "2026.8.2"
compile_program = cli.compile_program


def audit(project):
    main = (project / "src/main.cpp").read_text()
    defines = (project / "src/esphome/core/defines.h").read_text()
    if (project / "src/esphome/components/esp32/preferences.cpp").read_text() != STUB:
        raise ValueError("Storage guard is absent")
    hal = (project / "src/esphome/components/esp32/hal.cpp").read_text()
    if HAL_CALL in hal or HAL_REPLACEMENT not in hal:
        raise ValueError("Boot metadata guard is absent")
    audit_ota_main("normal", main)
    audit_ota_defines("normal", defines)
    for forbidden in ["CaptivePortal", "WebServer", "GPIO13"]:
        if forbidden in main:
            raise ValueError("Unexpected interface: " + forbidden)
    if main.count("set_enable_target_events(true)") != 1:
        raise ValueError("Target events are not enabled exactly once")
    expected = [
        (1, 2, 0x9000, 0x8000, "nvs"),
        (1, 0, 0x11000, 0x2000, "otadata"),
        (1, 1, 0x13000, 0x1000, "phy_init"),
        (0, 16, 0x20000, 0x200000, "aqara_fw1"),
        (0, 17, 0x220000, 0x200000, "aqara_fw2"),
        (0, 32, 0x420000, 0x13000, "test"),
        (1, 254, 0x433000, 0x400000, "mcu_ota"),
        (1, 2, 0x833000, 0x6000, "fctry"),
    ]
    table = (project / "build/partition_table/partition-table.bin").read_bytes()
    rows = []
    for offset in range(0, len(table), 32):
        if table[offset : offset + 2] != b"\xaa\x50":
            break
        magic, kind, subtype, address, size, label, flags = struct.unpack_from(
            "<HBBII16sI", table, offset
        )
        if flags:
            raise ValueError("Unexpected partition flags")
        rows.append((kind, subtype, address, size, label.split(b"\0")[0].decode()))
    if rows != expected:
        raise ValueError("Partition layout differs from supported stock layout")
    app = project / "build/firmware.ota.bin"
    if not app.exists() or not 0 < app.stat().st_size <= 0x200000:
        raise ValueError("App does not fit a stock OTA slot")
    symbols = subprocess.check_output(
        [str(xtensa_tool("nm")), str(project / "build/firmware.elf")], text=True
    )
    if re.search(
        r"\b(?:nvs_flash_erase(?:_partition)?|esp_ota_mark_app_valid_cancel_rollback)$",
        symbols,
        re.M,
    ):
        raise ValueError("Forbidden automatic storage/boot-metadata writer linked")
    sdk = (project / f"sdkconfig.{CORE.name}").read_text()
    for option in [
        "CONFIG_FREERTOS_UNICORE=y",
        "CONFIG_ESP_SYSTEM_SINGLE_CORE_MODE=y",
        "# CONFIG_ESP_PHY_CALIBRATION_AND_DATA_STORAGE is not set",
        "# CONFIG_SECURE_BOOT is not set",
        "# CONFIG_FLASH_ENCRYPTION_ENABLED is not set",
    ]:
        if option not in sdk:
            raise ValueError("Unexpected SDK configuration: " + option)
    for source in (ROOT / "components/fp2_poc").iterdir():
        if (
            source.suffix in (".cpp", ".h")
            and (project / "src/esphome/components/fp2_poc" / source.name).read_bytes()
            != source.read_bytes()
        ):
            raise ValueError("Generated component source is stale: " + source.name)
    out = ROOT / "artifacts"
    out.mkdir(exist_ok=True)
    shutil.copyfile(app, out / "fp2-esp32.bin")
    sources = list((ROOT / "components/fp2_poc").glob("*")) + list(
        (ROOT / "firmware").glob("*.yaml")
    )
    sources += [
        ROOT / "tools/build_firmware.py",
        ROOT / "tools/storage_guard.py",
        ROOT / "tools/ota_policy.py",
        ROOT / "tools/toolchain.py",
        ROOT / "firmware/stock-partitions.csv",
    ]
    manifest = {
        "esphome": VERSION,
        "app_bytes": app.stat().st_size,
        "app_sha256": hashlib.sha256(app.read_bytes()).hexdigest(),
        "kind": "app-only; never flash at address zero",
        "source_sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(sources)
            if p.is_file() and p.name != "secrets.yaml"
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def guarded_compile(args, config):
    project = Path(CORE.build_path).resolve()
    if project != ROOT / "firmware/.esphome/build/fp2-normal":
        raise ValueError("Unexpected build directory")
    patch(project)
    audit_ota_main("normal", (project / "src/main.cpp").read_text())
    result = compile_program(args, config)
    if result == 0:
        (project / "build/firmware.factory.bin").unlink(missing_ok=True)
        audit(project)
    return result


if __name__ == "__main__":
    if const.__version__ != VERSION:
        raise SystemExit("Requires ESPHome==" + VERSION)
    cli.compile_program = guarded_compile
    raise SystemExit(
        cli.run_esphome(["esphome", "compile", str(ROOT / "firmware/fp2-normal.yaml")])
    )
