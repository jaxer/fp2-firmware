import test from "node:test";
import assert from "node:assert/strict";
import { Fp2Client } from "../src/client.ts";
import type { HomeAssistant } from "../src/types.ts";

// Lit's shipped Node shim lets these isolated tests inspect real render output;
// no browser, HA session, network service or device is involved.
(globalThis as any).window = {};
const { Fp2LocalCard } = await import("../src/card.ts");
const { Fp2GlanceCard } = await import("../src/glance.ts");
const { Fp2LocalEditor } = await import("../src/editor.ts");
function rendered(value: any): string {
  if (value == null || typeof value === "symbol" || typeof value === "function")
    return "";
  if (Array.isArray(value)) return value.map(rendered).join("");
  if (typeof value === "object" && value.strings)
    return value.strings
      .map((s: string, i: number) => s + rendered(value.values[i]))
      .join("");
  return typeof value === "object" ? "" : String(value);
}
function hass(language: string): HomeAssistant {
  return {
    language,
    states: {},
    connection: { subscribeEvents: async () => () => {} },
    callWS: async () => ({}),
    callService: async () => {
      throw new Error("Unexpected mutation");
    },
  };
}
function state() {
  const client = new Fp2Client({}, () => {});
  client.dispose();
  return { ...client.state, deviceFresh: true, room: "off", illuminance: "42" };
}

test("main card renders English and Russian labels while tab identity survives a language change", () => {
  const card = new Fp2LocalCard();
  card.setConfig({});
  card.hass = hass("en");
  (card as any).state = state();
  let text = rendered(card.render());
  assert.match(text, /Presence map/);
  assert.match(text, /Unoccupied/);
  assert.match(text, /42 lx/);
  assert.doesNotMatch(text, /[А-Яа-яЁё]/);
  (card as any).tab = "settings";
  text = rendered(card.render());
  assert.match(text, /Boundaries \/ exclusions/);
  assert.match(text, /Proximity · 0106/);
  card.hass = hass("ru");
  text = rendered(card.render());
  assert.equal((card as any).tab, "settings");
  assert.match(text, /Служебные карты/);
  assert.match(text, /Границы \/ исключения/);
  assert.match(text, /Близость · 0106/);
  (card as any).tab = "learning";
  assert.match(rendered(card.render()), /Начать обучение фона/);
  card.setConfig({ language: "en", title: "My title" });
  text = rendered(card.render());
  assert.match(text, /Start background learning/);
  assert.match(text, /My title/);
  assert.doesNotMatch(text, /[А-Яа-яЁё]/);
});

test("glance card and editor follow HA language and explicit override without translating configured titles", () => {
  const card = new Fp2GlanceCard();
  card.setConfig({ title: "Custom title" });
  card.hass = hass("ru");
  (card as any).state = state();
  let text = rendered(card.render());
  assert.match(text, /Custom title/);
  assert.match(text, /Настроить ↗/);
  assert.match(text, /Свободно/);
  assert.match(text, /42 лк/);
  card.hass = hass("en");
  text = rendered(card.render());
  assert.match(text, /Configure ↗/);
  assert.match(text, /Unoccupied/);
  assert.match(text, /42 lx/);
  assert.doesNotMatch(text, /[А-Яа-яЁё]/);
  const editor = new Fp2LocalEditor();
  editor.setConfig({});
  editor.hass = hass("ru");
  text = rendered(editor.render());
  assert.match(text, /Название/);
  assert.match(text, /Как в Home Assistant/);
  editor.setConfig({ language: "en" });
  text = rendered(editor.render());
  assert.match(text, /Title/);
  assert.match(text, /Follow Home Assistant/);
  assert.match(text, /Entity prefix/);
});
