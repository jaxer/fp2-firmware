"""Vendor updater transaction; no standalone hardware entrypoint."""

import time
from audit_capture import scan
from bridge_uart import write_uart, poll_uart
import ram_bridge as bridge
import radar_xmodem

FLAG = bytes.fromhex("5500011b0200048901270401688e")


def frames(raw):
    return scan(raw, [(0, len(raw), 0.0, 1)])["frames"] if raw else []


def update_exchange(lines, bundle, event=lambda **row: None):
    lines.received_limit = 262144
    write_uart(lines, FLAG)
    received = bytearray()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        received.extend(poll_uart(lines))
        if any(
            f["operation"] == 3
            and f["attribute"] == "0x0127"
            and received[f["offset"] + 8 : f["end_offset"] - 2] == b"\x01\x27\0\0"
            for f in frames(received)
        ):
            break
    else:
        raise TimeoutError(
            "no successful0127 ACK; update flag may already be persistent"
        )
    lines.sent.extend(b"B")
    if lines.serial.write(b"B") != 1:
        raise OSError("uncertain radar reset request")
    boot = bridge.parse_boot(lines.read(seconds=8))
    if boot["uart_error_flags_observed"]:
        raise ValueError("UART errors after update reset")
    initial = bytes.fromhex(boot["raw_bytes_hex"])
    events = []

    class Link:
        def __init__(self):
            self.initial = initial
            self.started = False

        def read(self):
            raw = self.initial if self.initial else poll_uart(lines)
            self.initial = b""
            if not self.started and frames(raw):
                raise RuntimeError(
                    "normal radar frames after reset; updater entry not established"
                )
            return raw

        def write(self, data):
            self.started = True
            write_uart(lines, data)

    def record(**row):
        events.append(row)
        event(**row)

    result = radar_xmodem.send(Link(), bundle, event=record)
    return {
        "mode": "PERSISTENT_RADAR_UPDATE",
        "radar_flash_write_requested": True,
        "flag_ack_capture_hex": received.hex(),
        "boot_capture": boot,
        "transport": result,
        "events": events,
        "image_verified": False,
        "recovery_proven": False,
    }
