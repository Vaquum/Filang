/* Use the existing market-data worker. A named scan is independent of the paper's holds, drawing and forecast. */
function installPatternBrowser(request, timeframeNames) {
  const $ = id => document.getElementById(id);
  const dialog = $('pattern-browser'), search = $('pattern-filter'), list = $('pattern-list'), frame = $('pattern-frame');
  const title = $('pattern-title'), rule = $('pattern-rule'), status = $('pattern-status'), results = $('pattern-results');
  const send = $('send-named');
  let current = null, serial = 0;
  const dates = new Intl.DateTimeFormat('en-GB', {dateStyle:'medium', timeStyle:'short', timeZone:'UTC'});
  for (const name of timeframeNames) frame.add(new Option(name, name));
  const normalize = s => s.normalize('NFKC').trim().toLowerCase();
  function select(id) {
    current = CandlePatterns.resolve(id);
    results.replaceChildren();
    const aliases = $('pattern-aliases');
    aliases.textContent = current?.aliases.length ? 'Also listed as ' + current.aliases.join(' · ') : '';
    aliases.hidden = !aliases.textContent;
    if (send) send.disabled = !current;
    if (!current) {
      title.textContent = 'No matching name'; rule.textContent = ''; status.textContent = '';
      serial++;
      return;
    }
    title.textContent = current.name + ' · ' + current.ja;
    rule.textContent = current.rule;
    status.textContent = 'Reading BTCUSDT ' + frame.value + ' bars…';
    if (send) send.dataset.pattern = current.id;
    request({id: ++serial, pattern: current.id, timeframe: frame.value});
  }
  function filter(preferred) {
    const text = normalize(search.value);
    const shown = CandlePatterns.patterns.filter(p =>
      [p.id, p.name, p.ja, ...p.aliases].some(n => normalize(n).includes(text)));
    list.replaceChildren(...shown.map(p => new Option(p.name + ' · ' + p.ja, p.id)));
    if (shown.some(p => p.id === preferred)) list.value = preferred;
    select(list.value);
  }
  function open(id) {
    if (!dialog.open) dialog.showModal();
    search.value = '';
    filter(id || current?.id || 'hammer');
    search.focus();
  }
  search.addEventListener('input', () => filter(current?.id));
  list.addEventListener('change', () => select(list.value));
  frame.addEventListener('change', () => select(list.value));
  $('browse-patterns').addEventListener('click', () => open());
  $('close-patterns').addEventListener('click', () => dialog.close());
  dialog.addEventListener('keydown', e => {
    e.stopPropagation();
    if (e.key === 'Escape') { e.preventDefault(); dialog.close(); }
  });
  $('names').addEventListener('click', e => {
    const button = e.target.closest('button[data-pattern]');
    if (button) open(button.dataset.pattern);
  });
  const inbound = new URLSearchParams(location.search).get('pattern');
  if (inbound !== null) {
    if (CandlePatterns.resolve(inbound)) open(CandlePatterns.resolve(inbound).id);
    else {
      dialog.showModal(); filter(); search.value = inbound; list.selectedIndex = -1;
      select(''); title.textContent = 'Unknown pattern'; rule.textContent = 'Choose a catalog entry to start a search.'; search.focus();
    }
  }
  return {
    ready() { if (dialog.open && current) select(current.id); },
    failed(message) { if (dialog.open && current) status.textContent = message; },
    result(m) {
      if (m.id !== serial || !current) return;
      if (m.error) { status.textContent = m.error; return; }
      status.textContent = m.count.toLocaleString('en-GB') + ' matching closes among ' +
        m.eligible.toLocaleString('en-GB') + ' complete ' + frame.value + ' windows. ' +
        (m.samples.length ? 'Most recent first, in UTC.' : '');
      const price = cents => (cents / 100).toFixed(2);
      results.replaceChildren(...m.samples.map(s => {
        const item = document.createElement('details'), summary = document.createElement('summary');
        summary.textContent = dates.format(new Date(s.close * 1000)) + ' UTC';
        item.append(summary);
        for (const [i, row] of s.bars.entries()) {
          const p = document.createElement('p');
          p.textContent = 'Bar ' + (i+1) + ' · ' + ['Open','High','Low','Close'].map((name,k) => name + ' ' + price(row[k])).join(' · ');
          item.append(p);
        }
        return item;
      }));
    }
  };
}
