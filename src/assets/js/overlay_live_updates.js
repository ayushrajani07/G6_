(function(){
  const W = window;
  if(!W.G6){ W.G6 = {}; }
  if(!W.G6.overlay){ W.G6.overlay = {}; }
  const O = W.G6.overlay;

  // Registry of graphs to update
  O.registry = O.registry || new Map(); // id -> { layoutMode, meta }

  O.registerGraph = function(divId, opts){
    try{
      const el = document.getElementById(divId);
      if(!el){ console.warn('G6 overlay: missing div', divId); return; }
      O.registry.set(divId, { opts: opts||{} });
    }catch(e){ console.warn('G6 overlay: register failed', e); }
  }

  // No-op polling unless endpoint provided
  O.startPolling = function(cfg){
    const endpoint = cfg && cfg.endpoint;
    const intervalMs = (cfg && cfg.intervalMs) || 5000;
    if(!endpoint){ console.info('G6 overlay: live polling disabled (no endpoint)'); return; }
    if(O._timer){ clearInterval(O._timer); }
    O._timer = setInterval(async ()=>{
      try{
        const res = await fetch(endpoint, { cache: 'no-store' });
        if(!res.ok){ return; }
        const payload = await res.json();
        // Expected payload: { panels: { [divId]: { x:[], y:[] | { tp_live:[], avg_tp_live:[], ... }, layout?:{} } } }
        const panels = (payload && payload.panels) || {};
        Object.keys(panels).forEach(divId => {
          const el = document.getElementById(divId);
          if(!el) return;
          const p = panels[divId];
          if(!p) return;
          const x = p.x || [];
          const y = p.y;
          const updates = [];
          // Helper: ensure traces exist if figure started empty
          const ensureTraces = (el, xArr, yObjOrArr) => {
            try{
              const data = el.data || [];
              if(data && data.length){ return; }
              // If no traces yet, add at least a 'tp live' trace
              let traces = [];
              const BLUE = '#1f77b4';
              const ORANGE = '#ff7f0e';
              if(Array.isArray(yObjOrArr)){
                traces.push({ x: xArr, y: yObjOrArr, name: 'tp live', line: { color: BLUE, width: 2 }, mode: 'lines' });
              } else if (yObjOrArr && typeof yObjOrArr === 'object'){
                if(yObjOrArr.tp_live){ traces.push({ x: xArr, y: yObjOrArr.tp_live, name: 'tp live', line: { color: BLUE, width: 2 }, mode: 'lines' }); }
                if(yObjOrArr.tp_mean){ traces.push({ x: xArr, y: yObjOrArr.tp_mean, name: 'tp mean', line: { color: BLUE, dash: 'dash' }, mode: 'lines' }); }
                if(yObjOrArr.tp_ema){ traces.push({ x: xArr, y: yObjOrArr.tp_ema, name: 'tp ema', line: { color: BLUE, dash: 'dot' }, mode: 'lines' }); }
                if(yObjOrArr.avg_tp_live){ traces.push({ x: xArr, y: yObjOrArr.avg_tp_live, name: 'avg_tp live', line: { color: ORANGE, width: 2 }, mode: 'lines' }); }
                if(yObjOrArr.avg_tp_mean){ traces.push({ x: xArr, y: yObjOrArr.avg_tp_mean, name: 'avg_tp mean', line: { color: ORANGE, dash: 'dash' }, mode: 'lines' }); }
                if(yObjOrArr.avg_tp_ema){ traces.push({ x: xArr, y: yObjOrArr.avg_tp_ema, name: 'avg_tp ema', line: { color: ORANGE, dash: 'dot' }, mode: 'lines' }); }
              }
              if(traces.length){ Plotly.addTraces(el, traces); }
            }catch(_){}
          };
          ensureTraces(el, x, y);
          // If present, extend traces by matching name suffixes; fallback softly
          try{
            const data = el.data || [];
            // Build a suffix map (match end of name so 'NIFTY... tp live' works)
            const suffixIndex = {};
            data.forEach((tr,i)=>{ if(tr && tr.name){ suffixIndex[tr.name] = i; } });
            const findBySuffix = (suffix) => {
              const keys = Object.keys(suffixIndex);
              for(let k of keys){ if(k.endsWith(suffix)) return suffixIndex[k]; }
              return undefined;
            };
            const tryUpdate = (suffix, arr)=>{
              if(!arr) return;
              const idx = findBySuffix(suffix);
              if(idx===undefined){ return; }
              updates.push({ idx, x, y: arr });
            };
            if(Array.isArray(y)){
              // Single series fallback → extend ' tp live'
              tryUpdate(' tp live', y);
            } else if (y && typeof y === 'object'){
              tryUpdate(' tp live', y.tp_live);
              tryUpdate(' tp mean', y.tp_mean);
              tryUpdate(' tp ema', y.tp_ema);
              tryUpdate(' avg_tp live', y.avg_tp_live);
              tryUpdate(' avg_tp mean', y.avg_tp_mean);
              tryUpdate(' avg_tp ema', y.avg_tp_ema);
            }
            if(updates.length){
              updates.forEach(u=>{ Plotly.extendTraces(el, { x:[u.x], y:[u.y] }, [u.idx]); });
            }
          }catch(e){
            // Soft fallback
          }
          if(p.layout){ Plotly.relayout(el, p.layout); }
        });
      }catch(e){ /* swallow */ }
    }, intervalMs);
  };

  // Theme handling
  O.setTheme = function(theme){
    const t = (theme || '').toLowerCase();
    const root = document.documentElement;
    if(t === 'dark'){ root.setAttribute('data-theme','dark'); }
    else { root.removeAttribute('data-theme'); }
    try{ localStorage.setItem('g6_theme', t || 'light'); }catch(_){ }
  };
  O.initTheme = function(defaultTheme){
    // If a defaultTheme is explicitly provided, honor it; otherwise fallback to saved preference
    let t = defaultTheme || 'light';
    if(!defaultTheme){
      try{ t = localStorage.getItem('g6_theme') || t; }catch(_){ }
    }
    O.setTheme(t);
  };
})();
