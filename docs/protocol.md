# Radar protocol

This document describes the boundary between the ESP32 host and the retained radar firmware. It distinguishes recovered wire behavior from behavior implemented by this project. See [architecture](architecture.md), [radar integration](radar.md), [installation](install.md), [Home Assistant](home-assistant.md), and the [research notes](research.md).

## Framing and typed values

The stock host configures UART at a nominal 921600 baud. Physical timing and clock-divider behavior must be checked separately for each implementation.

| Offset | Field |
| --- | --- |
| 0–2 | Sync/version: `55 00 01` |
| 3 | Sequence byte |
| 4 | Operation |
| 5–6 | Payload length N, unsigned big-endian |
| 7 | Header checksum: negative sum of bytes 0–6, modulo 256 |
| 8–8+N−1 | Payload |
| 8+N–9+N | CRC16/MODBUS, low byte first |

Total length is N+10. CRC covers the complete header, including its checksum, and payload; reflected polynomial 0xA001, initial 0xFFFF. The stock host accepts payloads up to 2048 bytes. Frame integrity does not validate nested lengths.

| Operation | Payload and role |
| --- | --- |
| 1 | Two-byte attribute ID only; query in either direction |
| 2 | Typed attribute write |
| 3 | Acknowledgment/status |
| 4 | Typed response or incoming value |
| 5 | Unsolicited typed report on established producer paths |

Typed payloads start with `attribute:u16be, tag:u8`.

| Tag | Value encoding |
| --- | --- |
| 0 | One-byte scalar |
| 1 | Two-byte scalar, big-endian |
| 2 | Four-byte bit pattern, big-endian; signedness belongs to the consumer |
| 3 | No value in the host serializer; rejected by the inspected main-radar typed parser |
| 4 | One-byte Boolean; stock parsing normalizes nonzero to 1 |
| 5, 6 | `length:u16be`, then unmodified bytes; no implicit string encoding |

Tag 7 is a host-table wildcard, not an established wire encoding. Implement strict tag-specific lengths and container bounds: stock parsers have incomplete checks that should not be reproduced.

Normal status ACKs carry `attribute:u16be, tag 0, status:u8`; zero indicates the inspected success convention. A VOID ACK is not equivalent. Host replies can echo a request sequence, but radar responses do not universally do so. Sequence alone cannot identify every transaction; duplicate/retry semantics are incomplete. Logger-only unsupported branches may still reach success handling, so an ACK proves neither feature support nor persistence.

## Important attributes

IDs below are hexadecimal. Types describe established reports or canonical constructions, not proof that the stock setter rejects every alternative tag.

| ID | Purpose | Important boundary |
| --- | --- | --- |
| 0101, 0102 | Identity/version queries; 0102 also reports heartbeat/version | Version byte is not a unique complete firmware identity |
| 0103 | Motion/event code | Multiple codes; not a general occupancy Boolean |
| 0104 | Room presence; query returns op4/tag 0, changes report op5 | Preferred native room state |
| 0105 | Monitoring mode | Separate from 0116; human enum incomplete |
| 0106 | Proximity setting | Setter stores3 − input; no established safe arbitrary range |
| 0111 | Global sensitivity | Mode-dependent constraints and DSP effects |
| 0112 | Target-report enable | Value1 enables the recovered report path; no getter established |
| 0113 | Background-learning action | Input value ignored; completion is0113/op5/tag 4/true |
| 0114 | Native zone mask | Tag 6 body: zone byte plus40 mask bytes |
| 0115 | Packed native-zone event | Tag 1: zone ID followed by an event byte |
| 0116 | Operating/scene mode | Persistent transition can reset radar; query can mutate runtime mode |
| 0117 | Target snapshot | Op5/tag 6; format below |
| 0120, 0143 | Host-supplied tilt/installation state | Reverse queries require real calibrated sensor values; 0143 is not a harmless radar read probe |
| 0122 | Coordinate reversal | Numeric/physical enum incomplete |
| 0127 | Radar update trigger | Leads to a separate raw transfer and destructive flash operations |
| 0128 | Radar temperature query/response | Tag 1; physical interpretation incomplete |
| 0142 | Native-zone occupancy | Op5/tag 1: zone ID then 0/1 state; no initial snapshot getter established |
| 0149 | Automatic-edge result | Op5/tag 6, 40-byte candidate mask |
| 0150 | Automatic-edge action | False-valued input is not a cancellation command |
| 0151, 0152 | Per-zone sensitivity/type | Canonical tag 1: zone in high byte, setting in low byte |
| 0153 | Selected close/away events | Wire low byte 0 disables this event pair; nonzero enables it; occupancy remains active |
| 0160 | False-target deletion action | Distinct from deleting a zone; not a routine cleanup policy |
| 0170 | Wall/corner selector | Changes classifier bounds; physical labels incomplete |

Fall, sleep, counting and diagnostic families have additional mode-dependent attributes. A dispatch entry or reference enum alone is insufficient to expose them as supported controls.

## Zones, overlap and persistence

A raw mask is20 rows × 16 columns = 40 bytes. Cell index is `16*row+column`; byte `index>>3`, bit `7-(index&7)`. This storage layout does not establish meters, mounting orientation or a floor-plan origin. The native classifier uses half-unit cells with strict bounds that vary by mounting selector.

Native 0114 accepts configurable IDs 1–30. A zero mask deletes that zone. **ID 0 clears all native zones and special maps.** Equal geometry is a no-op. Creating/deleting a zone resets sensitivity/type/close-away state to 3/0/0; a changed nonempty-to-nonempty edit preserves these properties and cached report state.

One eligible target may occupy multiple overlapping zones. Upstream sensitivity/type selection instead uses the first matching active zone. Editing and boot reconstruction can change list order, so overlap does not provide a stable priority setting.

Raw masks and parameters persist independently:

| Logical radar storage offset | Record body |
| --- | --- |
| 0x31000 | General settings, active flags, parameters and learned background: 3000 bytes |
| 0x32000 | All 32 raw mask slots: 1280 bytes; this does not expand the configurable ID range |
| 0x33000 | Proximity/edge map: 40 bytes |
| 0x34000 | Entry/exit labeling map: 40 bytes |
| 0x35000 | Interference map: 40 bytes |
| 0x37000 | Fall blind-zone map: 40 bytes |

Records include a two-byte checksum and transfers round to eight-byte units. Deferred countdowns run on tracker-processing passes, not seconds. Separate records have separate countdowns; no atomic configuration transaction is established. A final retry may return without readback, and invalid-map checksum paths can continue into restoration. An ACK or elapsed delay cannot certify durability.

Native zone events are authoritative for native occupancy. Start unknown after reconnect until genuine state arrives; silence is not vacancy. Reading, editing and restoring an existing installation requires genuine current geometry, parameters and special maps plus a validated restore path. ESP32 app backup alone does not preserve radar settings. Host-only aliases and display regions are separate from native writes.

## Target records and freshness

0117's container body is `count:u8` followed by count records of 14 bytes. Its declared body length must equal `1+14*count`. An empty list is valid. Observed counts do not establish a maximum hardware capacity.

| Record bytes | Interpretation |
| --- | --- |
| 0 | Track identifier |
| 1–2, 3–4 | Signed big-endian coordinates × 100 in native units |
| 5–6 | Zero in the inspected constructor |
| 7–8 | Big-endian planar model speed × 100; physical distance/time units unproved |
| 9–10 | Big-endian scaled internal SNR statistic; not established dB |
| 11 | Tracker/status byte; influences native eligibility |
| 12 | Temporally voted pose class 1/2 when status 0, otherwise 255; class 2 is also a default |
| 13 | First matching native raw-zone ID at the serialized position ; 0 means none |

Human pose labels and confidence percentages are unproved. The reported zone ID is not exclusive occupancy and does not replace0142. Native eligibility filtering occurs after snapshot serialization, so displaying every reported track cannot exactly reconstruct native occupancy.

Stable-count positions are normally serialized once per five report-processing passes; a count change can report sooner. Native zone processing runs between snapshots. This is not a fixed-frequency guarantee or a measurement of physical motion-to-light latency.

Tracks may retain held positions and survive missed or rejected updates. Counter/history/geometry rules govern cleanup, including a qualified nearby-track veto without an independent elapsed-time ceiling in that branch. An unmoving reported target is not automatically false. Missing/stale data should become unknown or disappear from the live view, rather than become fabricated vacancy. Fresh packet receipt does not prove a fresh physical observation for each target.

Learning and automatic-edge actions reset tracking state and use processing-pass countdowns. Background learning emits completion after 80 eligible passes once armed; automatic-edge runs for 181 eligible passes and returns 0149. Actions can share scratch state; retries, cancellation and interruption recovery are not established. Completion reports precede deferred persistence.

## Radar update boundary

The researched stock process stages a bundle, sends 0127, accepts its ACK, resets the radar and hands UART reception to raw XMODEM. The installed first-stage bootloader owns the actual receiver; staged bootloaders are different artifacts.

The inspected receiver supports 128-byte SOH and 1024-byte STX packets, sequence/complement checks and CRC16-XMODEM (polynomial 0x1021, initial0; CRC high byte first). It can fall back to checksum mode. Data is programmed sequentially into a fixed selected bank, under a 0x280000-byte ceiling; normal transport CRC and update CRC are different algorithms.

**Bank erasure happens before readiness `C`.** The normal update window is 0x2c0000–0x53ffff; an explicit backup-update branch instead targets 0x40000–0x2bffff, including factory applications. Boot-record state influences that choice. EOT is ACKed before the final buffered tail is programmed, and inspected flush calls do not propagate every writer result. The host sender also treats CAN as success in its finishing state.

Transport success is therefore insufficient update acceptance. Image validation, selected-bank identity, boot/version response, compatibility and independent recovery remain separate checks. This research is not a public updater implementation or a power-loss recovery guarantee. ESP32 installation/OTA is a separate boundary described in [installation](install.md).

## Project monitor extension

This is an added protocol, not a stock vendor command. It uses operation 1 with
attribute `0102` and a magic signature so unrelated queries follow the original
handler. Addresses are big-endian and each request handles at most 128 bytes.

```text
Request payload: 01 02 46 50 32 MODE 01 ADDRESS:u32be COUNT:u8 [DATA]
Response:        01 02 05 LENGTH:u16be
                 03 MODE STATUS ADDRESS:u32be COUNT:u8 [DATA]
```

`46 50 32` is ASCII `FP2`. Request version is 1; response protocol version is 3.
`MODE` is ASCII `M` (mapped memory read), `W` (aligned RAM write), `S` (SFDP read),
or `J` (JEDEC). Status zero means the bounded operation returned, not independent
hardware-success proof. Legacy `R` is rejected. Response sequence is not used as
an authentication or freshness guarantee; mode/address/count must correlate.

Reads permit RAM `00000000..00040000`, `08000000..08030000` and mapped QSPI
`c0000000..c0800000` (exclusive ends). The host further bounds QSPI by actual SFDP
capacity. Writes permit RAM only, require 8-byte alignment, are at most 32 bytes,
and exclude monitor code/active handler storage except its owned scratch region.
No arbitrary MMIO or flash-write command is present. See [radar tools](radar.md)
for installation and acquisition boundaries.
