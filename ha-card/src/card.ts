import {
  translate,
  resolveLanguage,
  formatDate,
  type MessageValues,
} from "./localize.ts";
import { LitElement, html, svg, nothing } from "lit";
import { Fp2Client } from "./client.ts";
import {
  decodeMask,
  paintRectangle,
  targetToGrid,
  decodeTargetMetadata,
  SPECIAL_MAPS,
  SCALAR_CONTROLS,
  ZONE_TYPE_CODES,
} from "./protocol.ts";
import type {
  CardConfig,
  HomeAssistant,
  PanelState,
  ZoneProperties,
} from "./types.ts";
import { styles } from "./styles.ts";
import "./editor.ts";
import "./glance.ts";
const EMPTY = "0".repeat(80);
type Cell = { column: number; row: number };
export class Fp2LocalCard extends LitElement {
  private t(key: string, values: MessageValues = {}) {
    return translate(key, resolveLanguage(this.config, this.ha), values);
  }
  private date(timestamp: number, timeOnly = false) {
    return formatDate(
      timestamp,
      resolveLanguage(this.config, this.ha),
      timeOnly,
    );
  }

  static styles = styles;
  private config: CardConfig = {};
  private ha?: HomeAssistant;
  private client?: Fp2Client;
  private state?: PanelState;
  private tab = "map";
  private selected = 1;
  private layer = "zone";
  private draft: string | null = null;
  private history: string[] = [];
  private future: string[] = [];
  private tool = "rectangle";
  private start: Cell | null = null;
  private base = "";
  private timer?: ReturnType<typeof setInterval>;
  private clearRoom = false;
  private error = "";
  private deleting = false;
  static getConfigElement() {
    return document.createElement("fp2-local-card-editor");
  }
  static getStubConfig() {
    return { type: "custom:fp2-local-card", title: translate("FP2") };
  }
  getCardSize() {
    return 12;
  }
  getGridOptions() {
    return { columns: "full", rows: "auto", min_columns: 6 };
  }
  setConfig(config: CardConfig) {
    this.config = { ...config };
    this.client?.dispose();
    this.client = undefined;
    this.connect();
    this.requestUpdate();
  }
  set hass(value: HomeAssistant) {
    this.ha = value;
    this.connect();
    this.client?.attach(value);
    this.requestUpdate();
  }
  connectedCallback() {
    super.connectedCallback();
    this.connect();
    this.timer = setInterval(() => this.requestUpdate(), 1000);
  }
  disconnectedCallback() {
    super.disconnectedCallback();
    if (this.timer) clearInterval(this.timer);
    this.client?.dispose();
    this.client = undefined;
  }
  private connect() {
    if (!this.isConnected || !this.ha || this.client) return;
    this.client = new Fp2Client(this.config, () => {
      this.state = this.client?.state;
      this.requestUpdate();
    });
    this.state = this.client.state;
    this.client.attach(this.ha);
  }
  private async run(action: () => Promise<unknown>) {
    this.error = "";
    try {
      await action();
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
    }
    this.requestUpdate();
  }
  private mask() {
    return this.layer === "zone"
      ? this.state?.zones[this.selected]?.mask || EMPTY
      : this.state?.specialMaps[Number(this.layer)]?.mask || EMPTY;
  }
  private choose(id: number) {
    if (this.draft !== null && !confirm(this.t("Discard the unsaved draft?")))
      return;
    this.cancel();
    this.selected = id;
    this.layer = "zone";
    this.requestUpdate();
  }
  private cancel() {
    this.draft = null;
    this.history = [];
    this.future = [];
    this.deleting = false;
    this.requestUpdate();
  }
  private changeMask(mask: string) {
    if (mask === (this.draft ?? this.mask())) return;
    this.history.push(this.draft ?? this.mask());
    this.future = [];
    this.draft = mask;
    this.requestUpdate();
  }
  private undo() {
    if (!this.history.length) return;
    this.future.push(this.draft ?? this.mask());
    this.draft = this.history.pop()!;
    this.requestUpdate();
  }
  private redo() {
    if (!this.future.length) return;
    this.history.push(this.draft ?? this.mask());
    this.draft = this.future.pop()!;
    this.requestUpdate();
  }
  private point(e: PointerEvent): Cell | null {
    const svg = e.currentTarget as SVGSVGElement;
    const matrix = svg.getScreenCTM();
    if (!matrix) return null;
    const point = svg.createSVGPoint();
    point.x = e.clientX;
    point.y = e.clientY;
    const local = point.matrixTransform(matrix.inverse());
    const column = Math.floor(local.x),
      row = Math.floor(local.y);
    return column >= 0 && column < 16 && row >= 0 && row < 20
      ? { column, row }
      : null;
  }
  private down(e: PointerEvent) {
    if (this.draft === null) return;
    const p = this.point(e);
    if (!p) return;
    e.preventDefault();
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    this.start = p;
    this.base = this.draft;
    this.history.push(this.draft);
    this.future = [];
    this.paint(p);
  }
  private move(e: PointerEvent) {
    if (this.start) {
      const p = this.point(e);
      if (p) this.paint(p);
    }
  }
  private paint(p: Cell) {
    this.draft = paintRectangle(
      this.tool === "rectangle" ? this.base : this.draft!,
      this.tool === "rectangle" ? this.start! : p,
      p,
      this.tool !== "erase",
    );
    this.requestUpdate();
  }
  private end() {
    this.start = null;
  }
  private async apply() {
    const mask = this.draft;
    if (mask === null || !this.client) return;
    await this.run(async () => {
      if (this.layer === "zone")
        await this.client!.saveZone(this.selected, mask);
      else await this.client!.saveSpecialMap(Number(this.layer), mask);
      this.cancel();
    });
  }
  private status(id: number) {
    const z = this.state?.zones[id];
    if (!z) return this.t("Not read");
    if (z.active_raw === 0 && !decodeMask(z.mask).some(Boolean))
      return this.t("Not configured");
    if (!this.state?.deviceFresh) return this.t("No fresh data");
    const v = this.state.occupancy[id];
    return v === "on"
      ? this.t("Presence")
      : v === "off"
        ? this.t("Unoccupied")
        : this.t("Unknown");
  }
  private color(id: number) {
    return `hsl(${(id * 137.508) % 360} 58% 52%)`;
  }
  private renderMap() {
    const s = this.state!;
    const editable = this.draft !== null;
    const mapMask = this.draft ?? this.mask();
    const live =
      s.deviceFresh &&
      s.room === "on" &&
      s.traffic === "on" &&
      s.targets &&
      Date.now() - s.targets.receivedAt < 5000;
    return html`<div class="mapbox">
      <div class="row">
        <strong
          >${editable ? this.t("Draft") : this.layer === "zone" ? this.t("Presence map") : this.t(SPECIAL_MAPS.find((m) => String(m.attribute) === this.layer)?.label ?? "")}</strong
        ><span class="pill">16 × 20</span>
      </div>
      <p class="tiny">${this.t("Radar coordinate grid · not metres")}</p>
      ${
        editable
          ? html`<div class="tools">
              ${[
                ["rectangle", this.t("Rectangle")],
                ["paint", this.t("Brush")],
                ["erase", this.t("Eraser")],
              ].map(
                ([key, label]) =>
                  html`<button
                    class=${this.tool === key ? "active" : ""}
                    @click=${() => {
                      this.tool = key;
                      this.requestUpdate();
                    }}
                  >
                    ${label}
                  </button>`,
              )}
            </div>`
          : nothing
      }<svg
        class="map ${editable ? "editing" : ""}"
        viewBox="-1 -1 18 22"
        role="img"
        aria-label=${this.t("Radar map: 16 columns, 20 rows")}
        @pointerdown=${this.down}
        @pointermove=${this.move}
        @pointerup=${this.end}
        @pointercancel=${this.end}
      >
        <rect width="16" height="20" fill="var(--card-background-color,#fff)" />
        ${
          this.layer === "zone" && !editable
            ? Object.values(s.zones).map(
                (z) =>
                  svg`<g role="button" tabindex="0" aria-label=${this.t("Zone {id}", { id: z.id })} @click=${() => {
                    if (!editable) this.choose(z.id);
                  }} @keydown=${(e: KeyboardEvent) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      this.choose(z.id);
                    }
                  }}>${decodeMask(z.mask).map((on, i) => (on ? svg`<rect x=${(i % 16) + 0.02} y=${Math.floor(i / 16) + 0.02} width=".96" height=".96" fill=${this.color(z.id)} fill-opacity=${z.id === this.selected ? 0.7 : 0.3} stroke=${s.deviceFresh && s.occupancy[z.id] === "on" ? "var(--primary-text-color)" : "none"} stroke-width=".06"/>` : nothing))}${this.zoneLabel(z.id, z.mask)}</g>`,
              )
            : decodeMask(mapMask).map((on, i) =>
                on
                  ? svg`<rect x=${(i % 16) + 0.03} y=${Math.floor(i / 16) + 0.03} width=".94" height=".94" fill=${editable ? "#e5aa35" : this.color(this.selected)} opacity=".65"/>`
                  : nothing,
              )
        }${Array.from({ length: 17 }, (_, i) => svg`<path d=${`M${i} 0V20`} stroke="var(--divider-color,#ccd6df)" stroke-width=".025"/>`)}${Array.from({ length: 21 }, (_, i) => svg`<path d=${`M0 ${i}H16`} stroke="var(--divider-color,#ccd6df)" stroke-width=".025"/>`)}
        <path d="M7.7 -.4H8.3L8 0Z" fill="var(--primary-text-color)" />
        <text
          x="8"
          y="-.6"
          text-anchor="middle"
          font-size=".28"
          fill="var(--secondary-text-color)"
        >
          ${this.t("SENSOR · c8 / r0")}
        </text>
        ${[0, 4, 8, 12, 16].map((c) => svg`<text x=${c} y="20.55" text-anchor="middle" font-size=".28" fill="var(--secondary-text-color)">c${c}</text>`)}${[0, 5, 10, 15, 20].map((r) => svg`<text x="-.2" y=${r + 0.1} text-anchor="end" font-size=".28" fill="var(--secondary-text-color)">r${r}</text>`)}${
          live
            ? s.targets!.items.map((t) => {
                const p = targetToGrid(t);
                return svg`<circle cx=${p.column} cy=${p.row} r=".23" fill="#04b9c1" stroke="#fff" stroke-width=".06"/><text x=${p.column + 0.3} y=${p.row + 0.12} font-size=".34" fill="var(--primary-text-color)" font-weight="700">T${t.id}</text>`;
              })
            : nothing
        }
      </svg>
      <div class="legend">
        <span
          ><i class="dot" style="background:#04b9c1"></i
          >${this.t("Radar target")}</span
        ><span>${this.t("Colour — zone · outline — presence")}</span
        >${editable ? html`<span>${this.t("Yellow — local draft")}</span>` : nothing}
      </div>
      <p class="tiny">
        ${live ? this.t("Live targets: {count}", { count: s.targets!.items.length }) : !s.deviceFresh ? this.t("Sensor unavailable or data stale") : s.room === "off" ? this.t("Area clear · waiting for movement") : this.t("No fresh target report")}
      </p>
    </div>`;
  }
  private targetMetadata() {
    const s = this.state!,
      report = s.targets;
    const elapsed = report ? Date.now() - report.receivedAt : Infinity;
    const fresh =
      !!report &&
      elapsed >= 0 &&
      elapsed < 5000 &&
      s.deviceFresh &&
      s.room === "on" &&
      s.traffic === "on";
    return html`<section class="section target-panel">
      <div class="row">
        <h3>${this.t("Target data")}</h3>
        <span class="pill ${fresh ? "live" : "warning"}"
          >${fresh ? this.t("Live report") : this.t("No fresh targets")}</span
        >
      </div>
      <p class="tiny">
        ${this.t("Report: {report}. Protocol fields without confirmed physical units.", { report: report ? this.t("{seconds} s ago · sequence {sequence}", { seconds: Math.max(0, Math.floor(elapsed / 1000)), sequence: report.sequence }) : this.t("not received yet") })}
      </p>
      ${
        fresh
          ? html`<div class="target-cards">
                ${report!.items.map((t) => {
                  let m;
                  try {
                    m = decodeTargetMetadata(t.raw_hex);
                  } catch {
                    return html`<p>
                      ${this.t("T{id}: invalid record", { id: t.id })}
                    </p>`;
                  }
                  const p = targetToGrid(t);
                  const fields = [
                    [this.t("Coordinate a · raw"), t.a_hundredths],
                    [this.t("Coordinate b · raw"), t.b_hundredths],
                    [this.t("u16 · bytes 5–6"), m.u16_at_5],
                    [this.t("Speed · raw"), m.u16_at_7],
                    [this.t("SNR · code"), m.u16_at_9],
                    [this.t("Status · byte 11"), m.byte_11],
                    [
                      this.t("Posture · code"),
                      m.byte_12 === 255 ? this.t("255 · no value") : m.byte_12,
                    ],
                    [
                      this.t("Radar zone"),
                      m.byte_13 === 0 ? this.t("0 · no match") : m.byte_13,
                    ],
                  ];
                  return html`<article class="target-card">
                    <div class="row">
                      <strong>T${t.id}</strong
                      ><span class="pill"
                        >c${p.column.toFixed(2)} · r${p.row.toFixed(2)}</span
                      >
                    </div>
                    <dl>
                      ${fields.map(
                        ([label, value]) =>
                          html`<div>
                            <dt>${label}</dt>
                            <dd>${value}</dd>
                          </div>`,
                      )}
                    </dl>
                    <details>
                      <summary>${this.t("Record · 14 bytes")}</summary>
                      <code>${t.raw_hex}</code>
                    </details>
                  </article>`;
                })}
              </div>
              ${report!.items.length === 0 ? html`<p>${this.t("The device reported no targets.")}</p>` : nothing}`
          : html`<p>
              ${!report ? this.t("Waiting for an actual radar report.") : !s.deviceFresh ? this.t("Sensor unavailable or data stale.") : s.room === "off" ? this.t("Room clear.") : elapsed >= 5000 ? this.t("The last report is stale.") : this.t("Waiting for fresh targets.")}
              ${this.t("Values hidden.")}
            </p>`
      }
      <p class="tiny">
        ${this.t("Byte offsets start at 0 within each target record. Field meanings are only partly understood. SNR is a scaled code, not dB or confidence; posture is code 1/2 without confirmed posture names; code 2 is also the default (255 means no value with a nonzero status). Zone is the radar classifier’s first match, not a geometry check against this page. Speed uses internal units ×100; the physical scale is unconfirmed. These fields are not confidence estimates.")}
      </p>
    </section>`;
  }
  private zoneLabel(id: number, mask: string) {
    const cells = decodeMask(mask).flatMap((v, i) => (v ? [i] : []));
    if (!cells.length) return nothing;
    const i = cells[Math.floor(cells.length / 2)];
    return svg`<text x=${(i % 16) + 0.5} y=${Math.floor(i / 16) + 0.65} text-anchor="middle" font-size=".56" font-weight="800" fill="var(--primary-text-color)" stroke="var(--card-background-color,#fff)" stroke-width=".07" paint-order="stroke">${id}</text>`;
  }
  private renderZones() {
    return html`<div class="list">
      ${Array.from({ length: 30 }, (_, i) => i + 1).map((id) => html`<button class="zone ${id === this.selected ? "selected" : ""} ${!this.state?.zones[id] || this.state.zones[id].active_raw === 0 ? "unset" : ""}" style=${`--zone-color:${this.color(id)}`} @click=${() => this.choose(id)}><strong>${this.state?.zoneNames[id] || this.t("Zone {id}", { id: id })}</strong><small>${this.status(id)}</small></button>`)}
    </div>`;
  }
  private zoneEditor() {
    const z = this.state!.zones[this.selected];
    return html`<section class="section">
      <div class="row">
        <h3>
          ${this.state!.zoneNames[this.selected] || this.t("Zone {id}", { id: this.selected })}
        </h3>
        <span class="pill">${this.status(this.selected)}</span>
      </div>
      <p class="tiny">
        ${z ? this.t("{source} · {count} cells", { source: z.fresh ? this.t("Read from radar") : this.t("Saved observation"), count: decodeMask(z.mask).filter(Boolean).length }) : this.t("Read the configuration first or create a zone on the map.")}
      </p>
      <div class="tools">
        <button
          @click=${() => this.run(() => this.client!.readZone(this.selected))}
          ?disabled=${this.state!.busy}
        >
          ${this.t("Read")}</button
        ><button
          @click=${() => {
            this.draft = this.mask();
            this.requestUpdate();
          }}
          ?disabled=${this.draft !== null || this.state!.busy || !z?.fresh}
        >
          ${z?.active_raw ? this.t("Edit geometry") : this.t("Create zone")}
        </button>
      </div>
      <label class="field"
        >${this.t("Name in Home Assistant")}<input
          .value=${this.state!.zoneNames[this.selected] || ""}
          placeholder=${this.t("Zone {id}", { id: this.selected })}
          @change=${(e: Event) => {
            const name = (e.target as HTMLInputElement).value.trim();
            if (name)
              this.run(() => this.client!.renameZone(this.selected, name));
          }}
      /></label>
      <div class="zone-properties">
        <h3>${this.t("Zone settings")}</h3>
        <p class="tiny">
          ${this.t("Device codes. Physical type names are unconfirmed.")}
        </p>
        <label class="field"
          >${this.t("Zone sensitivity")}<select
            ?disabled=${!z || this.state!.busy}
            @change=${(e: Event) => {
              const input = e.target as HTMLSelectElement;
              this.zoneProperty("sensitivity", Number(input.value));
              input.value = String(z?.sensitivity ?? "");
            }}
          >
            ${!z || ![1, 2, 3].includes(z.sensitivity) ? html`<option value=${z?.sensitivity ?? ""} .selected=${true} disabled>${z ? this.t("{value} · unknown code", { value: z.sensitivity }) : this.t("Not read")}</option>` : nothing}${[
              [1, 200],
              [2, 400],
              [3, 2000],
            ].map(
              ([value, window]) =>
                html`<option
                  value=${value}
                  .selected=${z?.sensitivity === value}
                >
                  ${this.t("{value} · history up to {window} samples", { value, window })}
                </option>`,
            )}</select
          ><span class="tiny"
            >${this.t("Tracker history window limit: 1 → 200, 2 → 400, 3 → 2000 internal cycles, not seconds. A longer window may retain older target evidence. This is part of the algorithm, not a confirmed “low → high sensitivity” scale. Global sensitivity works differently.")}</span
          ></label
        ><label class="field"
          >${this.t("Type code")}<select
            ?disabled=${!z || this.state!.busy}
            .value=${String(z?.type ?? 0)}
            @change=${(e: Event) => this.zoneProperty("type", Number((e.target as HTMLSelectElement).value))}
          >
            ${ZONE_TYPE_CODES.map((code, i) => html`<option value=${i}>${code} · raw ${i}</option>`)}
          </select></label
        >${this.zoneField(this.t("0153 · write value (RAM raw: {raw}, inversion 0↔1)", { raw: z?.close_away_raw ?? "—" }), z ? (z.close_away_raw === 0 ? 1 : 0) : undefined, "close_away_value", 0, 1)}
      </div>
      ${
        this.deleting
          ? html`<div class="notice error">
              ${this.t("Delete zone {id} from the device?", { id: this.selected })}
              <div class="tools">
                <button
                  class="danger"
                  @click=${() =>
                    this.run(async () => {
                      await this.client!.deleteZone(this.selected);
                      this.cancel();
                    })}
                >
                  ${this.t("Confirm deletion")}</button
                ><button
                  @click=${() => {
                    this.deleting = false;
                    this.requestUpdate();
                  }}
                >
                  ${this.t("Cancel")}
                </button>
              </div>
            </div>`
          : html`<button
              class="danger"
              ?disabled=${!z || z.active_raw === 0 || this.state!.busy}
              @click=${() => {
                this.deleting = true;
                this.requestUpdate();
              }}
            >
              ${this.t("Delete zone…")}
            </button>`
      }
    </section>`;
  }
  private zoneField(
    label: string,
    value: number | undefined,
    key: keyof ZoneProperties,
    min: number,
    max: number,
  ) {
    return html`<label class="field"
      >${label}<input
        type="number"
        min=${min}
        max=${max}
        .value=${String(value ?? 0)}
        ?disabled=${!this.state!.zones[this.selected] || this.state!.busy}
        @change=${(e: Event) => this.zoneProperty(key, Number((e.target as HTMLInputElement).value))}
    /></label>`;
  }
  private zoneProperty(key: keyof ZoneProperties, value: number) {
    if (
      confirm(this.t("Write the zone setting and verify by reading it back?"))
    )
      this.run(() =>
        this.client!.saveZoneProperties(this.selected, { [key]: value }),
      );
  }
  private draftTools() {
    return this.draft === null
      ? nothing
      : html`<div class="notice draft">
          <strong>${this.t("Local draft")}</strong>
          <p>
            ${this.t("The device is unchanged. “Apply” writes the selected map and verifies it by reading it back. To remove a zone, use “Delete zone”.")}
          </p>
          <div class="tools">
            <button @click=${this.undo} ?disabled=${!this.history.length}>
              ${this.t("↶ Undo")}</button
            ><button @click=${this.redo} ?disabled=${!this.future.length}>
              ${this.t("↷ Redo")}</button
            ><button @click=${() => this.changeMask(EMPTY)}>
              ${this.t("Clear")}</button
            ><button @click=${this.cancel}>${this.t("Discard")}</button
            ><button
              class="primary"
              ?disabled=${this.state!.busy || (this.layer === "zone" && !decodeMask(this.draft).some(Boolean))}
              @click=${this.apply}
            >
              ${this.t("Apply")}
            </button>
          </div>
        </div>`;
  }
  private settings() {
    return html`<section class="section">
        <h3>${this.t("Special maps")}</h3>
        <p>
          ${this.t("Select a map, then edit a local draft. Only “Apply” writes it to the device.")}
        </p>
        ${SPECIAL_MAPS.map(
          (m) =>
            html`<button
              class=${this.layer === String(m.attribute) ? "active" : ""}
              @click=${() => {
                if (
                  this.draft !== null &&
                  !confirm(this.t("Discard the draft?"))
                )
                  return;
                this.cancel();
                this.layer = String(m.attribute);
                this.tab = "map";
                this.requestUpdate();
              }}
            >
              ${this.t(m.label)}
            </button>`,
        )}
      </section>
      <details class="section">
        <summary>${this.t("Advanced radar settings")}</summary>
        <p>
          ${this.t("Numeric protocol values. Changes require confirmation and read-back verification.")}
        </p>
        <p class="tiny">
          ${this.t("Individual target deletion · 0160: unavailable because the radar firmware may enter an infinite loop.")}
        </p>
        ${SCALAR_CONTROLS.map(
          (c) =>
            html`<label class="field"
              >${this.t(c.label)}
              <div class="row">
                <input
                  type="number"
                  min=${c.min}
                  max=${c.max}
                  .value=${String(this.state!.scalars[c.attribute]?.wire ?? "")}
                  id=${`scalar-${c.attribute}`}
                  placeholder=${this.t("Not read")}
                /><button
                  ?disabled=${this.state!.busy}
                  @click=${() => {
                    const input = this.renderRoot.querySelector(
                      `#scalar-${c.attribute}`,
                    ) as HTMLInputElement;
                    const value = Number(input.value);
                    if (
                      input.value !== "" &&
                      input.reportValidity() &&
                      confirm(
                        this.t("Write “{label}”: {value}?", {
                          label: this.t(c.label),
                          value: value,
                        }),
                      )
                    )
                      this.run(() =>
                        this.client!.saveScalar(c.attribute, value),
                      );
                  }}
                >
                  ${this.t("Apply")}
                </button>
              </div></label
            >`,
        )}
      </details>`;
  }
  private learningLocked() {
    return /awaiting completion|outcome unknown/i.test(
      this.state?.learningStatus || "",
    );
  }
  private learning() {
    return html`<div class="section">
        <h3>${this.t("Background learning")}</h3>
        <p>
          ${this.t("1. Remove people and moving objects from all visible zones.")}<br />${this.t("2. Leave the room.")}<br />${this.t("3. Start learning. The result below comes from the device.")}
        </p>
        <label class="checkbox"
          ><input
            type="checkbox"
            .checked=${this.clearRoom}
            @change=${(e: Event) => {
              this.clearRoom = (e.target as HTMLInputElement).checked;
              this.requestUpdate();
            }}
          />${this.t("All visible zones are clear and the sensor is stationary; I am ready to start learning.")}</label
        ><button
          class="primary"
          ?disabled=${!this.clearRoom || this.state!.busy || this.learningLocked()}
          @click=${() => this.run(() => this.client!.startLearning(0x113))}
        >
          ${this.t("Start background learning")}
        </button>
        <p>
          ${this.t("Device status: {status}", { status: this.state!.learningStatus || this.t("No message") })}
        </p>
      </div>
      <div class="section">
        <h3>${this.t("Automatic coverage map")}</h3>
        <p>
          ${this.t("Creates a proposed edge map 0107 from the coverage limits. This is not a confirmed room outline; the proposal is not applied automatically.")}
        </p>
        <button
          ?disabled=${this.state!.busy || this.learningLocked()}
          @click=${() => this.run(() => this.client!.startLearning(0x150))}
        >
          ${this.t("Start detection")}</button
        >${
          this.state!.autoEdgeCandidate
            ? html`<p>
                  ${this.t("Proposal received. Open it as a draft and check the map.")}
                </p>
                <button
                  @click=${() => {
                    this.cancel();
                    this.layer = String(0x107);
                    this.draft = this.state!.autoEdgeCandidate;
                    this.tab = "map";
                    this.requestUpdate();
                  }}
                >
                  ${this.t("Preview proposal")}
                </button>`
            : html`<p class="tiny">${this.t("No proposal received yet.")}</p>`
        }
      </div>`;
  }
  render() {
    if (!this.state)
      return html`<ha-card lang=${resolveLanguage(this.config, this.ha)}
        ><div class="body">
          <h2>${this.config.title || this.t("FP2")}</h2>
          <p>${this.t("Connecting to Home Assistant…")}</p>
        </div></ha-card
      >`;
    const s = this.state;
    return html`<ha-card lang=${resolveLanguage(this.config, this.ha)}
      ><div class="body">
        <header>
          <div>
            <div class="eyebrow">${this.t("Aqara FP2 · local control")}</div>
            <h2>${this.config.title || this.t("FP2")}</h2>
          </div>
          <span class="pill ${s.deviceFresh ? "live" : "warning"}"
            >${s.deviceFresh ? this.t("● Connected") : this.t("No fresh data")}</span
          >
        </header>
        <div class="row" style="margin-top:12px">
          <span class="tiny"
            >${s.cacheSavedAt ? this.t("Map saved in HA · {date}", { date: this.date(s.cacheSavedAt) }) : this.t("Map not saved yet")}</span
          ><button
            ?disabled=${s.busy || this.draft !== null}
            @click=${() => this.run(() => this.client!.refreshAll())}
          >
            ${this.t("Refresh from radar")}
          </button>
        </div>
        ${s.cacheError ? html`<p role="status">${s.cacheError}</p>` : nothing}
        <div class="tabs" role="tablist">
          ${["map", "settings", "learning"].map(
            (t) =>
              html`<button
                role="tab"
                aria-selected=${this.tab === t}
                class=${this.tab === t ? "active" : ""}
                @click=${() => {
                  this.tab = t;
                  if (t === "learning") void this.client!.refreshStatus();
                  this.requestUpdate();
                }}
              >
                ${this.t(({ map: "Map", settings: "Settings", learning: "Learning" } as Record<string, string>)[t])}
              </button>`,
          )}
        </div>
        <div class="stats">
          <div class="stat">
            <small>${this.t("Presence")}</small
            ><strong
              >${!s.deviceFresh ? this.t("Unknown") : s.room === "on" ? this.t("Presence") : s.room === "off" ? this.t("Unoccupied") : this.t("Unknown")}</strong
            >
          </div>
          <div class="stat">
            <small>${this.t("Illuminance")}</small
            ><strong
              >${s.illuminance && s.illuminance !== "unknown" && s.illuminance !== "unavailable" ? this.t("{value} lx", { value: s.illuminance }) : "—"}</strong
            >
          </div>
          <div class="stat">
            <small>${this.t("Configuration")}</small
            ><strong>${Object.keys(s.zones).length} / 30</strong>
          </div>
        </div>
        ${this.error ? html`<div class="notice error" role="alert">${this.client?.localizeMessage(this.error) ?? this.error}</div>` : nothing}${s.notice ? html`<div class="notice ${s.notice.kind}" role="status">${s.notice.message}</div>` : nothing}${s.progress ? html`<p role="status">${s.progress.label} · ${s.progress.done}/${s.progress.total}</p>` : nothing}${this.draftTools()}${
          this.tab === "settings"
            ? this.settings()
            : this.tab === "learning"
              ? this.learning()
              : html`<div class="workspace">
                  <div>
                    ${this.renderMap()}${this.targetMetadata()}${
                      this.layer !== "zone"
                        ? html`<div class="tools">
                            <button
                              @click=${() => {
                                this.draft = this.mask();
                                this.requestUpdate();
                              }}
                              ?disabled=${this.draft !== null || s.busy || !s.specialMaps[Number(this.layer)]?.fresh}
                            >
                              ${this.t("Edit map")}</button
                            ><button
                              @click=${() => {
                                if (
                                  this.draft !== null &&
                                  !confirm(this.t("Discard the draft?"))
                                )
                                  return;
                                this.cancel();
                                this.layer = "zone";
                                this.requestUpdate();
                              }}
                            >
                              ${this.t("Back to zones")}
                            </button>
                          </div>`
                        : nothing
                    }
                  </div>
                  <div>
                    ${this.renderZones()}${
                      this.layer === "zone"
                        ? this.zoneEditor()
                        : html`<section class="section">
                            <h3>
                              ${this.t(SPECIAL_MAPS.find((m) => String(m.attribute) === this.layer)?.label ?? "")}
                            </h3>
                            <p>
                              ${this.t(SPECIAL_MAPS.find((m) => String(m.attribute) === this.layer)?.description ?? "")}
                            </p>
                            <p class="tiny">
                              ${this.state.specialMaps[Number(this.layer)]?.fresh ? this.t("Fresh radar data") : this.t("Map not read yet or restored from an earlier save")}
                            </p>
                          </section>`
                    }
                  </div>
                </div>`
        }
        <details>
          <summary>${this.t("Diagnostics and refresh")}</summary>
          <button
            ?disabled=${s.busy}
            @click=${() => this.run(() => this.client!.refreshAll())}
          >
            ${this.t("Read all configuration")}
          </button>
          <p>
            ${this.t("{status} · Frames: {valid} / rejected {rejected}", { status: s.configurationStatus, valid: s.frames.valid, rejected: s.frames.rejected })}
          </p>
          ${
            s.targets
              ? html`<p class="tiny">
                    ${this.t("Target report: {seconds} s ago · N{count}", { seconds: Math.max(0, Math.floor((Date.now() - s.targets.receivedAt) / 1000)), count: s.targets.count })}
                  </p>
                  ${s.targets.items.map((t) => html`<p class="tiny">T${t.id} · a=${t.a_hundredths}, b=${t.b_hundredths} · flag=${t.flag_raw}</p>`)}`
              : html`<p>${this.t("Waiting for an actual target report.")}</p>`
          }
          <div class="events">
            ${s.events
              .slice(-12)
              .reverse()
              .map(
                (e) => html`<div>${this.date(e.at, true)} · ${e.label}</div>`,
              )}
          </div>
        </details>
      </div></ha-card
    >`;
  }
}
if (!customElements.get("fp2-local-card"))
  customElements.define("fp2-local-card", Fp2LocalCard);
const registry = window as unknown as { customCards?: unknown[] };
registry.customCards = registry.customCards || [];
registry.customCards.push({
  type: "fp2-local-card",
  name: translate("FP2 · Local control"),
  description: translate("Presence map, zones and FP2 radar settings"),
  preview: false,
});
