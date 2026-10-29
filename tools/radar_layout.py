#!/usr/bin/env python3
"""Supported vendor radar layout and identity; no device access."""

from __future__ import annotations
import hashlib
import struct
from verify_ti_crc64 import crc64_ti

SUPPORTED_BUNDLE_SHA256 = (
    "d2ebea24b9e52014d50541a6e83646211b19f296f2381fdc9fb586c342a1dcb1"
)


def validate_source(source):
    if len(source) != 0x1000000:
        raise ValueError("Requires an owner-supplied 16MiB ESP32 backup")
    bundle = source[0x433000 : 0x433000 + 0x250011]
    if hashlib.sha256(bundle).hexdigest() != SUPPORTED_BUNDLE_SHA256:
        raise ValueError(
            "Unsupported vendor radar bundle; do not bypass the identity check"
        )


PARTITION_OFFSET = 0x433000
PARTITION_SIZE = 0x400000
PACKAGE_OFFSETS = (0, 0x12000, 0xC0000, 0xD2000, 0x1A0000)
PATCHES = (
    (0x2652E, bytes.fromhex("4a7e"), bytes.fromhex("6522")),
    (0x26534, bytes.fromhex("497e"), bytes.fromhex("6521")),
)
GETTER = bytes.fromhex(
    "0f491cb50968044607a04a7e8df80020497efef797fc4ff48171204600226b46f2f748fd1cbd"
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def crc_words(data):
    value = crc64_ti(data)
    return struct.pack("<II", value >> 32, value & 0xFFFFFFFF)
