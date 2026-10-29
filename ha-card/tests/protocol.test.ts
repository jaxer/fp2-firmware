import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  decodeMask,
  encodeMask,
  paintRectangle,
  decodeTargets,
  targetToGrid,
  ZONE_TYPE_CODES,
  decodeTargetMetadata,
} from "../src/protocol.ts";
test("native MSB-first mask and bounded rectangle", () => {
  const mask = "80" + "00".repeat(39);
  assert.equal(decodeMask(mask)[0], true);
  assert.equal(decodeMask(mask)[1], false);
  assert.equal(encodeMask(decodeMask(mask)), mask);
  const rectangle = paintRectangle(
    "00".repeat(40),
    { row: 0, column: 0 },
    { row: 1, column: 1 },
    true,
  );
  assert.equal(rectangle.slice(0, 8), "c000c000");
  assert.throws(() => decodeMask("bad"));
  assert.equal(ZONE_TYPE_CODES.length, 40);
});
test("isolated target event decodes exactly", () => {
  const receipt = JSON.parse(
    readFileSync(
      new URL("../../tests/fixtures/targets.json", import.meta.url),
      "utf8",
    ),
  );
  for (const key of ["first_event", "last_event"])
    assert.deepEqual(
      decodeTargets(receipt[key].event.data.payload_hex),
      receipt[key].decoded_targets,
    );
  assert.deepEqual(targetToGrid({ a_hundredths: 380, b_hundredths: 108 }), {
    column: 0.4,
    row: 2.16,
  });
  assert.throws(() => decodeTargets("011706000f00"));
});
test("target decoder rejects otherwise consistent oversized reports", () => {
  const count = 146,
    declared = 1 + 14 * count;
  const payload =
    "011706" +
    declared.toString(16).padStart(4, "0") +
    count.toString(16) +
    "00".repeat(count * 14);
  assert.throws(() => decodeTargets(payload), /Malformed/);
});

test("isolated target metadata preserves native offsets without assigning units", () => {
  const receipt = JSON.parse(
    readFileSync(
      new URL("../../tests/fixtures/targets.json", import.meta.url),
      "utf8",
    ),
  );
  for (const key of ["first_event", "last_event"]) {
    const raw = receipt[key].decoded_targets[0].raw_hex;
    assert.deepEqual(decodeTargetMetadata(raw), {
      u16_at_5: 0,
      u16_at_7: 0,
      u16_at_9: 0,
      byte_11: 0,
      byte_12: 2,
      byte_13: 5,
    });
    assert.deepEqual(
      decodeTargetMetadata(raw.toUpperCase()),
      decodeTargetMetadata(raw),
    );
  }
  for (const raw of ["", "00".repeat(13), "00".repeat(15), "zz".repeat(14)])
    assert.throws(() => decodeTargetMetadata(raw), /14-byte/);
});

test("target metadata u16 words are big endian and byte fields stay separate", () => {
  assert.deepEqual(decodeTargetMetadata("0000000000010203040506070809"), {
    u16_at_5: 0x0102,
    u16_at_7: 0x0304,
    u16_at_9: 0x0506,
    byte_11: 7,
    byte_12: 8,
    byte_13: 9,
  });
});
