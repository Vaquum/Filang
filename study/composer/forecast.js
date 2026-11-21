'use strict';
// Sequence probabilities use every complete matching window; candle drawings are historical examples.
const ForecastViews = (() => {
  const states = ['U', 'I', 'D'];
  const names = { U: 'Above', I: 'Inside', D: 'Below' };
  const words = key => [...key].map(s => names[s]).join(' → ');
  const percent = x => `${(100 * x).toFixed(1).replace(/\.0$/, '')}%`;
  const count = new Intl.NumberFormat('en-GB').format;
  function rate(k, n) {
    if (n < 30) return null;
    const z = 1.959964, p = k / n, d = 1 + z * z / n;
    const c = (p + z * z / (2 * n)) / d, h = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d;
    return [p, c - h, c + h];
  }
  const label = w => w ? percent(w[0]) : '–';
  const evidence = (k, n) => `${count(k)} / ${count(n)} complete windows`;
  const interval = (k, n) => {
    const w = rate(k, n);
    return evidence(k, n) + (w ? ` · 95% interval ${percent(w[1])}–${percent(w[2])}` : ' · fewer than 30 supporting windows; no probability estimate');
  };
  function subset(c, prefix = '') {
    const sequences = c.sequences.filter(([key]) => key.startsWith(prefix));
    return { sequences, n: sequences.reduce((sum, [, n]) => sum + n, 0) };
  }
  function outcomes(c, prefix = '') {
    const set = subset(c, prefix), steps = c.fan.length;
    const grid = Array.from({ length: steps }, () => [0, 0, 0]);
    for (const [key, n] of set.sequences) for (let j = 0; j < steps; j++) grid[j][states.indexOf(key[j])] += n;
    return { ...set, grid };
  }
  function crumbs(prefix) {
    return `<div class="forecast-crumbs"><button type="button" data-prefix="" aria-label="Return to the current combo">Current combo</button>${[...prefix].map((s, j) => `<span aria-hidden="true">›</span><button type="button" data-prefix="${prefix.slice(0, j + 1)}" title="Bar +${j + 1} closes ${names[s].toLowerCase()}" aria-label="Return to ${words(prefix.slice(0, j + 1))}">+${j + 1} ${s === 'U' ? '↑' : s === 'D' ? '↓' : '•'}</button>`).join('')}</div>`;
  }
  function mini(example) {
    if (!example) return '';
    const lo = Math.min(...example.bars.map(b => b[2])), hi = Math.max(...example.bars.map(b => b[1]));
    const y = v => 3 + (hi - v) / (hi - lo || 1) * 42, x = j => (j + 0.5) * 40;
    return `<svg viewBox="0 0 ${example.bars.length * 40} 48" preserveAspectRatio="none" aria-hidden="true">${example.bars.map(([o, h, l, c], j) => `<g class="${c > o ? 'cu' : c < o ? 'cd' : 'cz'}"><rect x="${x(j) - 1}" y="${y(h)}" width="2" height="${Math.max(1, y(l) - y(h))}"/><rect x="${x(j) - 7}" y="${y(Math.max(o, c))}" width="14" height="${Math.max(1, Math.abs(y(o) - y(c)))}" rx="1"/></g>`).join('')}</svg>`;
  }
  function paths(c, prefix = '', selected = '') {
    const set = subset(c, prefix), leaders = set.sequences.slice(0, 4);
    const other = set.n - leaders.reduce((sum, [, n]) => sum + n, 0);
    const steps = c.fan.length;
    return `<div class="forecast-caption">${prefix ? 'Given these choices' : 'Whole-sequence probability'} · ${count(set.n)} windows</div><div class="forecast-path-head"><span>Probability</span><span class="forecast-steps">${Array.from({ length: steps }, (_, j) => `<span>+${j + 1}</span>`).join('')}</span></div>` + leaders.map(([key, n]) => `<button type="button" class="forecast-path" data-path="${key}" aria-pressed="${key === selected}" aria-label="${words(key)}: ${interval(n, set.n)}" title="${interval(n, set.n)}"><strong>${label(rate(n, set.n))}</strong><span class="forecast-mini">${mini(c.examples?.[key])}<span class="forecast-steps">${[...key].map(s => `<span title="${names[s]}">${s === 'U' ? '↑' : s === 'D' ? '↓' : '•'}</span>`).join('')}</span></span></button>`).join('') + `<div class="forecast-caption forecast-other">${Math.max(0, set.sequences.length - leaders.length)} other sequences · ${label(rate(other, set.n))}</div>`;
  }
  function branches(c, prefix = '') {
    const set = outcomes(c, prefix), j = prefix.length;
    if (j === c.fan.length) return `<div class="forecast-complete"><span>Complete sequence</span><strong>${label(rate(set.n, c.n))}</strong><span>of all matched windows</span><button type="button" data-prefix="${prefix.slice(0, -1)}">Back one bar</button></div>`;
    const children = set.grid[j];
    const links = children.map((n, i) => `<path d="M2 108 C27 108 25 ${36 + i * 72} 50 ${36 + i * 72}" stroke-width="${set.n ? Math.max(.6, 10 * n / set.n) : .6}"/>`).join('');
    return `<div class="forecast-caption">Bar +${j + 1} · ${count(set.n)} supporting windows</div><div class="forecast-branch-list"><svg viewBox="0 0 52 216" preserveAspectRatio="none" aria-hidden="true">${links}</svg>${states.map((s, i) => `<button type="button" class="forecast-branch" data-prefix="${prefix + s}" ${!children[i] ? 'disabled' : ''} title="${interval(children[i], set.n)}"><span>${names[s]} <strong>${label(rate(children[i], set.n))}</strong></span><small>${label(rate(children[i], c.n))} overall · ${count(children[i])} windows</small></button>`).join('')}</div>`;
  }
  function grid(c, prefix = '') {
    const set = outcomes(c, prefix), steps = c.fan.length;
    const cells = states.map((s, i) => `<tr><th scope="row">${names[s]}</th>${Array.from({ length: steps }, (_, j) => {
      const k = set.grid[j][i], w = rate(k, set.n), chosen = j < prefix.length;
      const info = chosen ? (prefix[j] === s ? 'Selected outcome; use the trail to go back' : 'Excluded by the selected path') : interval(k, set.n);
      return `<td><button type="button" class="forecast-cell" data-step="${j}" data-state="${s}" ${j === prefix.length && k ? `data-prefix="${prefix + s}"` : ''} data-evidence="${info}" aria-pressed="${chosen && prefix[j] === s}" aria-label="Bar +${j + 1} ${names[s]}: ${info}${j === prefix.length && k ? '; choose this outcome' : '; inspect probability'}" title="${info}" style="--odds:${chosen ? (prefix[j] === s ? .24 : 0) : w ? .05 + .30 * w[0] : 0}">${chosen ? (prefix[j] === s ? '✓' : '–') : label(w)}</button></td>`;
    }).join('')}</tr>`).join('');
    return `<div class="forecast-caption">${prefix ? 'Given the selected path' : 'Close versus the combo range'} · ${count(set.n)} windows</div><table aria-label="Future close probabilities relative to the current combo range"><thead><tr><th scope="col">Close</th>${Array.from({ length: steps }, (_, j) => `<th scope="col">+${j + 1}</th>`).join('')}</tr></thead><tbody>${cells}</tbody></table>`;
  }
  function fan(c) {
    const metrics = [['High broken', c.aboveHigh], ['Low broken', c.belowLow], ['Closed above last close', c.aboveClose]];
    return `<div class="forecast-caption">Next ${c.fan.length} bars · all ${count(c.n)} matched windows</div><div class="forecast-fan-rates">${metrics.map(([name, w]) => `<div class="forecast-fan-rate"><span>${name}</span><strong>${label(w)}</strong><small>${w ? `95% ${percent(w[1])}–${percent(w[2])}` : 'No estimate'}</small></div>`).join('')}</div><div class="forecast-caption">A continuation can break both levels.</div>`;
  }
  function detail(c, prefix, selected, view) {
    const set = subset(c, prefix), sequence = c.sequences.find(([key]) => key === selected);
    if (view === 'fan') return '<strong>Close distribution · all matched windows</strong><p>Outer band: middle 80% · inner band: middle 50% · line: median.</p><p>Branches and Grid follow your choices; the fan shows the full cohort.</p>';
    const n = view === 'paths' && sequence ? sequence[1] : set.n, denominator = view === 'paths' ? set.n : c.n;
    if (denominator < 30) return `<strong>${count(denominator)} supporting windows</strong><p>Estimates need at least 30. Counts remain available on each outcome.</p>`;
    const conditional = view === 'branches' && prefix.length < c.fan.length && set.n < 30
      ? `<p>Next-bar estimates need 30 supporting windows; ${count(set.n)} remain. Counts are available on each outcome.</p>` : '';
    return `<strong>${view === 'paths' ? 'Selected sequence' : prefix ? 'Selected path so far' : 'Follow a branch'} · ${label(rate(n, denominator))}${view === 'branches' ? ' overall' : ''}</strong><p>${prefix || view === 'paths' ? words(view === 'paths' ? selected : prefix) : 'Choose Above, Inside or Below to reveal the following bar.'}</p><p>${interval(n, denominator)}${view === 'paths' ? '<br>Candles are a historical example, not the odds of exact prices.' : ''}</p>${conditional}`;
  }
  function empty(view) {
    const n = view === 'paths' ? 4 : 3;
    return `<div class="forecast-skeleton" aria-hidden="true">${Array.from({ length:n }, () => '<div><i></i><span>–</span></div>').join('')}</div>`;
  }
  function emptyGrid() {
    return `<table aria-hidden="true"><thead><tr><th>Close</th>${Array.from({length:6},(_,j)=>`<th>+${j+1}</th>`).join('')}</tr></thead><tbody>${states.map(s=>`<tr><th>${names[s]}</th>${Array.from({length:6},()=>'<td><span class="forecast-cell forecast-cell-empty">–</span></td>').join('')}</tr>`).join('')}</tbody></table>`;
  }
  // A response is committed atomically. Temporary absence never clears the previous snapshot or its selections.
  function reconcile(previous, { fresh, failed, data, key }) {
    let source = previous.source, sourceKey = previous.sourceKey || '', prefix = previous.prefix || '', selected = previous.selected || '';
    if (fresh && !failed) {
      source = data || null;
      if (key !== sourceKey) prefix = '';
      sourceKey = key;
      if (source) {
        while (prefix && !subset(source, prefix).n) prefix = prefix.slice(0, -1);
        const set = previous.view === 'paths' || previous.view === 'states' ? source : subset(source, prefix);
        if (!set.sequences.some(([p]) => p === selected)) selected = set.sequences[0]?.[0] || '';
      } else { prefix = ''; selected = ''; }
    }
    const current = fresh && !failed;
    const phase = failed ? 'error' : !fresh ? source ? 'refreshing' : 'loading' : source ? 'ready' : 'sparse';
    return { source, sourceKey, prefix, selected, current, phase };
  }
  // Geometry depends only on the viewport and input modality, never on loading, mode, Grid or result content.
  function layout(w, lx, top, coarse = false) {
    const width = Math.min(580, Math.max(0, w - 24));
    // Grid evidence can wrap to several lines on a phone; reserve it before any results arrive.
    const height = (coarse ? 488 : 400) + (width <= 420 ? 42 : 0);
    return { height, width, left: Math.max(12, Math.min(lx + 12, w - width - 12)), reserve: height + 16, minHeight: Math.ceil(top + height + 260) };
  }
  // The forecast owns a probability gutter at every width. Mode and candle width never affect it.
  function geometry(w,n) {
    const base=Math.max(6,Math.min(52,w*.052));
    const x0=n<=2?Math.max(16,w*.12):Math.max(12,w*.06);
    const spacing=n<=2?Math.max(28,Math.max(44,w*.11)*.99):Math.max(3,(w*.35-x0)/(n-1));
    const baseBw=Math.min(base,spacing*.75),xs=Array.from({length:n},(_,i)=>x0+i*spacing);
    const forecastLeft=xs[n-1]+baseBw/2,end=w-40;
    const nominal=(end-forecastLeft)/6,gap=w<700?18:24,rateWidth=w<700?30:42;
    const maxRootRight=xs[n-1]+baseBw*.6;
    const tentativeWidth=Math.max(12,Math.min(baseBw*1.1,nominal*.62));
    const first=Math.max(forecastLeft+nominal,maxRootRight+18+rateWidth+gap+tentativeWidth/2);
    const fanStep=(end-first)/5,futureXs=Array.from({length:6},(_,i)=>first+i*fanStep);
    const forecastWidth=Math.max(4,Math.min(tentativeWidth,fanStep*.62));
    return {xs,spacing,baseBw,forecastLeft,fanStep,futureXs,forecastWidth,gap,rateWidth};
  }
  function field(G) {
    const height=Math.min(230,G.plotH*.75),top=G.plotTop+G.plotH*.52-height/2;
    const xs=G.futureXs,width=G.forecastWidth,left=xs[0]-width/2,right=xs[5]+width/2;
    const rateRight=left-G.gap,rateLeft=rateRight-G.rateWidth;
    return {xs,width,left,right,top,height,rateRight,rateLeft,rowTop:top+24,rowHeight:(height-48)/4,
      branchTop:top+25,branchHeight:(height-29)/3,rateFont:G.w<700?11:14};
  }
  const definition = 'Above means the future close is strictly above the matched combo’s highest wick; Below means strictly below its lowest wick; Inside includes both boundaries. These are closing states, not candle colour or wick crossings.';
  const cohortDefinition = 'Historical BTCUSDT windows admitted by the current matching settings, including held constraints, selected timeframes, stretch and next-bar filters. Only windows with all six continuous following bars contribute.';
  function pathTip(c,key) {
    const n=c.sequences.find(([p])=>p===key)?.[1]||0;
    const p=rate(n,c.n);
    return `${words(key)}. Probability of this entire six-bar closing-state sequence: ${p?percent(p[0]):'no estimate'}; ${interval(n,c.n)}. All ${count(c.n)} complete matched windows contribute; the six percentages are not multiplied independently. ${definition} ${cohortDefinition}`;
  }
  function stateTip(c,prefix,j,s,set=outcomes(c,prefix)) {
    const k=set.grid[j][states.indexOf(s)],prior=prefix? `Given ${words(prefix)} at the earlier bars; `:'Given the current combo; ';
    const p=rate(k,set.n);
    return `Bar +${j+1}, ${names[s]}: ${p?percent(p[0]):'no estimate'}. ${prior}${interval(k,set.n)}. This is the close at this bar, not a whole-path probability. ${definition} ${cohortDefinition}`;
  }
  function fanTip(c,j=null,q=null) {
    let text='Closing-price distribution of matching historical continuations, normalized to each combo’s range: low = 0, high = 1. The five lines are the 10th, 25th, 50th (median), 75th and 90th percentiles. Outer lines contain the middle 80% and inner lines the middle 50% at each individual bar, not a whole-path confidence region.';
    if(j!==null&&q!==null)text=`Bar +${j+1}: ${[10,25,50,75,90][q]}th percentile = ${c.fan[j][q].toFixed(2)} combo heights. `+text;
    return text+` Fan quantiles use ${count(c.sampled??c.n)} sampled complete continuations; probability views use all ${count(c.n)} complete windows. +1…+6 are bars in each selected timeframe, not a fixed elapsed duration. Branch choices do not condition the fan.`;
  }

  return { states, names, words, percent, rate, interval, subset, outcomes, crumbs, paths, branches, grid, fan, detail, empty, emptyGrid, reconcile, layout, geometry, field, definition, pathTip, stateTip, fanTip };
})();
