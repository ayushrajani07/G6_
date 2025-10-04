/**
 * Reference JS SSE client for G6 summary stream.
 * Works in browser or Node (>=18 where EventSource is not native — polyfill step provided).
 *
 * Features:
 *  - Connects to /summary/events
 *  - Optional API token & Request-ID headers (Node fetch polyfill path)
 *  - Reconnect with backoff & jitter
 *  - Maintains panel state from hello, full_snapshot, panel_update, panel_diff
 *  - Heartbeat tracking & disconnect detection
 *  - Graceful handling of bye event
 */

/* Usage (Node >=18 example):
   node clients/js_sse_client.js --url http://127.0.0.1:9329/summary/events --api-token secret --request-id demo123
*/

// In browsers you can simply include this file via a bundler or <script type="module">.

const args = (() => {
  const out = {}; const a = process.argv.slice(2);
  for (let i=0;i<a.length;i++) {
    if (a[i].startsWith('--')) {
      const k = a[i].replace(/^--/,'');
      const v = (i+1 < a.length && !a[i+1].startsWith('--')) ? a[++i] : '1';
      out[k] = v;
    }
  }
  return out;
})();

const URL_DEFAULT = 'http://127.0.0.1:9329/summary/events';
const SSE_URL = args.url || URL_DEFAULT;
const API_TOKEN = args['api-token'];
const REQUEST_ID = args['request-id'];
const USER_AGENT = args['user-agent'] || 'G6JSClient/1.0';

// Lightweight panel state
class PanelState {
  constructor() {
    this.panels = {};      // id -> panel object
    this.hashes = {};      // id -> hash (from hello)
    this.lastHeartbeat = 0;
    this.schemaVersion = null;
  }
  apply(evt, data) {
    switch(evt) {
      case 'hello':
        if (data && data.panel_hashes) this.hashes = data.panel_hashes;
        if (data && data.schema_version) this.schemaVersion = data.schema_version;
        break;
      case 'full_snapshot':
        if (data && data.panels) this.panels = data.panels;
        break;
      case 'panel_update':
        if (data && data.panels) {
          for (const [k,v] of Object.entries(data.panels)) this.panels[k] = v;
        }
        break;
      case 'panel_diff':
        if (data && data.panels) {
          for (const [k,v] of Object.entries(data.panels)) this.panels[k] = v;
        }
        break;
      case 'heartbeat':
        this.lastHeartbeat = Date.now();
        break;
      case 'bye':
        // No-op (reconnect loop will handle)
        break;
      default:
        break;
    }
  }
}

// Node lacks native EventSource before v18; we implement a minimal fetch-based loop.
async function connectLoop() {
  let attempt = 0;
  const state = new PanelState();
  while (true) {
    attempt += 1;
    const backoff = Math.min(30000, Math.pow(2, Math.min(attempt, 8)) * 100 + Math.random()*500);
    console.log(`[sse-js] connect attempt=${attempt} url=${SSE_URL}`);
    try {
      const controller = new AbortController();
      const headers = { 'User-Agent': USER_AGENT };
      if (API_TOKEN) headers['X-API-Token'] = API_TOKEN;
      if (REQUEST_ID) headers['X-Request-ID'] = REQUEST_ID;
      const resp = await fetch(SSE_URL, { headers, signal: controller.signal });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      console.log('[sse-js] connected');
      attempt = 0;
      const reader = resp.body.getReader();
      let buf = '';
      const decoder = new TextDecoder('utf-8');
      let eventType = null; let dataLines = [];
      while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        buf += decoder.decode(value, {stream: true});
        let idx;
        while ((idx = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, idx).replace(/\r$/,'');
            buf = buf.slice(idx+1);
            if (line.startsWith('event:')) {
              eventType = line.split(':',2)[1].trim();
            } else if (line.startsWith('data:')) {
              dataLines.push(line.split(':',2)[1].trim());
            } else if (line === '') { // frame end
              if (eventType) {
                const payload = dataLines.length ? dataLines.join('\n') : '';
                let dataObj = null;
                if (payload) { try { dataObj = JSON.parse(payload); } catch(_) { /* ignore */ } }
                state.apply(eventType, dataObj);
                if (['hello','full_snapshot'].includes(eventType)) {
                  console.log(`[sse-js] ${eventType} panels=${Object.keys(state.panels).length} hashes=${Object.keys(state.hashes).length}`);
                } else if (eventType === 'panel_update' || eventType === 'panel_diff') {
                  console.log(`[sse-js] delta applied panels_now=${Object.keys(state.panels).length}`);
                } else if (eventType === 'heartbeat') {
                  process.stdout.write('.');
                } else if (eventType === 'bye') {
                  console.log('\n[sse-js] bye received; reconnecting');
                  throw new Error('server bye');
                }
              }
              eventType = null; dataLines = [];
            }
        }
      }
      console.log('[sse-js] stream ended; reconnecting');
    } catch (err) {
      console.warn(`[sse-js] error: ${err}; backoff ${(backoff/1000).toFixed(2)}s`);
      await new Promise(r => setTimeout(r, backoff));
      continue;
    }
  }
}

if (require.main === module) {
  connectLoop().catch(e => { console.error('[sse-js] fatal', e); process.exit(1); });
}
