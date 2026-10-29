# Radar tools

The radar has its own processor and flash. This project keeps the vendor signal
processing and adds a small command handler for bounded memory reads, aligned
RAM writes, JEDEC and SFDP queries. It does not add arbitrary flash programming.

The reproducible path is:

```text
Own FP2 → ESP32 stock backup → extract supported radar bundle
                                      + compile monitor extension
                                      ↓
                               patched radar bundle
                                      ↓
FTDI → ESP32 ROM → temporary RAM bridge → vendor radar updater
                                      ↓
                              installed monitor → full radar dump
```

## Inputs and tools

First follow [board access and backup](install.md). Use your original 16 MiB
ESP32 backup. The supported radar bundle is identified by SHA-256
`d2ebea24b9e52014d50541a6e83646211b19f296f2381fdc9fb586c342a1dcb1`;
other versions stop before a package is produced. This is vendor-content identity,
not a required hash of another person's complete device backup.

Install GNU Arm Embedded tools (`arm-none-eabi-gcc`, `objcopy`, `objdump`, `nm`).
Set `ARM_PREFIX` if those commands use a different prefix. The ESP32 firmware
build installs the Xtensa toolchain used by the bridge; `XTENSA_TOOL_BIN` may
select its `bin` directory explicitly.

```sh
# No hardware access:
python3 tools/prepare_radar.py /path/to/stock.bin
python3 tools/build_bridge.py
python3 tools/research.py install
```

The first command compiles `firmware/radar_export`, verifies the original hook
and section layout, appends the TCMA section, preserves 64-byte member alignment,
and recomputes RPRC/MSTR CRC64 plus outer CRC32. It produces
`.tools/radar-image/monitor.bin` and receipts. Inputs are not modified.

The extension source is distributable; the combined result contains proprietary
vendor code. Keep generated bundles, dumps and private receipts out of Git.

## Install explicitly

**This writes persistent radar flash.** The updater erases before transfer, and
independent recovery after an interrupted update is not established. Keep stable
power throughout. ESP32 backup restoration alone does not restore the radar.
Do not treat the final transfer ACK as verified programming or immediate reset
permission; the sender includes the observed post-transfer wait.

Close serial monitors and other device clients. Connect FTDI TX/RX/GND and the
reset/bootstrap controls. Replace `PORT` with the local serial adapter.

```sh
uv run --with-requirements requirements-research.txt python tools/research.py install \
  --execute --accept-unproven-recovery --port PORT \
  --backup /path/to/stock.bin --output .tools/radar-install.json

# Separate verification after a successful install:
uv run --with-requirements requirements-research.txt python tools/research.py inspect \
  --execute --port PORT --backup /path/to/stock.bin \
  --output .tools/radar-inspect.json
```

The monitor prefix must match the locally built code before inspection/dumping.
The temporary bridge occupies bounded ESP32 IRAM/DRAM; it does not flash the ESP32.
Successful completion restores the bridge registers and resets the ESP32 to its
existing app. A failed radar install intentionally avoids a normal reset when
completion is uncertain. Review the private error receipt rather than blindly
repeating the write. Reset success is not proof that either application is healthy.

## Acquire radar flash

```sh
uv run --with-requirements requirements-research.txt python tools/research.py dump \
  --execute --port PORT --backup /path/to/stock.bin \
  --dump .tools/radar-flash.bin --output .tools/radar-dump.json
```

The client discovers actual capacity through JEDEC/SFDP, bounds mapped reads,
checks framing/CRC and echoed addresses, and records progress and a SHA-256.
An interrupted dump can resume with `--resume` and a **new** `--output` receipt;
retained prefix metadata and live anchors are checked before appending. Missing
bytes are never fabricated. Read retries do not imply safe retries of RAM writes
or interrupted programming.

This is a **post-monitor-install** dump, not a pristine pre-change radar backup.
Reads are sequential, not an atomic snapshot. The original ESP32 backup retains
the bundled vendor images but is not a complete backup of radar flash/settings.

## Continue research

`radar_memory_monitor.Monitor` exposes `read`, `write_ram`, `sfdp`, `jedec`,
`capacity` and `dump` over an existing bridge session. RAM writes are aligned and
bounded; MMIO and flash programming are absent. Prefer read-only inspection.
Patch layout, helper addresses and identity checks are specific to this vendor
build. Add a separately reviewed layout for a new version; never disable checks.

The portable package reproduces the monitor previously exercised on hardware.
The new public entrypoints have been checked offline; a fresh third-party
installation and interrupted-power recovery have not been certified.
