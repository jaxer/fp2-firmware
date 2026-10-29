import {
  translate,
  resolveLanguage,
  formatDate,
  type MessageValues,
} from "./localize.ts";
import { LitElement, html, svg, nothing, css } from "lit";
import { Fp2Client } from "./client.ts";
import { decodeMask, targetToGrid } from "./protocol.ts";
import type { CardConfig, HomeAssistant, PanelState } from "./types.ts";
export class Fp2GlanceCard extends LitElement {
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

  static styles = css`
    :host {
      display: block;
      container-type: inline-size;
      color: var(--primary-text-color);
      font-family: system-ui;
      min-width: 0;
    }
    * {
      box-sizing: border-box;
    }
    ha-card {
      display: block;
      padding: 16px;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
    }
    h2 {
      font-size: 17px;
      margin: 0;
    }
    a {
      color: var(--primary-color);
      font-size: 12px;
      text-decoration: none;
    }
    a:focus-visible {
      outline: 2px solid currentColor;
    }
    p {
      font-size: 12px;
      color: var(--secondary-text-color);
      margin: 8px 0;
    }
    .map {
      display: block;
      inline-size: 100%;
      block-size: 300px;
      margin-block: 8px;
      border-radius: 10px;
      background: var(--secondary-background-color);
    }
    .summary {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .pill {
      font-size: 12px;
      padding: 5px 9px;
      border-radius: 16px;
      background: var(--secondary-background-color);
    }
    .occupied {
      color: var(--primary-color);
      font-weight: 700;
    }
    .zones {
      display: flex;
      gap: 5px;
      flex-wrap: wrap;
      margin-top: 10px;
    }
    .zone {
      font-size: 11px;
      border: 1px solid var(--divider-color);
      border-inline-start: 3px solid var(--zone-color);
      padding: 4px 7px;
      border-radius: 5px;
    }
    .unknown {
      opacity: 0.6;
    }
    .foot {
      display: flex;
      justify-content: space-between;
      gap: 6px;
      flex-wrap: wrap;
      margin-top: 10px;
      font-size: 10px;
      color: var(--secondary-text-color);
    }
  `;
  private config: CardConfig = {};
  private ha?: HomeAssistant;
  private client?: Fp2Client;
  private state?: PanelState;
  static getStubConfig() {
    return {
      type: "custom:fp2-glance-card",
      title: translate("FP2 radar"),
    };
  }
  static getConfigElement() {
    return document.createElement("fp2-local-card-editor");
  }
  getCardSize() {
    return 7;
  }
  getGridOptions() {
    return { columns: 12, rows: 8, min_columns: 6 };
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
  }
  disconnectedCallback() {
    super.disconnectedCallback();
    this.client?.dispose();
    this.client = undefined;
  }
  private connect() {
    if (!this.isConnected || !this.ha || this.client) return;
    this.client = new Fp2Client(
      { ...this.config, read_only: true },
      (state) => {
        this.state = state;
        this.requestUpdate();
      },
    );
    this.state = this.client.state;
    this.client.attach(this.ha);
  }
  private color(id: number) {
    return `hsl(${(id * 137.508) % 360} 58% 52%)`;
  }
  render() {
    const s = this.state;
    if (!s)
      return html`<ha-card lang=${resolveLanguage(this.config, this.ha)}
        >${this.t("Connecting…")}</ha-card
      >`;
    const zones = Object.values(s.zones).filter((z) => z.active_raw !== 0);
    const live =
      s.deviceFresh &&
      s.room === "on" &&
      s.targets &&
      Date.now() - s.targets.receivedAt >= 0 &&
      Date.now() - s.targets.receivedAt < 5000;
    const occupied = zones.filter(
      (z) => s.deviceFresh && s.occupancy[z.id] === "on",
    );
    return html`<ha-card lang=${resolveLanguage(this.config, this.ha)}
      ><header>
        <h2>${this.config.title || this.t("FP2 radar")}</h2>
        <a href="/fp2-local/control" aria-label=${this.t("Open radar settings")}
          >${this.t("Configure ↗")}</a
        >
      </header>
      <p role="status">
        ${!s.deviceFresh ? this.t("No fresh data") : s.room === "on" ? this.t("Presence detected") : s.room === "off" ? this.t("Unoccupied") : this.t("Presence unknown")}
      </p>
      <div class="summary">
        <span class="pill"
          >${live ? this.t("Targets: {count}", { count: s.targets!.count }) : s.deviceFresh && s.room === "off" ? this.t("No presence") : this.t("Targets: waiting for a report")}</span
        ><span class="pill"
          >${this.t("{occupied} / {total} zones occupied", { occupied: s.deviceFresh ? occupied.length : "—", total: zones.length })}</span
        ><span class="pill"
          >${["unknown", "unavailable"].includes(s.illuminance) ? "—" : this.t("{value} lx", { value: s.illuminance })}</span
        >
      </div>
      <svg
        class="map"
        viewBox="-1 -1 18 22"
        role="img"
        aria-label=${this.t("Radar zones and live targets")}
      >
        <rect width="16" height="20" fill="var(--card-background-color)" />
        ${zones.map((z) => {
          const cells = decodeMask(z.mask);
          const middle = cells.flatMap((on, i) => (on ? [i] : []));
          const i = middle[Math.floor(middle.length / 2)];
          return svg`<g>${cells.map((on, i) => (on ? svg`<rect x=${(i % 16) + 0.03} y=${Math.floor(i / 16) + 0.03} width=".94" height=".94" fill=${this.color(z.id)} fill-opacity=${s.deviceFresh && s.occupancy[z.id] === "on" ? 0.65 : 0.22} stroke=${s.deviceFresh && s.occupancy[z.id] === "on" ? "var(--primary-text-color)" : "none"} stroke-width=".04"/>` : nothing))}${i !== undefined ? svg`<text x=${(i % 16) + 0.5} y=${Math.floor(i / 16) + 0.65} text-anchor="middle" font-size=".55" font-weight="700" fill="var(--primary-text-color)">${z.id}</text>` : nothing}</g>`;
        })}${Array.from({ length: 17 }, (_, i) => svg`<path d=${`M${i} 0V20`} stroke="var(--divider-color)" stroke-width=".025"/>`)}${Array.from({ length: 21 }, (_, i) => svg`<path d=${`M0 ${i}H16`} stroke="var(--divider-color)" stroke-width=".025"/>`)}
        <path d="M7.7 -.5H8.3L8 0Z" fill="var(--primary-text-color)" />
        ${
          live
            ? s.targets!.items.map((t) => {
                const p = targetToGrid(t);
                return svg`<g class="target" data-target-id=${t.id}><circle cx=${p.column} cy=${p.row} r=".25" fill="#04b9c1" stroke="#fff" stroke-width=".06"/><text x=${p.column + 0.32} y=${p.row + 0.12} font-size=".4" font-weight="700" fill="var(--primary-text-color)">T${t.id}</text></g>`;
              })
            : nothing
        }</svg
      >${!zones.length ? html`<p>${s.cacheError || this.t("Open settings and save the configuration from the radar.")}</p>` : nothing}
      <div class="zones">
        ${zones.map((z) => html`<span class="zone ${!s.deviceFresh ? "unknown" : s.occupancy[z.id] === "on" ? "occupied" : ""}" style=${`--zone-color:${this.color(z.id)}`} title=${`${s.zoneNames[z.id]} · ${!s.deviceFresh ? this.t("unknown") : s.occupancy[z.id] === "on" ? this.t("presence") : s.occupancy[z.id] === "off" ? this.t("clear") : this.t("unknown")}`}>${s.zoneNames[z.id]} ${!s.deviceFresh ? "?" : s.occupancy[z.id] === "on" ? "●" : s.occupancy[z.id] === "off" ? "○" : "?"}</span>`)}
      </div>
      <div class="foot">
        <span>${this.t("Zones — saved map · targets — live")}</span
        ><span
          >${s.cacheSavedAt ? this.date(s.cacheSavedAt) : this.t("Map not saved")}</span
        >
      </div></ha-card
    >`;
  }
}
if (!customElements.get("fp2-glance-card"))
  customElements.define("fp2-glance-card", Fp2GlanceCard);
const registry = window as unknown as { customCards?: unknown[] };
registry.customCards ??= [];
registry.customCards.push({
  type: "fp2-glance-card",
  name: translate("FP2 · Radar overview"),
  description: translate("Compact zone map with live targets"),
  preview: false,
});
