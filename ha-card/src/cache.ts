import {decodeMask,SCALAR_CONTROLS,SPECIAL_MAPS} from './protocol.ts';
import type {HomeAssistant,PanelState} from './types.ts';
export interface ConfigurationSnapshot {version:1;node:string;entity_prefix:string;savedAt:number;zones:PanelState['zones'];specialMaps:PanelState['specialMaps'];scalars:PanelState['scalars']}
export function snapshot(state:PanelState,node:string,prefix:string):ConfigurationSnapshot {
 return {version:1,node,entity_prefix:prefix,savedAt:Date.now(),zones:structuredClone(state.zones),specialMaps:structuredClone(state.specialMaps),scalars:structuredClone(state.scalars)};
}
export function validateSnapshot(value:unknown,node:string,prefix:string):ConfigurationSnapshot|null {
 try{const x=value as ConfigurationSnapshot;if(x?.version!==1||x.node!==node||x.entity_prefix!==prefix||!Number.isFinite(x.savedAt)||x.savedAt<=0||!x.zones||!x.specialMaps||!x.scalars)return null;
 for(const [key,z]of Object.entries(x.zones)){if(String(z.id)!==key||!Number.isInteger(z.id)||z.id<1||z.id>30||z.kind!=='zone'||!['active_raw','sensitivity','type','close_away_raw'].every(k=>Number.isInteger((z as any)[k])))return null;decodeMask(z.mask);}
 for(const [key,m]of Object.entries(x.specialMaps)){if(String(m.attribute)!==key||m.kind!=='map'||!SPECIAL_MAPS.some(s=>s.attribute===m.attribute))return null;decodeMask(m.mask);}
 for(const [key,s]of Object.entries(x.scalars)){if(String(s.attribute)!==key||s.kind!=='scalar'||!SCALAR_CONTROLS.some(c=>c.attribute===s.attribute)||!Number.isInteger(s.raw)||!Number.isInteger(s.wire))return null;}
 if(Object.keys(x.zones).length!==30||Object.keys(x.specialMaps).length!==3||Object.keys(x.scalars).length!==4)return null;
 const copy=structuredClone(x);for(const group of [copy.zones,copy.specialMaps,copy.scalars])for(const item of Object.values(group))item.fresh=false;return copy;
 }catch{return null;}
}
export async function loadSnapshot(hass:HomeAssistant,path:string,node:string,prefix:string){const config=await hass.callWS({type:'lovelace/config',url_path:path});return validateSnapshot(config.fp2_configuration_cache?.[node],node,prefix);}
export async function saveSnapshot(hass:HomeAssistant,path:string,value:ConfigurationSnapshot){
 // Fetch immediately before a narrowly scoped update: preserve every existing view/card.
 const config=await hass.callWS({type:'lovelace/config',url_path:path});
 config.fp2_configuration_cache={...config.fp2_configuration_cache,[value.node]:value};
 await hass.callWS({type:'lovelace/config/save',url_path:path,config});
}
