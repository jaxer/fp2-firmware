export type EntityState = "on" | "off" | "unknown" | "unavailable" | string;
export interface CardConfig {
  type?: string;
  title?: string;
  /** Optional UI language override; omit to follow Home Assistant. */
  language?: string;
  entity_prefix?: string;
  service_prefix?: string;
  node?: string;
  cache_dashboard?: string;
  read_only?: boolean;
}
export interface HaEntity {
  state: string;
  attributes: Record<string, unknown>;
  last_updated: string;
  last_changed?: string;
}
export interface HomeAssistant {
  states: Record<string, HaEntity>;
  locale?: { language?: string };
  language?: string;
  connection: {
    connected?: boolean;
    subscribeEvents: (
      callback: (event: any) => void,
      type: string,
    ) => Promise<() => void>;
  };
  callService: (
    domain: string,
    service: string,
    data: Record<string, unknown>,
  ) => Promise<unknown>;
  callWS: (message: Record<string, unknown>) => Promise<any>;
}
export interface ZoneConfiguration {
  kind: "zone";
  id: number;
  active_raw: number;
  mask: string;
  sensitivity: number;
  type: number;
  close_away_raw: number;
  source: string;
  observed_ms: number;
  seenAt: number;
  fresh: boolean;
}
export interface MapConfiguration {
  kind: "map";
  attribute: number;
  mask: string;
  source: string;
  observed_ms: number;
  seenAt: number;
  fresh: boolean;
}
export interface ScalarConfiguration {
  kind: "scalar";
  attribute: number;
  raw: number;
  wire: number;
  source: string;
  observed_ms: number;
  seenAt: number;
  fresh: boolean;
}
export interface RadarTarget {
  id: number;
  a_hundredths: number;
  b_hundredths: number;
  flag_raw: number;
  raw_hex: string;
}
export interface PanelState {
  zones: Record<number, ZoneConfiguration>;
  specialMaps: Record<number, MapConfiguration>;
  scalars: Record<number, ScalarConfiguration>;
  occupancy: Record<number, EntityState>;
  zoneNames: Record<number, string>;
  room: EntityState;
  traffic: EntityState;
  deviceFresh: boolean;
  targets: {
    receivedAt: number;
    sequence: string | number;
    count: number;
    items: RadarTarget[];
  } | null;
  learningStatus: string;
  autoEdgeCandidate: string | null;
  configurationStatus: string;
  frames: { valid: string; rejected: string };
  illuminance: string;
  cacheSavedAt?: number;
  cacheError?: string;
  busy: boolean;
  progress: { done: number; total: number; label: string } | null;
  notice: { kind: "success" | "error" | "info"; message: string } | null;
  events: { at: number; label: string }[];
}
export interface ZoneProperties {
  sensitivity?: number;
  type?: number;
  close_away_value?: number;
}
