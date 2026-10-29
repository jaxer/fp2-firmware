"""Bounded UART transactions over the RAM bridge."""

import ram_bridge as bridge


def write_uart(lines, data, *, poll_ahead=False):
    if not 1 <= len(data) <= 1029 or b"X" in lines.sent:
        raise ValueError("bounded raw UART write refused")
    lines.sent.extend(b"W")
    raw = b"W" + len(data).to_bytes(2, "little") + data
    if poll_ahead:
        raw += b"P"
        lines.sent.extend(b"P")
        lines.prefetched_polls = getattr(lines, "prefetched_polls", 0) + 1
    if lines.serial.write(raw) != len(raw):
        raise OSError("uncertain raw bridge write; not retried")
    if lines.read() != b"WOK":
        raise ValueError("raw UART write not confirmed")


def poll_uart(lines):
    if b"X" in lines.sent:
        raise ValueError("bridge already restored")
    if getattr(lines, "prefetched_polls", 0):
        lines.prefetched_polls -= 1
    else:
        lines.sent.extend(b"P")
        if lines.serial.write(b"P") != 1:
            raise OSError("short bridge poll write")
    reply = bridge.parse_rx(lines.read())
    if reply["uart_error_flags_observed"]:
        raise ValueError(
            f"UART error0x{reply['raw_interrupt']:x} data={reply['raw_bytes_hex'][:128]}"
        )
    return bytes.fromhex(reply["raw_bytes_hex"])


def write_then_poll_uart(lines, data):
    # Queue the capture before waiting on USB latency: private replies can be
    # larger than the radar-facing hardware FIFO.
    return write_uart(lines, data, poll_ahead=True)
