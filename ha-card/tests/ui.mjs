// Isolated rendering acceptance. Synthetic layout; never connects to Home Assistant.
import {chromium} from '@playwright/test';
import {createServer} from 'node:http';
import {readFile,mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
const root=fileURLToPath(new URL('../../',import.meta.url));
const module=await readFile(root+'ha-card/dist/fp2-local-card.js');
const html=`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FP2 card layout test</title><style>:root{--primary-text-color:#172b3a;--secondary-text-color:#627889;--primary-color:#148593;--divider-color:#dce5ea;--card-background-color:#fff;--ha-card-background:#fff;--secondary-background-color:#f1f6f8}body{font-family:system-ui;margin:0;padding:24px;background:#eaf0f3}main{max-width:1120px;margin:auto}.demo{font-size:12px;color:#526875;margin:0 0 14px}fp2-glance-card{display:block;max-width:400px;margin-top:20px;background:white;border-radius:16px}</style><main><p class="demo">Interface demonstration · synthetic layout, not a household capture</p><fp2-local-card></fp2-local-card><fp2-glance-card></fp2-glance-card></main><script type="module" src="/card.js"></script></html>`;
const server=createServer((req,res)=>{res.setHeader('Content-Type',req.url==='/card.js'?'text/javascript':'text/html');res.end(req.url==='/card.js'?module:html);});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const browser=await chromium.launch({headless:true,args:['--mute-audio']});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[];
 page.on('pageerror',e=>errors.push(String(e)));
 await page.addInitScript(()=>{Date.now=()=>Date.UTC(2026,0,1,12);});
 await page.goto(`http://127.0.0.1:${server.address().port}`);
 await page.waitForFunction(()=>customElements.get('fp2-local-card'));
 await page.evaluate(async()=>{
  const cards=[document.querySelector('fp2-local-card'),document.querySelector('fp2-glance-card')];
  const hass={language:'en',states:{},connection:{connected:true,subscribeEvents:async()=>()=>{}},callWS:async()=>({}),callService:async()=>{throw Error('Unexpected hardware action')}};
  for(const card of cards){card.setConfig({node:'fp2',entity_prefix:'fp2',language:'en'});card.hass=hass;await card.updateComplete;card.client.dispose();
   const mask=(fn)=>Array.from({length:40},(_,b)=>Array.from({length:8},(_,i)=>fn(Math.floor((b*8+i)/16),(b*8+i)%16)?128>>i:0).reduce((a,b)=>a+b,0).toString(16).padStart(2,'0')).join('');
   const shapes=[(r,c)=>r<5,(r,c)=>r>=5&&r<10&&c<8,(r,c)=>r>=5&&r<10&&c>=8,(r,c)=>r>=10];
   const zones=Object.fromEntries(shapes.map((fn,i)=>[i+1,{kind:'zone',id:i+1,mask:mask(fn),active_raw:1,sensitivity:1,type:0,close_away_raw:0,source:'radar_ram',fresh:true,seenAt:Date.now(),observed_ms:1}]));
   card.state={...card.state,zones,occupancy:{1:'off',2:'on',3:'off',4:'off'},zoneNames:{1:'Zone 1',2:'Zone 2',3:'Zone 3',4:'Zone 4'},room:'on',traffic:'on',deviceFresh:true,illuminance:'42',configurationStatus:'idle',cacheSavedAt:Date.now(),targets:{items:[{id:1,a_hundredths:200,b_hundredths:400,flag_raw:0,raw_hex:'0100c80190000000000000000202'}],receivedAt:Date.now(),sequence:17,count:1},notice:null};card.requestUpdate();await card.updateComplete;
  }
 });
 await page.getByText('Presence map',{exact:true}).waitFor();
 await page.locator('fp2-local-card').getByText('Sensitivity',{exact:false}).first().waitFor();
 await mkdir(root+'.tools/ui',{recursive:true});
 await page.locator('fp2-local-card').screenshot({path:root+'.tools/ui/editor-en.png'});
 await page.locator('fp2-glance-card').screenshot({path:root+'.tools/ui/glance-en.png'});
 await page.setViewportSize({width:390,height:844});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'mobile overflow');
 await page.screenshot({path:root+'.tools/ui/mobile-en.png',fullPage:true});
 await page.evaluate(async()=>{for(const card of document.querySelectorAll('fp2-local-card,fp2-glance-card')){card.setConfig({language:'ru'});await card.updateComplete;}});
 await page.locator('fp2-local-card').getByText('Карта присутствия',{exact:true}).waitFor();
 assert.deepEqual(errors,[]);
 console.log('English/Russian browser rendering, zone controls and mobile layout passed (isolated synthetic fixture).');
}finally{await browser.close();await new Promise(r=>server.close(r));}
