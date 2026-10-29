"""Small stock-shaped XMODEM sender. No serial/device access in this module."""

import binascii
import time

BLOCK = 1024


def packet(bundle, index):
    if not 0 <= index < (len(bundle) + BLOCK - 1) // BLOCK:
        raise ValueError("block outside bundle")
    data = bundle[index * BLOCK : (index + 1) * BLOCK].ljust(BLOCK, b"\xff")
    seq = (index + 1) & 255
    return (
        bytes((2, seq, seq ^ 255)) + data + binascii.crc_hqx(data, 0).to_bytes(2, "big")
    )


def send(link, bundle, *, clock=time.monotonic, event=lambda **kw: None):
    """link.write(bytes) and link.read() implement transport, not flash policy.

    Fixed CRC1K, FF final padding, 20s readiness, 3s retry/four retries.
    CAN is failure even at EOT; success requires ACK. No erase/reset/flag/CAN
    command is generated here. Caller owns entry, recovery and verification.
    """
    if not bundle:
        raise ValueError("empty bundle")
    overall = clock() + 900

    def wait(wanted, seconds, clean=False):
        deadline = min(clock() + seconds, overall)
        while clock() < deadline:
            received = link.read()
            if received:
                event(kind="rx", hex=received.hex())
                if 0x18 in received:
                    raise RuntimeError("radar cancelled transfer; recovery not assumed")
                control = received.strip(b"\0\xff\r\n ") if clean else received
                if clean and (
                    not control or any(byte not in wanted for byte in control)
                ):
                    continue
                if any(byte in wanted for byte in control):
                    return True
        return False

    if not wait((0x43, 0x15), 20, clean=True):
        raise TimeoutError("no updater readiness")
    blocks = (len(bundle) + BLOCK - 1) // BLOCK
    for index in range(blocks):
        raw = packet(bundle, index)
        for attempt in range(5):
            if clock() >= overall:
                raise TimeoutError("overall transfer deadline")
            link.write(raw)  # an ambiguous transport write raises; never retried here
            event(kind="block", index=index, sequence=raw[1], attempt=attempt)
            if wait((6,), 3):
                break
        else:
            raise TimeoutError(f"block {index} not acknowledged")
    for attempt in range(4):
        link.write(b"\x04")
        event(kind="eot", attempt=attempt)
        if wait((6,), 3):
            return {
                "transport_complete": True,
                "blocks": blocks,
                "bytes": len(bundle),
                "image_verified": False,
            }
    raise TimeoutError("EOT not acknowledged")
