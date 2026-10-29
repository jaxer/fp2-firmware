"""Run pure domain harnesses with sanitizers and isolated synthetic wire frames."""

from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def frame(payload):
    header = bytearray([0x55, 0, 1, 0, 5, len(payload) >> 8, len(payload) & 255, 0])
    header[7] = (-sum(header[:7])) & 255
    body = bytes(header) + payload
    crc = 0xFFFF
    for b in body:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return body + crc.to_bytes(2, "little")


class DomainTests(unittest.TestCase):
    def compile_run(self, name, sources, wire=b""):
        with tempfile.TemporaryDirectory(prefix="fp2-domain-") as temporary:
            exe = Path(temporary) / name
            subprocess.run(
                [
                    "c++",
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-fsanitize=address,undefined",
                    "-fno-omit-frame-pointer",
                    "-I",
                    str(ROOT / "components/fp2"),
                    str(ROOT / "tests" / f"{name}_harness.cpp"),
                    *[str(ROOT / "components/fp2" / f"{s}.cpp") for s in sources],
                    "-o",
                    str(exe),
                ],
                check=True,
            )
            subprocess.run([str(exe)], input=wire, check=True, capture_output=True)

    def test_orientation(self):
        self.compile_run("orientation", ["orientation"])

    def test_command_bounds(self):
        self.compile_run("normal_commands", ["normal_commands", "protocol"])

    def test_occupancy(self):
        self.compile_run(
            "occupancy", ["occupancy", "protocol"], frame(bytes([1, 4, 0, 1]))
        )

    def test_target_zones(self):
        self.compile_run(
            "target_zones",
            ["target_zones", "targets", "protocol"],
            frame(bytes.fromhex("011706000100")),
        )
