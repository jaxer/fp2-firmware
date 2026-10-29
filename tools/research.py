#!/usr/bin/env python3
"""Explicit radar monitor install/inspect/dump through the ESP32 RAM bridge."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
from inspect_radar_bundle import inspect
from radar_layout import validate_source
from prepare_radar_export import load_wrapper
from radar_memory_monitor import Monitor
from radar_update import update_exchange
import ram_bridge as bridge

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_SHA = "ab20b5a16b62af5b36297731566e500802348bff4c6e059dc452f911f725b406"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["install", "inspect", "dump"])
    p.add_argument(
        "--execute",
        action="store_true",
        help="Actually reset and access hardware; otherwise print plan",
    )
    p.add_argument("--accept-unproven-recovery", action="store_true")
    p.add_argument("--backup", type=Path)
    p.add_argument("--port")
    p.add_argument("--output", type=Path)
    p.add_argument("--dump", type=Path)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--image-dir", type=Path, default=ROOT / ".tools/radar-image")
    p.add_argument(
        "--bridge",
        type=Path,
        default=ROOT / ".tools/esp32-ram-xmodem-bridge/bridge.elf",
    )
    p.add_argument("--baud", type=int, choices=[115200, 921600], default=921600)
    a = p.parse_args()
    if not a.execute:
        print(
            json.dumps(
                {
                    "action": a.action,
                    "hardware_access": False,
                    "requires": [
                        "owner backup",
                        "built radar image",
                        "built RAM bridge",
                        "FTDI with reset/bootstrap control",
                    ],
                    "warning": "Radar install erases persistent flash; interrupted-update recovery is not proven.",
                }
            )
        )
        return 0
    if not a.port or not a.backup or not a.output:
        p.error("--execute requires --port, --backup, --output")
    if a.action == "install" and not a.accept_unproven_recovery:
        p.error("install requires --accept-unproven-recovery")
    if a.action == "dump" and not a.dump:
        p.error("dump requires --dump")
    if a.resume and a.action != "dump":
        p.error("--resume is only for dumps")
    if not a.output.resolve().is_relative_to(ROOT / ".tools"):
        p.error("output must be under ignored .tools/")
    if a.dump and not a.dump.resolve().is_relative_to(ROOT / ".tools"):
        p.error("dump must be under ignored .tools/")
    source = a.backup.read_bytes()
    validate_source(source)
    receipt = json.loads((a.image_dir / "receipt.json").read_text())
    raw, manifest, _ = load_wrapper(
        a.image_dir / "wrapper",
        receipt["wrapper_sha256"],
        receipt["wrapper_manifest_sha256"],
    )
    bundle = (a.image_dir / "monitor.bin").read_bytes()
    if hashlib.sha256(bundle).hexdigest() != BUNDLE_SHA:
        raise ValueError("Unsupported monitor bundle")
    inspect(bundle)

    def guard():
        if (
            hashlib.sha256(a.backup.read_bytes()).digest()
            != hashlib.sha256(source).digest()
        ):
            raise ValueError("Backup changed")
        return {"backup_sha256": hashlib.sha256(source).hexdigest()}

    def exchange(lines):
        if a.action == "install":
            return update_exchange(lines, bundle)
        monitor = Monitor(lines)
        if monitor.read(0x38000, 128) != raw[:128]:
            raise ValueError("Installed monitor code does not match build")
        if a.action == "dump":
            return {"success": True, "dump": monitor.dump(a.dump, resume=a.resume)}
        return {
            "success": True,
            "code_prefix_verified": True,
            "metadata": monitor.capacity(),
        }

    result = bridge.run(
        a.port,
        a.bridge,
        a.output,
        guard=guard,
        exchange=exchange,
        radar_flash_write_requested=a.action == "install",
        resume_on_error=a.action != "install",
        baud=a.baud,
    )
    print(
        json.dumps(
            {
                "success": result["success"],
                "errors": result["errors"],
                "receipt": str(a.output),
            }
        )
    )
    return (
        0
        if result["success"]
        and result.get("exchange", {}).get("success", a.action == "install")
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
