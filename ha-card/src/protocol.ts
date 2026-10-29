import { translate, type Language } from "./localize.ts";
import type { RadarTarget } from "./types.ts";
export const SPECIAL_MAPS = [
  {
    attribute: 0x107,
    label: "Boundaries / exclusions",
    description: "Affects coordinate retention and target output.",
  },
  {
    attribute: 0x109,
    label: "Entrances/exits",
    description: "Affects zone state and nearby targets.",
  },
  {
    attribute: 0x110,
    label: "Interference sources",
    description: "May exclude matching targets from the tracker.",
  },
];
export const SCALAR_CONTROLS = [
  {
    attribute: 0x106,
    label: "Proximity · 0106",
    min: 0,
    max: 2,
    advanced: true,
  },
  {
    attribute: 0x111,
    label: "Sensitivity · 0111",
    min: 0,
    max: 3,
    advanced: true,
  },
  {
    attribute: 0x122,
    label: "Coordinate rotation · 0122",
    min: 0,
    max: 2,
    advanced: true,
  },
  {
    attribute: 0x170,
    label: "Installation angle · 0170",
    min: 0,
    max: 3,
    advanced: true,
  },
];
export const ZONE_TYPE_CODES = [
  "0",
  "1",
  "1.1",
  "1.2",
  "1.3",
  "1.4",
  "1.5",
  "1.6",
  "2",
  "2.1",
  "2.2",
  "2.3",
  "3",
  "3.1",
  "3.2",
  "3.3",
  "3.4",
  "3.5",
  "4",
  "4.1",
  "4.2",
  "4.3",
  "5",
  "5.1",
  "5.2",
  "5.3",
  "6",
  "6.1",
  "6.2",
  "7",
  "7.1",
  "7.2",
  "8",
  "8.1",
  "8.2",
  "9",
  "9.1",
  "9.2",
  "9.3",
  "3.6",
];
export function decodeMask(mask: string, language: Language = "en"): boolean[] {
  if (!/^[0-9a-f]{80}$/i.test(mask))
    throw new Error(translate("Expected 40-byte mask", language));
  return Array.from(
    { length: 320 },
    (_, i) =>
      !!(
        parseInt(mask.slice((i >> 3) * 2, (i >> 3) * 2 + 2), 16) &
        (128 >> (i % 8))
      ),
  );
}
export function encodeMask(
  bits: readonly boolean[],
  language: Language = "en",
): string {
  if (bits.length !== 320)
    throw new Error(translate("Expected 320 cells", language));
  return Array.from({ length: 40 }, (_, b) =>
    bits
      .slice(b * 8, b * 8 + 8)
      .reduce((n, v, i) => n + (v ? 128 >> i : 0), 0)
      .toString(16)
      .padStart(2, "0"),
  ).join("");
}
export function targetToGrid(
  target: Pick<RadarTarget, "a_hundredths" | "b_hundredths">,
) {
  return {
    column: (400 - target.a_hundredths) / 50,
    row: target.b_hundredths / 50,
  };
}
export function paintRectangle(
  mask: string,
  start: { column: number; row: number },
  end: { column: number; row: number },
  value: boolean,
): string {
  const bits = decodeMask(mask);
  for (
    let r = Math.max(0, Math.min(start.row, end.row));
    r <= Math.min(19, Math.max(start.row, end.row));
    r++
  )
    for (
      let c = Math.max(0, Math.min(start.column, end.column));
      c <= Math.min(15, Math.max(start.column, end.column));
      c++
    )
      bits[r * 16 + c] = value;
  return encodeMask(bits);
}
export function decodeTargets(
  payload: string,
  language: Language = "en",
): RadarTarget[] {
  if (!/^[0-9a-f]+$/i.test(payload) || payload.length % 2)
    throw new Error(translate("Malformed target payload", language));
  const bytes = Uint8Array.from(payload.match(/../g)!, (h) => parseInt(h, 16));
  if (
    bytes.length < 6 ||
    bytes.length > 2048 ||
    bytes[0] !== 1 ||
    bytes[1] !== 0x17 ||
    bytes[2] !== 6 ||
    ((bytes[3] << 8) | bytes[4]) !== bytes.length - 5 ||
    bytes.length !== 6 + bytes[5] * 14
  )
    throw new Error(translate("Malformed target report", language));
  const signed = (n: number) => (n > 32767 ? n - 65536 : n);
  return Array.from({ length: bytes[5] }, (_, i) => {
    const p = 6 + i * 14;
    return {
      id: bytes[p],
      a_hundredths: signed(bytes[p + 1] * 256 + bytes[p + 2]),
      b_hundredths: signed(bytes[p + 3] * 256 + bytes[p + 4]),
      flag_raw: bytes[p + 11],
      raw_hex: payload.slice(p * 2, (p + 14) * 2),
    };
  });
}

/** Native 0117 fields, without inferred physical units. Offsets are zero-based. */
export function decodeTargetMetadata(
  rawHex: string,
  language: Language = "en",
) {
  if (typeof rawHex !== "string" || !/^[0-9a-f]{28}$/i.test(rawHex))
    throw new Error(translate("Expected 14-byte target record", language));
  const b = Uint8Array.from(rawHex.match(/../g)!, (h) => parseInt(h, 16));
  const u16 = (offset: number) => (b[offset] << 8) | b[offset + 1];
  return {
    u16_at_5: u16(5),
    u16_at_7: u16(7),
    u16_at_9: u16(9),
    byte_11: b[11],
    byte_12: b[12],
    byte_13: b[13],
  };
}
