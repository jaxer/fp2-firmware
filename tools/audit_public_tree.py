#!/usr/bin/env python3
"""Check the publishable Git file set, not private ignored build material."""

from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def audit():
    paths = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
        )
        .decode()
        .split("\0")
    )
    errors = []
    patterns = [
        re.compile("/" + "Users/"),
        re.compile(r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"),
        re.compile(r"\b(?:[a-fA-F0-9]{2}:){5}[a-fA-F0-9]{2}\b"),
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ]
    forbidden = {".bin", ".elf", ".wav", ".mkv", ".mp4", ".pcap", ".pcapng"}
    for name in sorted(set(paths) - {""}):
        p = ROOT / name
        if p.is_symlink():
            errors.append(name + ": symlink requires explicit review")
            continue
        if p.suffix in forbidden or p.name == "secrets.yaml":
            errors.append(name + ": private/generated artifact")
            continue
        if not p.is_file():
            continue
        try:
            text = p.read_text()
        except UnicodeDecodeError:
            if p.suffix not in {".png", ".jpg", ".webp"}:
                errors.append(name + ": unexpected binary")
            continue
        for pattern in patterns:
            if pattern.search(text):
                errors.append(name + ": identity/credential pattern " + pattern.pattern)
        if p.suffix == ".md":
            for link in re.findall(r"\]\(([^)]+)\)", text):
                if "://" in link or link.startswith("#"):
                    continue
                target = link.split("#", 1)[0]
                if target and not (p.parent / target).exists():
                    errors.append(name + ": broken link " + target)
    if errors:
        raise SystemExit("\n".join(errors))
    print(
        "Public file-set audit passed: no device dumps, secret files, private addresses or broken document links."
    )


if __name__ == "__main__":
    audit()
