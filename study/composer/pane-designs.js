// Presentation of the matcher's results. HTML and retained updates share formatting.
// changing a layout never changes the cohort or recomputes a statistic.
const PaneDesigns = (() => {
  const variants = [
    { id: 'signal', name: 'Signal first' },
    { id: 'ledger', name: 'Comparison ledger' },
    { id: 'bars', name: 'Bar by bar' },
  ];
  const names = { vol: 'Volume', trades: 'Trades', size: 'Mean trade size', maker: 'Maker volume share', range: 'Range', body: 'Body', day: 'Close in prior-day range' };
  const groups = { vol: 'Activity', trades: 'Activity', size: 'Trade size', maker: 'Aggression', range: 'Movement', body: 'Movement', day: 'Location' };
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = n => Number(n).toLocaleString('en-US');
  const pct = x => `${(x * 100).toFixed(1)}%`;
  const f2 = x => x.toFixed(2).replace('-', '−');
  const label = w => names[w.key];
  const value = (w, x) => w.log ? `${Math.exp(x).toFixed(2)}×` : w.key === 'maker' ? pct(x) : w.key === 'day' ? `${(x * 100).toFixed(0)}%` : f2(x);
  const unit = w => w.key === 'body' || w.key === 'range' ? ' ATR' : '';
  const readingContext=w=>`Bar ${w.bar+1}${unit(w)?' · ATR':w.log?' · vs prior 11':''}`;
  const displayed = (w, x) => value(w, x) + unit(w);
  const sorted = P => (P.rows || []).slice().sort((a, b) => Math.abs(b.d) - Math.abs(a.d));
  const clear = w => w.set[1] > w.all[0] || w.set[2] < w.all[0];
  const ledgerNote=rows=>`${rows.filter(clear).length} of ${rows.length} intervals exclude the all-window mean.`;
  const detail = (key, title, content, open = false) => `<details class="pane-details" data-detail="${key}"${open ? ' open' : ''}><summary>${title}</summary>${content}</details>`;
  const legend = () => '<div class="pane-legend"><span><i class="legend-dot" aria-hidden="true"></i>Selected</span><span><i class="legend-band" aria-hidden="true"></i>95% interval</span><span><i class="legend-tick" aria-hidden="true"></i>All</span></div>';
  const formattedReadings=new WeakMap();
  function trackFields(w) {
    const cached=formattedReadings.get(w),mean=w.set[0];
    const lo = w.set[1], hi = w.set[2], ref = w.all[0], a = Math.min(lo, ref), b = Math.max(hi, ref);
    if(cached&&cached.key===w.key&&cached.log===w.log&&cached.mean===mean&&cached.lo===lo&&cached.hi===hi&&cached.ref===ref)return cached.fields;
    const pad = (b - a) * .6 || .05, mn = a - pad, mx = b + pad, at = x => (x - mn) / (mx - mn) * 100;
    const selected=value(w,mean),baseline=value(w,ref),selectedDisplay=selected+unit(w),baselineDisplay=baseline+unit(w);
    const fields={selected,baseline,selectedDisplay,baselineDisplay,
      aria:`Selected mean ${selectedDisplay}; 95% interval ${displayed(w,lo)} to ${displayed(w,hi)}; all-window mean ${baselineDisplay}`,band:`left:${at(lo)}%;width:${at(hi)-at(lo)}%`,dot:`left:${at(mean)}%`,reference:`left:${at(ref)}%`};
    formattedReadings.set(w,{key:w.key,log:w.log,mean,lo,hi,ref,fields});return fields;
  }
  function track(w, f=trackFields(w)) {
    return `<div class="trk" role="img" aria-label="${f.aria}"><i class="bd" style="${f.band}"></i><i class="dt" style="${f.dot}"></i><i class="tk" style="${f.reference}"></i></div>`;
  }
  function reading(w, showBar = true, retained = null, destination = '') {
    if(retained?.has(`${destination}|${w.bar}-${w.key}`))return `<div class="prow" data-reading="${w.bar}-${w.key}"></div>`;
    const f=trackFields(w);
    return `<div class="prow" data-reading="${w.bar}-${w.key}"><div class="pl"><span>${showBar ? 'Bar '+(w.bar+1)+' · ' : ''}${label(w)}</span><b>${f.selectedDisplay}</b></div><div class="pane-reading-bottom">${track(w,f)}<span class="pane-baseline">All ${f.baselineDisplay}</span></div></div>`;
  }
  const difference = w => {
    if (w.key === 'maker' || w.key === 'day') { const d = (w.set[0]-w.all[0])*100; return `${d > 0 ? '+' : ''}${d.toFixed(1).replace('-','−')} pp`; }
    const ratio = w.log ? Math.exp(w.set[0]-w.all[0]) : w.all[0] > 0 ? w.set[0]/w.all[0] : null;
    return ratio === null ? '' : `${ratio.toFixed(1)}× as large`;
  };
  function table(rows) {
    return `<table class="pane-ledger"><caption class="sr-only">Selected-window means compared with all-window means</caption><thead><tr><th>Reading</th><th>Selected</th><th>All</th></tr></thead><tbody>${rows.map(w=>`<tr class="prow" data-reading="${w.bar}-${w.key}"><td>${label(w)}<small>${readingContext(w)}</small></td><td>${trackFields(w).selected}</td><td>${trackFields(w).baseline}</td></tr>`).join('')}</tbody></table>`;
  }
  function left(variant, r, ctx) {
    const P = r.panes, all = sorted(P), first = all.slice(0,10);
    if (P.n < 30) return '<p class="pcap">Fewer than 30 windows: no estimate.</p>';
    if (!P.readings) return `<p class="pcap">${ctx.readings === 'failed' ? 'Activity readings unavailable: '+esc(ctx.note)+'.' : 'Reading activity…'}</p>`;
    if (!all.length) return '<p class="pcap">Not enough measured activity for these readings.</p>';
    if (variant === 'bars') {
      return legend()+Array.from({length:ctx.barCount},(_,bar)=>{
        const rows = all.filter(w=>w.bar === bar), lead = rows[0];
        return detail('bar-'+bar, `<strong>Bar ${bar+1}</strong><span class="pane-bar-summary">${lead ? `${label(lead)} <b>${displayed(lead,lead.set[0])}</b> · all ${displayed(lead,lead.all[0])}` : 'No estimate for this bar'}</span>`,rows.map(w=>reading(w,false)).join(''),bar === 0);
      }).join('')+'<p class="pane-note">Activity and trade size are relative to the prior 11 bars.</p>';
    }
    const remaining = all.length > 10 ? detail('more', `${all.length-10} more readings`, variant === 'ledger' ? table(all.slice(10)) : all.slice(10).map(w=>reading(w,true,ctx.retainedReadings,'more')).join('')) : '';
    if (variant === 'ledger') {
      return '<p class="pane-order">Largest differences first</p>'+table(first)+`<p class="pane-note">${ledgerNote(first)}</p>`+remaining+detail('intervals',`95% intervals · all ${all.length} readings`,legend()+all.map(w=>reading(w)).join(''));
    }
    const lead = first[0], delta = difference(lead), rest = first.slice(1);
    return `<div class="pane-hero" data-reading="${lead.bar}-${lead.key}"><p class="pane-hero-label">Largest difference · Bar ${lead.bar+1} ${label(lead).toLowerCase()}</p><p class="pane-hero-value">${value(lead,lead.set[0])}<span class="pane-unit">${unit(lead)}</span></p><p class="pane-hero-compare">All ${displayed(lead,lead.all[0])}${delta ? ' · <strong>'+delta+'</strong>' : ''}</p>${track(lead)}</div>`+legend()+
      [...new Set(rest.map(w=>groups[w.key]))].map(group=>`<section class="pane-group" data-motion-key="group-${group}"><h3>${group}${group === 'Activity' || group === 'Trade size' ? '<span class="pane-unit">vs prior 11 bars</span>' : ''}</h3>${rest.filter(w=>groups[w.key]===group).map(w=>reading(w,true,ctx.retainedReadings,'group-'+group)).join('')}</section>`).join('')+remaining;
  }
  // Used only after the caller verifies unchanged layout/identity. Bindings live
  // in Flow's markup entry, so a structural patch releases old DOM references.
  function updateSignal(root,r,memo){
    const rows=new Map((r.panes.rows||[]).map(w=>[`${w.bar}-${w.key}`,w]));
    if(!memo){
      const nodes=[...root.querySelectorAll('[data-reading]')];
      if(nodes.length!==rows.size||!nodes.length)return false;
      memo=nodes.map(node=>{
        const hero=node.classList.contains('pane-hero'),track=node.querySelector('.trk');
        const binding={node,key:node.dataset.reading,hero,value:hero?node.querySelector('.pane-hero-value')?.firstChild:node.querySelector('.pl b')?.firstChild,
          baseline:hero?node.querySelector('.pane-hero-compare')?.firstChild:node.querySelector('.pane-baseline')?.firstChild,
          delta:hero?node.querySelector('.pane-hero-compare strong'):null,track,band:track?.querySelector('.bd'),dot:track?.querySelector('.dt'),reference:track?.querySelector('.tk')};
        if(!hero)retainedReadings.set(node,{value:binding.value,baseline:binding.baseline,track,band:binding.band,dot:binding.dot,reference:binding.reference});
        return binding;
      });
    }
    if(memo.length!==rows.size||memo.some(b=>!rows.has(b.key)||b.node.dataset.reading!==b.key||![b.node,b.value,b.baseline,b.track,b.band,b.dot,b.reference,...(b.delta?[b.delta]:[])].every(n=>n&&root.contains(n))))return false;
    const text=(node,value)=>{if(node.nodeValue!==value)node.nodeValue=value;},attribute=(node,name,value)=>{if(node.getAttribute(name)!==value)node.setAttribute(name,value);};
    for(const b of memo){
      const w=rows.get(b.key),f=trackFields(w),delta=b.hero?difference(w):'';
      text(b.value,b.hero?f.selected:f.selectedDisplay);
      text(b.baseline,`All ${f.baselineDisplay}${b.hero&&delta?' · ':''}`);
      if(b.delta&&b.delta.textContent!==delta)b.delta.textContent=delta;
      attribute(b.track,'aria-label',f.aria);attribute(b.band,'style',f.band);attribute(b.dot,'style',f.dot);attribute(b.reference,'style',f.reference);
    }
    return memo;
  }
  const retainedReadings=new WeakMap();
  function readingUpdater(r){
    const rows=new Map((r.panes.rows||[]).map(w=>[`${w.bar}-${w.key}`,w]));
    return (node,next)=>{
      if(!['DIV','TR'].includes(node.nodeName)||node.nodeName!==next.nodeName||node.className!=='prow'||next.className!=='prow'||node.dataset.reading!==next.dataset.reading)return null;
      const w=rows.get(node.dataset.reading);if(!w)return null;
      let b=retainedReadings.get(node);
      if(!b){
        if(node.nodeName==='TR')b={value:node.children[1]?.firstChild,baseline:node.children[2]?.firstChild,label:node.children[0]?.firstChild,context:node.children[0]?.querySelector('small')?.firstChild};
        else {const track=node.querySelector('.trk');b={value:node.querySelector('.pl b')?.firstChild,baseline:node.querySelector('.pane-baseline')?.firstChild,
          track,band:track?.querySelector('.bd'),dot:track?.querySelector('.dt'),reference:track?.querySelector('.tk')};}
        retainedReadings.set(node,b);
      }
      if(!Object.values(b).every(n=>n&&node.contains(n))||b.value.nodeType!==3||b.baseline.nodeType!==3)return null;
      const f=trackFields(w);
      return ()=>{
        const text=(n,v)=>{if(n.nodeValue!==v)n.nodeValue=v;},attr=(n,k,v)=>{if(n.getAttribute(k)!==v)n.setAttribute(k,v);};
        text(b.value,b.track?f.selectedDisplay:f.selected);text(b.baseline,b.track?`All ${f.baselineDisplay}`:f.baseline);
        if(b.context){text(b.label,label(w));text(b.context,readingContext(w));}
        if(b.track){attr(b.track,'aria-label',f.aria);attr(b.band,'style',f.band);attr(b.dot,'style',f.dot);attr(b.reference,'style',f.reference);}
      };
    };
  }
  // Reuse only rows whose validated bindings stay in the same keyed parent.
  // Rows crossing the hero/visible/more boundary keep their full representation.
  function signalTemplate(root,r,ctx,retain){
    const retainedReadings=new Set();
    for(const node of root.querySelectorAll('div.prow[data-reading]')){
      const parent=node.parentElement;
      const destination=parent.dataset.motionKey||(parent.classList.contains('flow-detail-content')&&parent.closest('details')?.dataset.detail==='more'?'more':null);
      if(destination&&retain(node,node))retainedReadings.add(`${destination}|${node.dataset.reading}`);
    }
    return retainedReadings.size?left('signal',r,{...ctx,retainedReadings}):null;
  }
  function updateBars(root,r,barCount){
    const P=r.panes,details=[...root.querySelectorAll(':scope > details[data-detail]')];
    if(P.n<30||!P.readings||details.length!==barCount)return false;
    const groups=Array.from({length:barCount},()=>[]),updater=readingUpdater(r),plans=[];
    for(const w of sorted(P)){if(!groups[w.bar])return false;groups[w.bar].push(w);}
    for(let bar=0;bar<barCount;bar++){
      const detail=details[bar],rows=groups[bar],content=detail.querySelector(':scope > .flow-detail-body > .flow-detail-content'),summary=detail.querySelector('.pane-bar-summary');
      if(detail.dataset.detail!==`bar-${bar}`||!content||!rows.length||summary?.childNodes.length!==3)return false;
      const nodes=[...content.children],byKey=new Map(nodes.map(node=>[node.dataset.reading,node])),ordered=rows.map(w=>byKey.get(`${w.bar}-${w.key}`));
      if(nodes.length!==rows.length||byKey.size!==rows.length||ordered.some(node=>!node))return false;
      const changes=ordered.map(node=>updater(node,node)),[heading,value,baseline]=summary.childNodes;
      if(changes.some(change=>!change)||heading.nodeType!==3||value.nodeName!=='B'||baseline.nodeType!==3)return false;
      plans.push({content,ordered,changes,heading,value,baseline,lead:rows[0]});
    }
    const text=(node,value)=>{if(node.nodeValue!==value)node.nodeValue=value;};
    for(const p of plans){
      for(const change of p.changes)change();
      let cursor=p.content.firstElementChild;for(const node of p.ordered){if(node!==cursor)p.content.insertBefore(node,cursor);cursor=node.nextElementSibling;}
      const f=trackFields(p.lead);text(p.heading,label(p.lead)+' ');if(p.value.textContent!==f.selectedDisplay)p.value.textContent=f.selectedDisplay;text(p.baseline,' · all '+f.baselineDisplay);
    }
    return {kind:'bars'};
  }
  function updateLedger(root,r,move){
    const all=sorted(r.panes),tables=[...root.querySelectorAll('.pane-ledger tbody')],intervals=root.querySelector('details[data-detail="intervals"] .flow-detail-content'),note=root.querySelector(':scope > .pane-note');
    if(r.panes.n<30||!r.panes.readings||!all.length||tables.length!==(all.length>10?2:1)||!intervals||!note)return false;
    const rows=tables.flatMap(body=>[...body.children]),charts=[...intervals.querySelectorAll(':scope > [data-reading]')],keys=all.map(w=>`${w.bar}-${w.key}`);
    const byKey=nodes=>new Map(nodes.map(node=>[node.dataset.reading,node])),tableRows=byKey(rows),chartRows=byKey(charts);
    if(rows.length!==all.length||charts.length!==all.length||tableRows.size!==all.length||chartRows.size!==all.length||keys.some(key=>!tableRows.has(key)||!chartRows.has(key)))return false;
    const updater=readingUpdater(r),changes=[...rows,...charts].map(node=>updater(node,node));if(changes.some(change=>!change))return false;
    const more=root.querySelector('details[data-detail="more"]'),leading=new Set(keys.slice(0,10));
    if(more&&!more.open&&!more.hasAttribute('data-flow-details')){
      for(const node of tables[0].children)if(!leading.has(node.dataset.reading))move?.depart(node);
      for(const key of leading){const node=tableRows.get(key);if(more.contains(node))move?.arrive(node);}
    }
    for(const change of changes)change();
    const order=(parent,nodes,start=parent.firstChild)=>{let cursor=start;for(const node of nodes){if(node!==cursor)parent.insertBefore(node,cursor);cursor=node.nextSibling;}};
    order(tables[0],keys.slice(0,10).map(key=>tableRows.get(key)));
    if(tables[1])order(tables[1],keys.slice(10).map(key=>tableRows.get(key)));
    order(intervals,keys.map(key=>chartRows.get(key)),charts[0]);
    const text=ledgerNote(all.slice(0,10));if(note.textContent!==text)note.textContent=text;
    return {kind:'ledger'};
  }
  function meter(w, direction = 'selected', reference = null) {
    if (!w) return '';
    return `<div class="pane-meter ${direction}" role="img" aria-label="${pct(w[0])}; 95% interval ${pct(w[1])} to ${pct(w[2])}${reference === null ? '' : '; all windows '+pct(reference)}"><i class="meter-fill" style="width:${w[0]*100}%"></i><i class="meter-ci" style="left:${w[1]*100}%;width:${(w[2]-w[1])*100}%"></i><i class="meter-dot" style="left:${w[0]*100}%"></i>${reference === null ? '' : `<i class="meter-reference" style="left:${reference*100}%"></i>`}</div>`;
  }
  const interval = w => w ? `<span class="pane-meta">95% interval ${pct(w[1])}–${pct(w[2])}</span>` : '';
  const rate = (label,w,direction='selected',hero=false) => w ? `<div class="prate${hero ? ' pane-hero' : ''}"><div class="pane-rate-head"><span>${label}</span><b>${pct(w[0])}</b></div>${meter(w,direction)}${interval(w)}</div>` : `<p class="pcap">${label}: no estimate.</p>`;
  function next(r, ctx) {
    if (r.filter) return `<p class="pcap">Filtered to next bars that ${esc(ctx.nextWords(r.filter))}. No rise-rate comparison.</p>`;
    const P = r.panes, w = P.next, ref = r.base.n ? r.base.up/r.base.n : null;
    if (!w) return '<p class="pcap">Fewer than 30 next bars: no estimate.</p>';
    const delta = ref === null ? '' : (w[0]-ref)*100, outside = ref !== null && (w[1]>ref || w[2]<ref);
    const tfs = `<table class="pane-timeframes"><thead><tr><th>Timeframe</th><th>Rose</th><th>Windows</th></tr></thead><tbody>${ctx.timeframes.map(({label,k})=>`<tr><td>${label}</td><td>${P.byTf[k] ? pct(P.byTf[k][0]) : '—'}</td><td>${fmt(P.tfN[k])}</td></tr>`).join('')}</tbody></table><p class="pane-note">— Fewer than 30 next bars.</p>`;
    return `<p class="pane-next-value">${pct(w[0])}</p>${ref === null ? '<p class="pane-note">All-window rate unavailable.</p>' : `<p class="pane-hero-compare">All windows ${pct(ref)} · <strong>${delta>0?'+':''}${delta.toFixed(1).replace('-','−')} pp</strong></p>`}${meter(w,'selected',ref)}${interval(w)}${ref === null ? '' : `<p class="pane-note">${outside ? 'Interval excludes the all-window rate.' : 'Interval overlaps the all-window rate.'}</p>`}${detail('timeframes','By timeframe',tfs)}`;
  }
  function right(variant,r) {
    const P=r.panes,c=P.cont;
    if (!c) return `<p class="pcap">Fewer than 30 complete ${P.after}-bar continuations: no estimate.</p>`;
    const breaks = rate("Broke the shape's high",c.aboveHigh,'up',variant === 'signal')+rate("Broke the shape's low",c.belowLow,'down')+'<p class="pane-note">A window can break both levels.</p>';
    const end = `<section class="pane-group"><h3>At bar ${P.after}</h3>${rate('Closed above the last drawn close',c.aboveClose)}</section>`;
    return variant === 'signal' ? `<section class="pane-group">${breaks}</section>`+end : `<section class="pane-group"><h3>${variant === 'bars' ? 'During the next '+P.after+' bars' : 'Crossed during those '+P.after+' bars'}</h3>${breaks}${variant === 'ledger' ? '<div class="pane-scale"><span>0% of windows</span><span>100%</span></div>' : ''}</section>`+end;
  }
  function terminal(P) {
    const c=P.cont;
    if (!c) return '';
    const q=c.fan[c.fan.length-1], low=q[1], median=q[2], high=q[3];
    const a=Math.min(0,low),b=Math.max(1,high),pad=(b-a)*.12,mn=a-pad,mx=b+pad,at=x=>(x-mn)/(mx-mn)*100;
    return `<section class="pane-group"><h3>Where bar ${P.after} closed</h3><div class="pane-terminal-value"><span>Median</span><strong>${f2(median)}<span class="pane-unit">shape heights</span></strong></div><div class="trk terminal-track" role="img" aria-label="Median close ${f2(median)} shape heights; middle 50% ${f2(low)} to ${f2(high)}. Shape low 0, high 1."><i class="bd" style="left:${at(low)}%;width:${at(high)-at(low)}%"></i><i class="dt" style="left:${at(median)}%"></i><i class="tk" style="left:${at(0)}%"></i><i class="tk" style="left:${at(1)}%"></i></div><p class="pane-note">Middle 50%: ${f2(low)}–${f2(high)}</p><p class="pane-note">Shape's low = 0 · high = 1</p>${c.sampled < c.n ? `<p class="pane-note">Fan sample: ${fmt(c.sampled)} of ${fmt(c.n)} windows. Rates use all windows.</p>` : ''}</section>`;
  }
  function caption(r,ctx) {
    const P=r.panes,n=P.n,kind=P.kind==='hold'?'windows hold your relations':P.kind==='twins'?'exact matches':'closest windows';
    const exact = (r.filter ? r.exactF : r.exact) || [], total = ctx.timeframes.reduce((n,{k})=>n+(exact[k] || 0),0);
    return `<strong>${fmt(n)} ${kind}</strong><span class="pane-meta">${P.kind==='closest' ? `${fmt(total)} exact matches · ` : ''}BTCUSDT · ${ctx.timeframes.map(t=>t.label).join(' / ') || 'No timeframes'}</span>${P.kind==='closest' ? '<span class="pane-meta">Closest windows stand in below 30 exact matches.</span>' : ''}${r.stretch ? `<span class="pane-meta">Up to ${r.stretch} bars skipped</span>` : ''}${r.filter ? `<span class="pane-meta">Next bar ${esc(ctx.nextWords(r.filter))}</span>` : ''}`;
  }
  const leftMethod = barCount => `<ul class="pane-method"><li>All means every ${barCount}-bar window on the selected timeframes. Rows compare selected-window and all-window means.</li><li>Volume, trades and mean trade size: relative to the median of the prior 11 bars; geometric means.</li><li>Body and range: prior-bar Wilder ATR(14). Maker share: share of volume. Last close: position in the prior UTC day's range.</li><li>Every reading track has its own scale. Differences are ranked in standard deviations of all windows.</li><li>95% intervals: t for means, Wilson for rates. No estimate below 30 windows.</li></ul>`;
  const rightMethod = after => `<ul class="pane-method"><li>Each window is scaled from its own low and high to your drawing. The canvas fan shows the median and middle 50% and 80% of closes.</li><li>Breaks count any crossing during the next ${after} bars. Final close compares bar ${after} with the window's last close.</li><li>The terminal band is the middle 50% of closes, not a confidence interval. Outcome rates use all complete continuations, with Wilson 95% intervals.</li></ul>`;
  return { variants, left, updateSignal, readingUpdater, signalTemplate, updateBars, updateLedger, right, next, terminal, caption, leftMethod, rightMethod };
})();
