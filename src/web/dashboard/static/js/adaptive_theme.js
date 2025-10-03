/* Adaptive Theme Fetcher & Renderer
 * Fetches /adaptive/theme from catalog_http server (9315 by default) and applies CSS variables + renders counts & trend.
 */
 (function(){
  const STATE = { last: null, history: [], paused: false, useSSE: true, lastUpdateTs: 0 };
  const DEFAULT_ENDPOINT = (window.G6 && window.G6.adaptive && window.G6.adaptive.endpoint) || 'http://127.0.0.1:9315/adaptive/theme';
  const SSE_ENDPOINT = DEFAULT_ENDPOINT.replace(/\/adaptive\/theme$/, '/adaptive/theme/stream');
  let REFRESH_MS = (window.G6 && window.G6.adaptive && window.G6.adaptive.refreshMs) || 3000;
  const MAX_HISTORY = 120; // extended for timeline (≈6m)

  function $(sel){ return document.querySelector(sel); }
  function fmt(n){ if(n===undefined||n===null) return '-'; return n; }

  function ensureContainers(){
    if(!$('#adaptive-theme-root')){
      const root = document.createElement('div');
      root.id = 'adaptive-theme-root';
      root.innerHTML = `
        <div class="adaptive-theme-panel">
          <div class="adaptive-theme-header">
            <span class="title">Adaptive Alerts Severity</span>
            <span class="update" id="adaptive-theme-updated"></span>
          </div>
          <div class="palette" id="adaptive-theme-palette"></div>
          <div class="controls" id="adaptive-theme-controls">
            <button id="adaptive-pause" class="btn-sm">Pause</button>
            <label>Refresh:
              <select id="adaptive-refresh">
                <option value="1000">1s</option>
                <option value="2000">2s</option>
                <option value="3000" selected>3s</option>
                <option value="5000">5s</option>
                <option value="10000">10s</option>
              </select>
            </label>
            <span id="adaptive-health" class="health indeterminate" title="Endpoint health">●</span>
          </div>
          <div class="counts" id="adaptive-theme-counts"></div>
          <canvas id="adaptive-theme-timeline" height="54"></canvas>
          <div class="trend" id="adaptive-theme-trend"></div>
          <div class="per-type" id="adaptive-theme-pertype"></div>
          <div class="meta" id="adaptive-theme-meta"></div>
        </div>`;
      document.body.appendChild(root);
    }
  }

  function applyPalette(palette){
    if(!palette) return;
    const rootStyle = document.documentElement.style;
    rootStyle.setProperty('--g6-color-info', palette.info || '#6BAF92');
    rootStyle.setProperty('--g6-color-warn', palette.warn || '#FFC107');
    rootStyle.setProperty('--g6-color-critical', palette.critical || '#E53935');
  }

  function renderCounts(active){
    const el = $('#adaptive-theme-counts');
    if(!el) return;
    const info = active && active.info || 0;
    const warn = active && active.warn || 0;
    const critical = active && active.critical || 0;
    el.innerHTML = `
      <span class="badge info" title="Active info">I:${info}</span>
      <span class="badge warn" title="Active warn">W:${warn}</span>
      <span class="badge critical" title="Active critical">C:${critical}</span>`;
  }

  function renderPalette(palette){
    const el = $('#adaptive-theme-palette');
    if(!el) return;
    el.innerHTML = Object.keys(palette||{}).map(k=>`<span class="swatch ${k}" title="${k}">${k}</span>`).join('');
  }

  function computeRatios(history){
    if(!history.length) return { warn:0, critical:0 };
    const window = history[history.length-1];
    return {
      warn: window.warn_ratio !== undefined ? window.warn_ratio : 0,
      critical: window.critical_ratio !== undefined ? window.critical_ratio : 0
    };
  }

  function renderTrend(trend){
    const el = $('#adaptive-theme-trend');
    if(!el) return;
    if(!trend || !trend.snapshots){ el.textContent = 'No trend yet'; return; }
    const critSeries = trend.snapshots.map(s=> (s.counts ? s.counts.critical : (s.critical||0)) ).slice(-60);
    const warnSeries = trend.snapshots.map(s=> (s.counts ? s.counts.warn : (s.warn||0)) ).slice(-60);
    function spark(arr, paletteVar){
      if(!arr.length) return '';
      const max = Math.max(...arr,1);
      const chars = '▁▂▃▄▅▆▇█';
      return arr.map(v=>chars[Math.min(chars.length-1, Math.floor((v/max)*(chars.length-1)))]).join('');
    }
    const ratios = computeRatios(trend.snapshots);
    el.innerHTML = `<div class="sparkline"><label>Critical</label><span class="spark critical">${spark(critSeries,'--g6-color-critical')}</span></div>
      <div class="sparkline"><label>Warn</label><span class="spark warn">${spark(warnSeries,'--g6-color-warn')}</span></div>
      <div class="ratios">r_crit=${ratios.critical.toFixed(2)} r_warn=${ratios.warn.toFixed(2)}</div>`;
  }

  function renderPerTypeFull(perTypeMap){
    const el = $('#adaptive-theme-pertype'); if(!el) return;
    if(!perTypeMap || !Object.keys(perTypeMap).length){ el.innerHTML=''; return; }
    const rows = Object.keys(perTypeMap).sort().map(k=>{
      const st = perTypeMap[k]||{}; const lvl = st.active||'info';
      const age = st.age!==undefined? st.age : '-';
      const resolved = st.resolved_count!==undefined? st.resolved_count : 0;
      return `<tr data-adaptive-alert-type="${k}"><td>${k}</td><td class="lvl ${lvl}">${lvl}</td><td>${age}</td><td>${resolved}</td></tr>`;
    }).join('');
    el.innerHTML = `<table class="per-type-table"><thead><tr><th>Type</th><th>Active</th><th>Age</th><th>Resolved</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  function extractLatestPerTypeFromTrend(trend){
    if(!trend || !trend.snapshots || !trend.snapshots.length) return {};
    const latest = trend.snapshots[trend.snapshots.length-1];
    return latest.per_type || {};
  }

  function drawTimeline(){
    const canvas = $('#adaptive-theme-timeline');
    if(!canvas) return;
    const ctx = canvas.getContext('2d');
    if(!ctx) return;
    const snaps = (STATE.last && STATE.last.trend && STATE.last.trend.snapshots) || [];
    const W = canvas.width = canvas.clientWidth || 360;
    const H = canvas.height;
    ctx.clearRect(0,0,W,H);
    if(!snaps.length) return;
    const slice = snaps.slice(-Math.min(snaps.length, W));
    const step = W / slice.length;
    slice.forEach((s,i)=>{
      const counts = s.counts || s;
      const crit = counts.critical||0; const warn = counts.warn||0; const info = counts.info||0;
      const total = Math.max(1, crit+warn+info);
      const x = Math.floor(i*step);
      // info base
      const infoH = Math.round((info/total)*H);
      const warnH = Math.round((warn/total)*H);
      const critH = Math.round((crit/total)*H);
      let y = H;
      // draw info
      ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--g6-color-info').trim() || '#6BAF92';
      ctx.fillRect(x, y-infoH, Math.ceil(step), infoH); y -= infoH;
      ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--g6-color-warn').trim() || '#FFC107';
      ctx.fillRect(x, y-warnH, Math.ceil(step), warnH); y -= warnH;
      ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--g6-color-critical').trim() || '#E53935';
      ctx.fillRect(x, y-critH, Math.ceil(step), critH);
    });
  }

  function renderMeta(data){
    const el = $('#adaptive-theme-meta');
    if(!el) return;
    const smooth = data && data.smoothing_env && data.smoothing_env.smooth;
    const win = data && data.smoothing_env && data.smoothing_env.trend_window;
    const cr = data && data.smoothing_env && data.smoothing_env.critical_ratio;
    const wr = data && data.smoothing_env && data.smoothing_env.warn_ratio;
    el.innerHTML = `mode: ${smooth? 'smooth':'immediate'} | window=${fmt(win)} | crit_ratio>=${fmt(cr)} | warn_ratio>=${fmt(wr)}`;
  }

  function updateHealth(ok){
    const h = $('#adaptive-health'); if(!h) return;
    if(ok){
      const age = (Date.now() - STATE.lastUpdateTs)/1000;
      h.className = 'health ' + (age < REFRESH_MS*1.5/1000 ? 'good' : 'stale');
    } else {
      h.className = 'health bad';
    }
  }

  function applyUpdate(data){
    STATE.last = data;
    STATE.lastUpdateTs = Date.now();
    applyPalette(data.palette);
    renderPalette(data.palette);
    renderCounts(data.active_counts);
  renderTrend(data.trend);
  const perType = data.per_type || extractLatestPerTypeFromTrend(data.trend);
  renderPerTypeFull(perType);
  highlightHighestSeverity(perType);
    renderMeta(data);
    drawTimeline();
    injectBadges();
    const ts = new Date();
    const up = $('#adaptive-theme-updated'); if(up) up.textContent = ts.toLocaleTimeString();
    updateHealth(true);
  }

  async function poll(){
    try{
      if(STATE.paused) { setTimeout(poll, REFRESH_MS); return; }
      const resp = await fetch(DEFAULT_ENDPOINT, { cache: 'no-store' });
      if(!resp.ok) throw new Error('HTTP '+resp.status);
      const data = await resp.json();
      applyUpdate(data);
    }catch(e){
      const up = $('#adaptive-theme-updated'); if(up) up.textContent = 'err';
      console.warn('adaptive_theme poll failed', e);
      updateHealth(false);
    }finally{
      setTimeout(poll, REFRESH_MS);
    }
  }

  function injectStyles(){
    if(document.getElementById('adaptive-theme-styles')) return;
    const style = document.createElement('style');
    style.id = 'adaptive-theme-styles';
    style.textContent = `:root { --g6-color-info:#6BAF92; --g6-color-warn:#FFC107; --g6-color-critical:#E53935; }
#adaptive-theme-root { position:relative; margin:12px 0; font-family: system-ui, Arial, sans-serif; }
.adaptive-theme-panel { border:1px solid #ddd; border-radius:6px; padding:8px 10px; background:#fff; max-width:420px; box-shadow:0 1px 3px rgba(0,0,0,0.08); }
.adaptive-theme-header { display:flex; align-items:center; justify-content:space-between; font-size:14px; margin-bottom:4px; }
.adaptive-theme-header .title { font-weight:600; }
.palette { margin:4px 0 6px; }
.palette .swatch { display:inline-block; padding:4px 8px; margin-right:6px; border-radius:4px; font-size:12px; color:#222; background:var(--g6-color-info); }
.palette .swatch.warn { background:var(--g6-color-warn); }
.palette .swatch.critical { background:var(--g6-color-critical); color:#fff; }
.controls { display:flex; align-items:center; gap:8px; margin:4px 0 6px; font-size:12px; }
.controls .btn-sm { padding:2px 8px; font-size:12px; cursor:pointer; }
.health { font-size:14px; }
.health.good { color:#29b351; }
.health.stale { color:#c68c1d; }
.health.bad { color:#d32f2f; }
.health.indeterminate { color:#999; }
.counts { margin:4px 0; font-size:13px; }
.counts .badge { display:inline-block; margin-right:6px; padding:2px 6px; border-radius:12px; background:#eee; font-weight:600; }
.counts .badge.info { background:var(--g6-color-info); color:#fff; }
.counts .badge.warn { background:var(--g6-color-warn); color:#222; }
.counts .badge.critical { background:var(--g6-color-critical); color:#fff; }
.trend { font-family: monospace; font-size:12px; line-height:1.2; background:#fafafa; padding:6px; border-radius:4px; border:1px solid #eee; }
.trend .sparkline { margin-bottom:4px; display:flex; align-items:center; gap:6px; }
.trend .spark { background:rgba(0,0,0,0.02); padding:2px 4px; border-radius:3px; }
.per-type { margin-top:6px; max-height:140px; overflow:auto; }
.per-type-table { width:100%; border-collapse:collapse; font-size:11px; }
.per-type-table th { text-align:left; border-bottom:1px solid #ddd; position:sticky; top:0; background:#fff; }
.per-type-table td { padding:2px 4px; }
.per-type-table td.lvl.info { color: var(--g6-color-info); font-weight:600; }
.per-type-table td.lvl.warn { color: var(--g6-color-warn); font-weight:600; }
.per-type-table td.lvl.critical { color: var(--g6-color-critical); font-weight:600; }
.g6-adaptive-highlight { outline:1px solid var(--g6-color-critical); box-shadow:0 0 0 1px var(--g6-color-critical); }
.meta { font-size:11px; margin-top:6px; color:#555; }
@media (prefers-color-scheme: dark) { .adaptive-theme-panel { background:#1e1f26; border-color:#333; color:#e2e2e2; } .trend { background:#2a2b32; border-color:#3a3b42; } .counts .badge { opacity:0.9; } }
`;
    document.head.appendChild(style);
  }

  function injectBadges(){
    try {
      const counts = (STATE.last && STATE.last.active_counts) || {};
      const errPanel = document.querySelector('#panel-errors')?.closest('.grid-stack-item');
      if(!errPanel) return;
      const header = errPanel.querySelector('.panel-header .title');
      if(!header) return;
      const badgeId = 'adaptive-severity-badge';
      let span = header.querySelector('#'+badgeId);
      if(!span){ span = document.createElement('span'); span.id = badgeId; span.style.marginLeft='8px'; span.style.fontSize='12px'; header.appendChild(span); }
      span.textContent = `[C:${counts.critical||0} W:${counts.warn||0}]`;
    }catch(_){ }
  }

  function applyDiff(diff){
    if(!STATE.last) return;
    const base = STATE.last;
    if(diff.active_counts) base.active_counts = diff.active_counts;
    if(diff.per_type){
      base.per_type = base.per_type || {};
      Object.keys(diff.per_type).forEach(k=>{ base.per_type[k] = diff.per_type[k]; });
    }
    if(diff.trend){
      base.trend = base.trend || {};
      if(diff.trend.critical_ratio!==undefined) base.trend.critical_ratio = diff.trend.critical_ratio;
      if(diff.trend.warn_ratio!==undefined) base.trend.warn_ratio = diff.trend.warn_ratio;
      if(diff.trend.latest){
        try {
          base.trend.snapshots = base.trend.snapshots || [];
          base.trend.snapshots.push({ counts: diff.trend.latest, per_type: base.per_type||{} });
          const win = base.trend.window || 50;
          if(base.trend.snapshots.length > win){ base.trend.snapshots = base.trend.snapshots.slice(-win); }
        } catch(e){}
      }
    }
  }

  function highlightHighestSeverity(perType){
    try {
      const order = { info:0, warn:1, critical:2 };
      let topType=null; let topLvl=-1;
      Object.keys(perType||{}).forEach(k=>{ const lvl=perType[k].active||'info'; const v=order[lvl]||0; if(v>topLvl){ topLvl=v; topType=k; }});
      if(!topType || topLvl<1) return; // highlight only warn/critical
      document.querySelectorAll('[data-adaptive-alert-type].g6-adaptive-highlight').forEach(n=> n.classList.remove('g6-adaptive-highlight'));
      document.querySelectorAll(`[data-adaptive-alert-type="${topType}"]`).forEach(el=>{ el.classList.add('g6-adaptive-highlight'); });
    }catch(_){ }
  }

  function startSSE(){
    try {
      const es = new EventSource(SSE_ENDPOINT);
      es.onmessage = (ev)=>{
        if(STATE.paused) return;
  try { const data = JSON.parse(ev.data); if(data && data.diff){ applyDiff(data); applyUpdate(STATE.last); } else { applyUpdate(data); } } catch(e){ console.warn('adaptive_theme SSE parse', e); }
      };
      es.onerror = ()=>{ es.close(); STATE.useSSE = false; poll(); };
    } catch(e){ STATE.useSSE = false; poll(); }
  }

  function bindControls(){
    const pauseBtn = $('#adaptive-pause');
    const sel = $('#adaptive-refresh');
    if(pauseBtn){
      pauseBtn.addEventListener('click', ()=>{
        STATE.paused = !STATE.paused;
        pauseBtn.textContent = STATE.paused ? 'Resume' : 'Pause';
      });
    }
    if(sel){ sel.addEventListener('change', ()=>{ REFRESH_MS = parseInt(sel.value,10)||3000; }); }
  }

  function init(){
    injectStyles();
    ensureContainers();
    bindControls();
    // Prefer SSE; fallback to polling
    if(STATE.useSSE){ startSSE(); } else { poll(); }
  }

  if(document.readyState === 'complete' || document.readyState === 'interactive'){
    init();
  } else {
    document.addEventListener('DOMContentLoaded', init);
  }
})();
