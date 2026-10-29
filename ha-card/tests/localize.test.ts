import test from "node:test";
import assert from "node:assert/strict";
import {
  russian,
  resolveLanguage,
  translate,
  formatDate,
} from "../src/localize.ts";
import { Fp2Client } from "../src/client.ts";
import { decodeMask, SPECIAL_MAPS, SCALAR_CONTROLS } from "../src/protocol.ts";
import type { HomeAssistant } from "../src/types.ts";

function hass(language?: string): HomeAssistant {
  return {
    language,
    states: {},
    connection: { subscribeEvents: async () => () => {} },
    callWS: async () => ({}),
    callService: async () => {
      throw new Error("Unexpected radar mutation");
    },
  };
}

test("language selection follows HA, handles region tags, and uses English for unsupported languages", () => {
  assert.equal(resolveLanguage(), "en");
  assert.equal(resolveLanguage({}, hass("ru")), "ru");
  assert.equal(resolveLanguage({}, hass("RU-ru")), "ru");
  assert.equal(resolveLanguage({}, hass("ru_RU")), "ru");
  assert.equal(
    resolveLanguage({}, { ...hass(), locale: { language: "ru-RU" } }),
    "ru",
  );
  assert.equal(
    resolveLanguage({}, { ...hass("en-GB"), locale: { language: "ru" } }),
    "en",
  );
  assert.equal(resolveLanguage({}, hass("et")), "en");
  assert.equal(resolveLanguage({ language: "en" }, hass("ru")), "en");
  assert.equal(resolveLanguage({ language: "ru" }, hass("en")), "ru");
  assert.equal(resolveLanguage({ language: "de" }, hass("ru")), "en");
  assert.equal(resolveLanguage({ language: "" }, hass("ru")), "ru");
});

test("catalog preserves placeholders, interpolates zero values, and falls back safely for unknown messages", () => {
  const placeholders = (text: string) =>
    [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
  for (const [en, ru] of Object.entries(russian)) {
    assert.deepEqual(placeholders(ru), placeholders(en), en);
    assert.equal(translate(en), en);
    assert.equal(translate(en, "ru"), ru);
  }
  assert.equal(
    translate("{occupied} / {total} zones occupied", "ru", {
      occupied: 0,
      total: 30,
    }),
    "0 / 30 областей занято",
  );
  assert.equal(translate("New label", "ru"), "New label");
  assert.equal(translate("constructor", "ru"), "constructor");
  assert.equal(translate("Zone {id}", "ru"), "Зона {id}");
  assert.equal(translate("Zone {id}", "ru", { id: "{total}" }), "Зона {total}");
  assert.equal(translate("Clear", "ru"), "Очистить");
  assert.equal(translate("Unoccupied", "ru"), "Свободно");
});

test("protocol labels and validation localize without altering protocol attributes", () => {
  assert.deepEqual(
    SPECIAL_MAPS.map((x) => x.attribute),
    [0x107, 0x109, 0x110],
  );
  for (const item of [...SPECIAL_MAPS, ...SCALAR_CONTROLS]) {
    assert.ok(!/[А-Яа-я]/.test(item.label));
    assert.notEqual(translate(item.label, "ru"), item.label);
  }
  assert.throws(() => decodeMask("bad"), /Expected 40-byte mask/);
  assert.throws(() => decodeMask("bad", "ru"), /Ожидается маска из 40 байт/);
});

test("client switches generated names, retained cache messages and errors while preserving custom names and device status", async () => {
  const ha = hass("en");
  ha.states["binary_sensor.fp2_native_zone_2_occupancy"] = {
    state: "off",
    attributes: { friendly_name: "Рабочий стол" },
    last_updated: "now",
  };
  ha.states["sensor.fp2_learning_status"] = {
    state: "native status unchanged",
    attributes: {},
    last_updated: "now",
  };
  const client = new Fp2Client({ read_only: true }, () => {});
  try {
    client.attach(ha);
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(client.state.zoneNames[1], "Zone 1");
    assert.equal(
      client.state.cacheError,
      "No saved configuration. Read it from the radar.",
    );
    await assert.rejects(client.readZone(1), /read-only/);
    assert.equal(client.state.notice?.message, "This card is read-only");
    ha.language = "ru-RU";
    client.attach(ha);
    assert.equal(client.state.zoneNames[1], "Зона 1");
    assert.equal(client.state.zoneNames[2], "Рабочий стол");
    assert.equal(client.state.learningStatus, "native status unchanged");
    assert.equal(
      client.state.cacheError,
      "Нет сохранённой конфигурации. Прочитайте её с радара.",
    );
    assert.equal(client.state.notice?.message, "Карточка только для просмотра");
    await assert.rejects(client.readZone(1), /просмотра/);
    ha.language = "et";
    client.attach(ha);
    assert.equal(client.state.zoneNames[1], "Zone 1");
    assert.equal(client.state.notice?.message, "This card is read-only");
    assert.equal(
      client.state.cacheError,
      "No saved configuration. Read it from the radar.",
    );
  } finally {
    client.dispose();
  }
});

test("client language override wins over HA and action/entity identifiers stay unchanged", async () => {
  const ha = hass("en");
  let command: any;
  ha.callWS = async (message) => {
    command = message;
    return {};
  };
  const client = new Fp2Client({ language: "ru" }, () => {});
  try {
    client.attach(ha);
    assert.equal(client.state.zoneNames[1], "Зона 1");
    assert.throws(
      () => client.saveScalar(0x111, 99),
      /Неподдерживаемое значение/,
    );
    await client.renameZone(1, "My custom name");
    assert.equal(command.type, "config/entity_registry/update");
    assert.equal(
      command.entity_id,
      "binary_sensor.fp2_native_zone_1_occupancy",
    );
    assert.equal(command.name, "My custom name");
  } finally {
    client.dispose();
  }
});

test("dates use the selected display language", () => {
  const timestamp = 1793228505998;
  assert.equal(
    formatDate(timestamp, "en"),
    new Date(timestamp).toLocaleString("en"),
  );
  assert.equal(
    formatDate(timestamp, "ru"),
    new Date(timestamp).toLocaleString("ru"),
  );
  assert.equal(
    formatDate(timestamp, "ru", true),
    new Date(timestamp).toLocaleTimeString("ru"),
  );
});
