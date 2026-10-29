import { translate, resolveLanguage, type MessageValues } from "./localize.ts";
import { LitElement, html } from "lit";
import type { CardConfig, HomeAssistant } from "./types.ts";
import { styles } from "./styles.ts";
export class Fp2LocalEditor extends LitElement {
  private t(key: string, values: MessageValues = {}) {
    return translate(key, resolveLanguage(this.config, this.ha), values);
  }
  private ha?: HomeAssistant;
  set hass(value: HomeAssistant) {
    this.ha = value;
    this.requestUpdate();
  }

  static styles = styles;
  private config: CardConfig = {};
  setConfig(config: CardConfig) {
    this.config = { ...config };
    this.requestUpdate();
  }
  private change(key: keyof CardConfig, event: Event) {
    this.config = {
      ...this.config,
      [key]: (event.target as HTMLInputElement).value,
    };
    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config: this.config },
        bubbles: true,
        composed: true,
      }),
    );
    this.requestUpdate();
  }
  render() {
    return html`<div class="body" lang=${resolveLanguage(this.config, this.ha)}>
      <label class="field"
        >${this.t("Title")}<input
          .value=${this.config.title || this.t("FP2")}
          @change=${(e: Event) => this.change("title", e)}
      /></label>
      <p>
        ${this.t("The card uses your current Home Assistant session. No token or external server is needed.")}
      </p>
      <label class="field"
        >${this.t("Language")}<select
          .value=${this.config.language ?? ""}
          @change=${(e: Event) => this.change("language", e)}
        >
          <option value="">${this.t("Follow Home Assistant")}</option>
          <option value="en">English</option>
          <option value="ru">Русский</option>
        </select></label
      >
      <details>
        <summary>${this.t("Connection · advanced options")}</summary>
        ${(["entity_prefix", "service_prefix", "node"] as const).map((key) => html`<label class="field">${this.t({ entity_prefix: "Entity prefix", service_prefix: "Service prefix", node: "Node" }[key])}<input .value=${this.config[key] || { entity_prefix: "fp2", service_prefix: "fp2", node: "fp2" }[key]} @change=${(e: Event) => this.change(key, e)} /></label>`)}
      </details>
    </div>`;
  }
}
if (!customElements.get("fp2-local-card-editor"))
  customElements.define("fp2-local-card-editor", Fp2LocalEditor);
