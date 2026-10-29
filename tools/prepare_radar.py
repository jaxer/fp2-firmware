#!/usr/bin/env python3
"""Build a version-checked radar monitor bundle from an owner's stock backup."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from prepare_radar_export import prepare
from inspect_radar_bundle import envelope_candidate
from radar_layout import (
    PARTITION_OFFSET,
    PARTITION_SIZE,
    validate_source,
)

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("backup", type=Path)
    p.add_argument("--output", type=Path, default=ROOT / ".tools/radar-image")
    a = p.parse_args()
    source = a.backup.read_bytes()
    validate_source(source)
    a.output.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location(
        "monitor_builder", ROOT / "firmware/radar_export/build.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    wrapper = a.output / "wrapper"
    manifest = builder.build(wrapper)
    raw = (wrapper / "export.bin").read_bytes()
    overlay, package, receipt = prepare(source, raw, manifest)
    bundle = envelope_candidate(
        source[PARTITION_OFFSET : PARTITION_OFFSET + PARTITION_SIZE], overlay
    )
    (a.output / "monitor.bin").write_bytes(bundle)
    receipt["bundle_sha256"] = hashlib.sha256(bundle).hexdigest()
    receipt["wrapper_manifest_sha256"] = hashlib.sha256(
        (wrapper / "manifest.json").read_bytes()
    ).hexdigest()
    (a.output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(
        json.dumps(
            {
                "bundle_sha256": receipt["bundle_sha256"],
                "wrapper_sha256": manifest["raw_sha256"],
                "bytes": len(bundle),
                "device_access": False,
            }
        )
    )


if __name__ == "__main__":
    main()
