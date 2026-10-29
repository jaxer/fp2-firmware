#!/usr/bin/env python3
"""Audit recorded FP2 UART bytes without replaying or repairing missing data.

Reads hansihe's ``t<timestamp> <channel> <hex bytes>`` capture format. Channel
0 is ESP -> radar and channel 1 is radar -> ESP. Only complete frames passing
both header checksum and CRC are accepted. XMODEM blocks additionally require
the sequence complement and CRC16-XMODEM. No payload bytes are exported.
"""

from __future__ import annotations

import argparse
import binascii
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path


def modbus_crc(data: bytes) -> int:
    crc = 0xFFFF
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def read_capture(path: Path) -> tuple[dict, dict, dict]:
    raw = path.read_bytes()
    streams = {0: bytearray(), 1: bytearray()}
    spans = {0: [], 1: []}
    bad = []
    for ordinal, line in enumerate(raw.decode("ascii").splitlines(), 1):
        if not line.strip():
            continue
        try:
            stamp, channel_text, encoded = line.split(" ", 2)
            if not stamp.startswith("t"):
                raise ValueError("missing timestamp prefix")
            timestamp = float(stamp[1:])
            channel = int(channel_text)
            if channel not in streams:
                raise ValueError("unsupported channel")
            data = bytes.fromhex(encoded)
        except ValueError as exc:
            bad.append({"line": ordinal, "error": str(exc)})
            continue
        start = len(streams[channel])
        streams[channel].extend(data)
        spans[channel].append((start, len(streams[channel]), timestamp, ordinal))
    metadata = {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "file_size": len(raw),
        "malformed_line_count": len(bad),
        "malformed_line_examples_up_to_10": bad[:10],
        "byte_counts": {str(k): len(v) for k, v in streams.items()},
        "directions": {"0": "ESP -> radar", "1": "radar -> ESP"},
    }
    return metadata, streams, spans


def locate(spans: list, offset: int) -> dict:
    # Timestamp precision is that of the recorded read chunk, not each byte.
    import bisect

    index = bisect.bisect_right(spans, (offset, float("inf"))) - 1
    _, _, timestamp, line = spans[index]
    return {"offset": offset, "timestamp": timestamp, "source_line": line}


def scan(stream: bytes, spans: list) -> dict:
    frames, blocks, consumed = [], [], []
    failures = Counter()
    pos = 0
    while pos < len(stream):
        if stream[pos : pos + 3] == b"\x55\x00\x01":
            if pos + 8 > len(stream):
                failures["truncated_normal_header"] += 1
            else:
                length = int.from_bytes(stream[pos + 5 : pos + 7], "big")
                end = pos + 10 + length
                expected = ~(sum(stream[pos : pos + 7]) - 1) & 0xFF
                if stream[pos + 7] != expected:
                    failures["normal_header_checksum"] += 1
                elif end > len(stream):
                    failures["truncated_normal_frame"] += 1
                elif modbus_crc(stream[pos : end - 2]) != int.from_bytes(
                    stream[end - 2 : end], "little"
                ):
                    failures["normal_crc"] += 1
                else:
                    payload = stream[pos + 8 : end - 2]
                    attribute = (
                        int.from_bytes(payload[:2], "big")
                        if len(payload) >= 2
                        else None
                    )
                    frame = {
                        **locate(spans, pos),
                        "end_offset": end,
                        "sequence": stream[pos + 3],
                        "operation": stream[pos + 4],
                        "payload_length": length,
                        "attribute": f"0x{attribute:04x}"
                        if attribute is not None
                        else None,
                        "data_type": payload[2] if len(payload) >= 3 else None,
                    }
                    if attribute == 0x0127:
                        frame["boolean_true"] = payload[2:] == b"\x04\x01"
                    if attribute == 0x0102 and len(payload) == 4 and payload[2] == 0:
                        frame["radar_version"] = payload[3]
                    frames.append(frame)
                    consumed.append((pos, end))
                    pos = end
                    continue
        if (
            stream[pos] in (1, 2)
            and pos + 3 <= len(stream)
            and stream[pos + 1] ^ stream[pos + 2] == 0xFF
        ):
            length = 128 if stream[pos] == 1 else 1024
            end = pos + 3 + length + 2
            if end > len(stream):
                failures["truncated_xmodem_candidate"] += 1
            elif binascii.crc_hqx(stream[pos + 3 : end - 2], 0) != int.from_bytes(
                stream[end - 2 : end], "big"
            ):
                failures["xmodem_crc_candidate"] += 1
            else:
                data = stream[pos + 3 : end - 2]
                blocks.append(
                    {
                        **locate(spans, pos),
                        "end_offset": end,
                        "sequence": stream[pos + 1],
                        "block_size": length,
                        "payload_sha256": hashlib.sha256(data).hexdigest(),
                        "starts_with_MSTR": data.startswith(b"MSTR"),
                    }
                )
                consumed.append((pos, end))
                pos = end
                continue
        pos += 1
    return {
        "frames": frames,
        "blocks": blocks,
        "consumed": consumed,
        "candidate_failures": dict(failures),
    }


def controls(
    stream: bytes, spans: list, parsed: dict, start_time: float, end_time: float
) -> dict:
    """Count standalone candidate controls, excluding all validated frame bytes."""
    names = {0x43: "C_readiness", 0x06: "ACK", 0x15: "NAK", 0x18: "CAN", 0x04: "EOT"}
    result = Counter({name: 0 for name in names.values()})
    positions = defaultdict(list)
    ranges = parsed["consumed"]
    cursor = 0
    for start, end, timestamp, _ in spans:
        if not start_time <= timestamp <= end_time:
            continue
        for offset in range(start, end):
            while cursor < len(ranges) and ranges[cursor][1] <= offset:
                cursor += 1
            if cursor < len(ranges) and ranges[cursor][0] <= offset < ranges[cursor][1]:
                continue
            if stream[offset] in names:
                name = names[stream[offset]]
                result[name] += 1
                if len(positions[name]) < 10:
                    positions[name].append(locate(spans, offset))
    return {"counts": dict(result), "first_locations_up_to_10": dict(positions)}


def summarize(metadata: dict, parsed: dict) -> dict:
    attributes = defaultdict(Counter)
    versions = Counter()
    for channel, result in parsed.items():
        for frame in result["frames"]:
            key = f"channel={channel},operation={frame['operation']},type={frame['data_type']}"
            attributes[frame["attribute"]][key] += 1
            if "radar_version" in frame:
                versions[str(frame["radar_version"])] += 1
    return {
        "source": metadata,
        "validated_normal_frames": sum(len(r["frames"]) for r in parsed.values()),
        "observed_attribute_count": len(attributes),
        "attributes": {
            k: dict(v) for k, v in sorted(attributes.items(), key=lambda x: str(x[0]))
        },
        "radar_version_reports": dict(versions),
        "candidate_failures": {
            str(k): v["candidate_failures"] for k, v in parsed.items()
        },
    }


def audit(path: Path) -> dict:
    metadata, streams, spans = read_capture(path)
    parsed = {ch: scan(data, spans[ch]) for ch, data in streams.items()}
    result = summarize(metadata, parsed)
    blocks = parsed[0]["blocks"]
    gaps, duplicates = [], []
    for previous, current in zip(blocks, blocks[1:]):
        advance = (current["sequence"] - previous["sequence"]) & 0xFF
        if advance == 0:
            duplicates.append(
                {
                    "previous": previous,
                    "current": current,
                    "same_payload": previous["payload_sha256"]
                    == current["payload_sha256"],
                }
            )
        elif advance != 1:
            gaps.append(
                {
                    "previous_sequence": previous["sequence"],
                    "current_sequence": current["sequence"],
                    "modulo_256_unobserved_sequence_slots": advance - 1,
                    "previous_offset": previous["offset"],
                    "current_offset": current["offset"],
                }
            )
    triggers = [
        f for ch in parsed.values() for f in ch["frames"] if f["attribute"] == "0x0127"
    ]
    transfer = {
        "trigger_frames": sorted(triggers, key=lambda f: f["timestamp"]),
        "validated_xmodem_blocks": len(blocks),
        "block_sizes": dict(Counter(str(b["block_size"]) for b in blocks)),
        "validated_payload_bytes": sum(b["block_size"] for b in blocks),
        "sequence_gaps": gaps,
        "duplicate_blocks": duplicates,
        "blocks_starting_MSTR": [b for b in blocks if b["starts_with_MSTR"]],
        "complete_image_recovered": False,
    }
    if blocks:
        start = min(
            [b["timestamp"] for b in blocks] + [t["timestamp"] for t in triggers]
        )
        after_frames = [
            f
            for f in parsed[1]["frames"]
            if f["offset"] >= 0 and f["timestamp"] > blocks[-1]["timestamp"]
        ]
        end = after_frames[0]["timestamp"] if after_frames else spans[1][-1][2]
        transfer.update(
            {
                "first_block": blocks[0],
                "last_block": blocks[-1],
                "first_radar_normal_frame_after_transfer": after_frames[0]
                if after_frames
                else None,
                "control_window_timestamp_start": start,
                "control_window_timestamp_end": end,
                "standalone_control_candidates": {
                    str(ch): controls(streams[ch], spans[ch], parsed[ch], start, end)
                    for ch in streams
                },
                "readiness_phase_controls_before_first_block": {
                    str(ch): controls(
                        streams[ch],
                        spans[ch],
                        parsed[ch],
                        start,
                        blocks[0]["timestamp"],
                    )
                    for ch in streams
                },
                "termination_phase_controls_after_last_valid_block": {
                    str(ch): controls(
                        streams[ch], spans[ch], parsed[ch], blocks[-1]["timestamp"], end
                    )
                    for ch in streams
                },
            }
        )
    result["firmware_transfer"] = transfer
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--corpus-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = {
        "schema_version": 1,
        "limits": [
            "Historical recorded bytes only; no device interaction or upgrade execution.",
            "No bytes are invented, stitched across gaps, or exported as a recovered image.",
            "A valid packet proves recorded transport integrity, not command semantics or firmware authenticity.",
            "Timestamps identify read chunks; sub-chunk byte timing and physical baud are unknown.",
            "Candidate CRC failures can be false starts in unparsed bytes and do not measure link packet loss.",
            "Control candidates exclude validated packets; corrupt or unparsed data can imitate control bytes.",
            "Modulo sequence gaps show discontinuity between valid blocks, not an exact loss count or cause.",
            "One recorded successful-looking exchange does not establish retry, abort, rollback or power-failure behavior.",
        ],
        "capture": audit(args.capture),
    }
    if args.corpus_dir:
        corpus = []
        totals = Counter()
        for path in sorted(args.corpus_dir.glob("*.txt")):
            metadata, streams, spans = read_capture(path)
            parsed = {ch: scan(data, spans[ch]) for ch, data in streams.items()}
            summary = summarize(metadata, parsed)
            corpus.append(summary)
            for attribute, counts in summary["attributes"].items():
                totals[attribute] += sum(counts.values())
        report["corpus"] = {
            "files": corpus,
            "file_count": len(corpus),
            "files_with_no_accepted_capture_bytes": [
                x["source"]["path"]
                for x in corpus
                if sum(x["source"]["byte_counts"].values()) == 0
            ],
            "validated_normal_frames": sum(
                x["validated_normal_frames"] for x in corpus
            ),
            "observed_attribute_count": len(totals),
            "attribute_frame_counts": dict(sorted(totals.items())),
        }
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
