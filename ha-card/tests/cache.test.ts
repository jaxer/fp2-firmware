import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { validateSnapshot, saveSnapshot } from "../src/cache.ts";
import { Fp2Client } from "../src/client.ts";
function recorded() {
  const rows = JSON.parse(
    readFileSync(
      new URL("../../tests/fixtures/configuration.json", import.meta.url),
      "utf8",
    ),
  ).results;
  const x: any = {
    version: 1,
    node: "fp2",
    entity_prefix: "fp2",
    savedAt: 1793228505998,
    zones: {},
    specialMaps: {},
    scalars: {},
  };
  for (const { observation: o } of rows)
    x[
      o.kind === "zone" ? "zones" : o.kind === "map" ? "specialMaps" : "scalars"
    ][o.id ?? o.attribute] = { ...o, fresh: true, seenAt: 1793228505998 };
  return x;
}
test("shared snapshot validates complete isolated records, rejects wrong device/corruption, never restores freshness", () => {
  const x = recorded();
  const v = validateSnapshot(x, x.node, x.entity_prefix)!;
  assert.equal(Object.keys(v.zones).length, 30);
  assert.equal(v.zones[1].fresh, false);
  assert.equal(x.zones[1].fresh, true);
  assert.equal(validateSnapshot(x, "different", x.entity_prefix), null);
  delete x.zones[30];
  assert.equal(validateSnapshot(x, x.node, x.entity_prefix), null);
  const bad = recorded();
  bad.specialMaps[263].mask = "bad";
  assert.equal(validateSnapshot(bad, bad.node, bad.entity_prefix), null);
});
test("opening either card uses HA cache and makes zero radar service calls", async () => {
  for (const read_only of [false, true]) {
    let services = 0;
    const client = new Fp2Client({ read_only }, () => {});
    const hass: any = {
      states: {},
      connection: { subscribeEvents: async () => () => {} },
      callWS: async () => ({ fp2_configuration_cache: { fp2: recorded() } }),
      callService: async () => {
        services++;
      },
    };
    try {
      client.attach(hass);
      await new Promise((r) => setTimeout(r, 0));
      assert.equal(Object.keys(client.state.zones).length, 30);
      assert.equal(client.state.zones[1].fresh, false);
      assert.equal(services, 0);
      if (read_only) await assert.rejects(client.readZone(1), /read-only/);
      assert.equal(services, 0);
    } finally {
      client.dispose();
    }
  }
});
test("cache update preserves current dashboard views and other devices", async () => {
  const before: any = {
    title: "existing",
    views: [{ path: "control", cards: [{ type: "custom:fp2-local-card" }] }],
    fp2_configuration_cache: { other: { untouched: true } },
  };
  let saved: any;
  await saveSnapshot(
    {
      callWS: async (message: any) => {
        if (message.type === "lovelace/config") return structuredClone(before);
        saved = message;
      },
    } as any,
    "fp2-local",
    recorded(),
  );
  assert.deepEqual(saved.config.views, before.views);
  assert.deepEqual(saved.config.fp2_configuration_cache.other, {
    untouched: true,
  });
  assert.equal(saved.config.fp2_configuration_cache["fp2"].zones[1].id, 1);
  assert.equal(saved.url_path, "fp2-local");
});
test("shared snapshot change updates an open read-only card without radar reads", async () => {
  let saved = recorded(),
    event: (e: any) => void = () => {};
  let services = 0;
  const hass: any = {
    states: {},
    connection: {
      subscribeEvents: async (cb: any, type: string) => {
        if (type === "lovelace_updated") event = cb;
        return () => {};
      },
    },
    callWS: async () => ({ fp2_configuration_cache: { fp2: saved } }),
    callService: async () => {
      services++;
    },
  };
  const c = new Fp2Client({ read_only: true }, () => {});
  try {
    c.attach(hass);
    await new Promise((r) => setTimeout(r, 0));
    const original = c.state.zones[10].mask;
    saved = structuredClone(saved);
    saved.zones[10].mask = saved.zones[1].mask;
    saved.savedAt++;
    event({ data: { url_path: "fp2-cache" } });
    await new Promise((r) => setTimeout(r, 0));
    assert.notEqual(c.state.zones[10].mask, original);
    assert.equal(c.state.zones[10].mask, saved.zones[1].mask);
    assert.equal(c.state.zones[10].fresh, false);
    assert.equal(services, 0);
  } finally {
    c.dispose();
  }
});
