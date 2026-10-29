#!/usr/bin/env python3
"""Create private device credentials; CI mode is for build validation only."""

import argparse
import base64
import getpass
import json
from pathlib import Path
import secrets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ci",
        action="store_true",
        help="Generate explicitly non-deployable CI configuration",
    )
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / "firmware/secrets.yaml"
    values = {
        "wifi_ssid": "CI-NOT-A-REAL-NETWORK" if args.ci else input("Wi-Fi SSID: "),
        "wifi_password": "CI-NOT-A-REAL-PASSWORD"
        if args.ci
        else getpass.getpass("Wi-Fi password: "),
        "api_encryption_key": base64.b64encode(secrets.token_bytes(32)).decode(),
        "ota_password": secrets.token_urlsafe(32),
    }
    # Exclusive creation avoids replacing credentials of a device already installed.
    with path.open("x") as stream:
        path.chmod(0o600)
        stream.write("# Private device credentials. Never commit or share.\n")
        if args.ci:
            stream.write("# CI ONLY: never deploy this build.\n")
        for key, value in values.items():
            stream.write(key + ": " + json.dumps(value) + "\n")
    print("Created firmware/secrets.yaml; keep it private. API key is in that file.")


if __name__ == "__main__":
    main()
