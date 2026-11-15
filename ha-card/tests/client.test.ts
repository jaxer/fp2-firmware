import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { Fp2Client } from "../src/client.ts";
import type { HomeAssistant } from "../src/types.ts";
const prefix = "sensor.fp2_";
test("all native readback grammars match the 37-observation isolated fixture", async () => {
  const rows = JSON.parse(
    readFileSync(
      new URL("../../tests/fixtures/configuration.json", import.meta.url),
      "utf8",
    ),
  ).results;
  const hass: HomeAssistant = {
    states: {},
    connection: { subscribeEvents: async () => () => {} },
    callWS: async (m: any) => {
      if (m.type === "call_service") {
        await hass.callService(m.domain, m.service, m.service_data);
        return {
          response: {
            configuration: hass.states[prefix + "radar_configuration"].state,
          },
        };
      }
      return {};
    },
    callService: async (_domain, service, data) => {
      assert.ok(service.endsWith("read_configuration"));
      const row = rows.find(
        (r: any) =>
          r.attribute === data.attribute_id && r.zone === data.zone_id,
      );
      assert.ok(row, "fixture observation exists");
      hass.states[prefix + "radar_configuration"] = {
        state: JSON.stringify(row.observation),
        attributes: {},
        last_updated: new Date().toISOString(),
      };
    },
  };
  const client = new Fp2Client({}, () => {});
  try {
    client.attach(hass);
    await client.refreshAll();
    await client.readZone(1);
    assert.equal(Object.keys(client.state.zones).length, 30);
    assert.equal(Object.keys(client.state.specialMaps).length, 3);
    assert.equal(Object.keys(client.state.scalars).length, 4);
    for (const row of rows) {
      const actual = row.observation;
      const result =
        actual.kind === "zone"
          ? client.state.zones[actual.id]
          : actual.kind === "map"
            ? client.state.specialMaps[actual.attribute]
            : client.state.scalars[actual.attribute];
      for (const [key, value] of Object.entries(actual))
        assert.deepEqual((result as any)[key], value);
    }
  } finally {
    client.dispose();
  }
});
function fixture() {
  let marker = 1;
  const calls: { service: string; data: Record<string, unknown> }[] = [];
  let callback: (e: any) => void = () => {};
  const hass: HomeAssistant = {
    states: {},
    connection: {
      subscribeEvents: async (cb, type) => {
        if (type === "esphome.fp2_targets") callback = cb;
        return () => {};
      },
    },
    callWS: async (m: any) => {
      if (m.type === "call_service") {
        await hass.callService(m.domain, m.service, m.service_data);
        return {
          response: {
            configuration: hass.states[prefix + "radar_configuration"].state,
          },
        };
      }
      return {};
    },
    callService: async (_domain, service, data) => {
      calls.push({ service, data });
      if (service.endsWith("read_configuration")) {
        const attribute = Number(data.attribute_id),
          id = Number(data.zone_id);
        const body = id
          ? {
              kind: "zone",
              id,
              active_raw: 1,
              sensitivity: 1,
              type: 0,
              close_away_raw: 0,
              mask: "80" + "00".repeat(39),
            }
          : [263, 265, 272].includes(attribute)
            ? { kind: "map", attribute, mask: "00".repeat(40) }
            : {
                kind: "scalar",
                attribute,
                raw: 1,
                wire: attribute === 262 ? 2 : 1,
              };
        hass.states[prefix + "radar_configuration"] = {
          state: JSON.stringify({
            ...body,
            source: "radar_ram",
            observed_ms: ++marker,
          }),
          attributes: {},
          last_updated: new Date().toISOString(),
        };
      } else
        hass.states[prefix + "configuration_status"] = {
          state: "acknowledged (not verified/saved)",
          attributes: {},
          last_updated: String(++marker),
        };
    },
  };
  return { hass, calls, event: (e: any) => callback(e) };
}
test("serial refresh reads all 37 native sections and write requires matching readback", async () => {
  const f = fixture();
  const client = new Fp2Client({}, () => {});
  try {
    client.attach(f.hass);
    void client.refreshAll().catch(() => {});
    await client.readZone(1);
    assert.equal(f.calls.length, 38);
    assert.equal(Object.keys(client.state.zones).length, 30);
    assert.equal(Object.keys(client.state.scalars).length, 4);
    assert.equal(Object.keys(client.state.specialMaps).length, 3);
    await client.saveZone(1, "80" + "00".repeat(39));
    assert.equal(
      f.calls.filter((c) => c.service === "fp2_fp2_zone_mask").length,
      1,
    );
    assert.equal(f.calls.at(-1)?.service, "fp2_fp2_read_configuration");
    await assert.rejects(client.saveScalar(273, 3), /does not match/);
    assert.equal(
      f.calls.filter((c) => c.service.endsWith("_scalar")).length,
      1,
    );
    assert.throws(() => client.saveZone(1, "00".repeat(40)));
    assert.throws(() => client.saveScalar(273, 4));
  } finally {
    client.dispose();
  }
});
test("cached sensor is never silently ingested as fresh; wrong-source events ignored", async () => {
  const f = fixture();
  f.hass.states[prefix + "radar_configuration"] = {
    state: JSON.stringify({
      kind: "zone",
      id: 30,
      active_raw: 1,
      sensitivity: 1,
      type: 0,
      close_away_raw: 0,
      mask: "ff".repeat(40),
      source: "radar_ram",
      observed_ms: 1,
    }),
    attributes: {},
    last_updated: "2020-01-01",
  };
  const client = new Fp2Client({}, () => {});
  try {
    client.attach(f.hass);
    void client.refreshAll().catch(() => {});
    assert.equal(client.state.zones[30], undefined);
    f.event({
      data: {
        node: "other",
        source: "radar_uart",
        payload_hex: "011706000100",
        count: "0",
      },
    });
    assert.equal(client.state.targets, null);
    await client.readZone(1);
    assert.equal(client.state.zones[30].mask, "80" + "00".repeat(39));
  } finally {
    client.dispose();
  }
});
test("unknown ACK outcome verifies RAM without retrying mutation", async () => {
  const f = fixture(),
    original = f.hass.callService;
  f.hass.callService = async (d, s, data) => {
    await original(d, s, data);
    if (s.endsWith("_scalar"))
      f.hass.states[prefix + "configuration_status"].state =
        "unconfirmed (unknown outcome)";
  };
  const client = new Fp2Client({}, () => {});
  try {
    client.attach(f.hass);
    void client.refreshAll().catch(() => {});
    await client.readZone(1);
    await client.saveScalar(273, 1);
    assert.equal(
      f.calls.filter((c) => c.service.endsWith("_scalar")).length,
      1,
    );
    assert.equal(client.state.notice?.kind, "success");
  } finally {
    client.dispose();
  }
});
test("availability uses native health/occupancy, independent of absent or future-dated counters", async () => {
  const f = fixture();
  let previous: unknown,
    distinct = true;
  const client = new Fp2Client({}, (state) => {
    if (previous === state) distinct = false;
    previous = state;
  });
  try {
    f.hass.states["binary_sensor.fp2_radar_traffic"] = {
      state: "on",
      attributes: {},
      last_updated: "2020-01-01",
    };
    f.hass.states["binary_sensor.fp2_room_presence"] = {
      state: "off",
      attributes: {},
      last_updated: "2020-01-01",
    };
    client.attach(f.hass);
    assert.equal(client.state.deviceFresh, true);
    f.hass.states[prefix + "valid_radar_frames"] = {
      state: "1",
      attributes: {},
      last_updated: new Date(Date.now() + 60000).toISOString(),
    };
    client.attach(f.hass);
    assert.equal(client.state.deviceFresh, true);
    f.hass.connection.connected = false;
    client.attach(f.hass);
    assert.equal(client.state.deviceFresh, false);
    f.hass.connection.connected = true;
    f.hass.states["binary_sensor.fp2_radar_traffic"].state = "off";
    client.attach(f.hass);
    assert.equal(client.state.deviceFresh, false);
    assert.equal(distinct, true);
  } finally {
    client.dispose();
  }
});
test("unresolved learning prevents background queries and explicit reads", async () => {
  const f = fixture();
  f.hass.states[prefix + "learning_status"] = {
    state: "auto edge: outcome unknown (no retry/cancel); ack=unconfirmed",
    attributes: {},
    last_updated: "now",
  };
  const client = new Fp2Client({}, () => {});
  try {
    client.attach(f.hass);
    void client.refreshAll().catch(() => {});
    await assert.rejects(client.readZone(1), /Learning/);
    assert.equal(f.calls.length, 0);
  } finally {
    client.dispose();
  }
});
test("disposal prevents active read retry and queued commands", async () => {
  const f = fixture();
  let release!: () => void;
  const entered = new Promise<void>((resolve) => {
    const original = f.hass.callService;
    f.hass.callService = async (d, s, data) => {
      resolve();
      await new Promise<void>((r) => {
        release = r;
      });
      await original(d, s, data);
    };
  });
  const client = new Fp2Client({}, () => {});
  client.attach(f.hass);
  void client.refreshAll().catch(() => {});
  await entered;
  const queued = client.readZone(1);
  client.dispose();
  release();
  await assert.rejects(queued, /disposed/);
  assert.equal(f.calls.length, 1);
});
test("full-width scalar words survive readback without narrowing", async () => {
  const f = fixture(),
    original = f.hass.callService;
  f.hass.callService = async (d, s, data) => {
    await original(d, s, data);
    if (s.endsWith("read_configuration") && data.attribute_id === 273) {
      const entity = f.hass.states[prefix + "radar_configuration"];
      entity.state = JSON.stringify({
        ...JSON.parse(entity.state),
        raw: 16777219,
        wire: 16777219,
      });
    }
  };
  const client = new Fp2Client({}, () => {});
  try {
    client.attach(f.hass);
    void client.refreshAll().catch(() => {});
    await client.readZone(1);
    assert.equal(client.state.scalars[273].raw, 16777219);
    assert.equal(client.state.scalars[273].wire, 16777219);
  } finally {
    client.dispose();
  }
});
test("generated zone labels are localized while custom names and only valid candidates survive", async () => {
  const f = fixture();
  f.hass.states["binary_sensor.fp2_native_zone_1_occupancy"] = {
    state: "off",
    attributes: { friendly_name: "FP2 occupancy MVP Native zone 1 occupancy" },
    last_updated: "now",
  };
  f.hass.states["binary_sensor.fp2_native_zone_2_occupancy"] = {
    state: "off",
    attributes: { friendly_name: "Рабочий стол" },
    last_updated: "now",
  };
  f.hass.states[prefix + "auto_edge_candidate"] = {
    state: "learning: pending",
    attributes: {},
    last_updated: "now",
  };
  const client = new Fp2Client({}, () => {});
  try {
    client.attach(f.hass);
    void client.refreshAll().catch(() => {});
    assert.equal(client.state.zoneNames[1], "Zone 1");
    assert.equal(client.state.zoneNames[2], "Рабочий стол");
    assert.equal(client.state.autoEdgeCandidate, null);
    f.hass.states[prefix + "auto_edge_candidate"].state = "ab".repeat(40);
    client.attach(f.hass);
    void client.refreshAll().catch(() => {});
    assert.equal(client.state.autoEdgeCandidate, "ab".repeat(40));
    await client.readZone(1);
  } finally {
    client.dispose();
  }
});

test("opening the editor reads only the installation angle and never saves the cache", async () => {
  const calls: string[] = [];
  const hass: HomeAssistant = {
    states: {
      "binary_sensor.fp2_radar_traffic": { state: "on", attributes: {}, last_updated: "now" },
      "binary_sensor.fp2_room_presence": { state: "off", attributes: {}, last_updated: "now" },
    },
    connection: { subscribeEvents: async () => () => {} },
    callWS: async (m: any) => {
      calls.push(m.type === "call_service" ? `${m.service}:${m.service_data.attribute_id}` : m.type);
      if (m.type === "call_service")
        return {
          response: {
            configuration: JSON.stringify({ kind: "scalar", attribute: 0x170, raw: 2, wire: 2, source: "radar_ram", observed_ms: 1000 }),
          },
        };
      return {};
    },
    callService: async () => {
      throw new Error("unexpected service call");
    },
  };
  const client = new Fp2Client({}, () => {});
  try {
    client.attach(hass);
    await new Promise((resolve) => setTimeout(resolve, 300));
    assert.equal(client.state.scalars[0x170]?.wire, 2);
    assert.equal(client.state.scalars[0x170]?.fresh, true);
    assert.ok(calls.includes("fp2_fp2_read_configuration:368"));
    assert.ok(!calls.includes("lovelace/config/save"));
    assert.equal(client.state.notice, null);
  } finally {
    client.dispose();
  }
  const silent = new Fp2Client({}, () => {});
  const quiet: HomeAssistant = { ...hass, states: { "binary_sensor.fp2_radar_traffic": { state: "off", attributes: {}, last_updated: "now" } } };
  calls.length = 0;
  try {
    silent.attach(quiet);
    await new Promise((resolve) => setTimeout(resolve, 200));
    assert.ok(!calls.some((c) => c.includes("read_configuration")), "no radar read while the radar link is down");
  } finally {
    silent.dispose();
  }
});

test("a changed installation angle is saved to the cache so status cards follow it", async () => {
  const mask = "00".repeat(40);
  const snapshot = {
    version: 1,
    node: "fp2",
    entity_prefix: "fp2",
    savedAt: 1,
    zones: Object.fromEntries(
      Array.from({ length: 30 }, (_, i) => [i + 1, { kind: "zone", id: i + 1, mask, active_raw: 0, sensitivity: 1, type: 0, close_away_raw: 0, source: "radar_ram", observed_ms: 1 }]),
    ),
    specialMaps: Object.fromEntries([0x107, 0x109, 0x110].map((a) => [a, { kind: "map", attribute: a, mask, source: "radar_ram", observed_ms: 1 }])),
    scalars: Object.fromEntries([[0x106, 1], [0x111, 3], [0x122, 2], [0x170, 1]].map(([a, v]) => [a, { kind: "scalar", attribute: a, raw: v, wire: v, source: "radar_ram", observed_ms: 1 }])),
  };
  const saved: any[] = [];
  const hass: HomeAssistant = {
    states: { "binary_sensor.fp2_radar_traffic": { state: "on", attributes: {}, last_updated: "now" } },
    connection: { subscribeEvents: async () => () => {} },
    callWS: async (m: any) => {
      if (m.type === "lovelace/config") return { fp2_configuration_cache: { fp2: snapshot } };
      if (m.type === "lovelace/config/save") {
        saved.push(m.config);
        return {};
      }
      if (m.type === "call_service")
        return { response: { configuration: JSON.stringify({ kind: "scalar", attribute: 0x170, raw: 2, wire: 2, source: "radar_ram", observed_ms: 5000 }) } };
      return {};
    },
    callService: async () => {
      throw new Error("unexpected service call");
    },
  };
  const client = new Fp2Client({}, () => {});
  try {
    client.attach(hass);
    await new Promise((resolve) => setTimeout(resolve, 400));
    assert.equal(client.state.scalars[0x170]?.wire, 2);
    assert.equal(saved.length, 1, "cache saved once");
    assert.equal(saved[0].fp2_configuration_cache.fp2.scalars[0x170].wire, 2);
    assert.equal(saved[0].fp2_configuration_cache.fp2.scalars[0x106].wire, 1, "other cached values are kept");
  } finally {
    client.dispose();
  }
});
