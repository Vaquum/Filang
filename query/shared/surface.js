// The surface of the Vaquum instruments: navy or warm stock. Shared verbatim by Composer, Query and Cube.
// Loaded as a classic script in <head>, before the stylesheets apply, so the first paint is already on the right
// surface. The reader's choice is one cookie on .vaquum.fi, so it holds on every instrument; until one is chosen,
// the system's light or dark setting decides, and a change to it is followed at once.
// On navy it also marks <body> "night", the class the shared base.css's drawings take their navy colours from.
(() => {
  const root = document.documentElement;
  const NAME = 'vq-surface';
  const system = matchMedia('(prefers-color-scheme: light)');
  const chosen = () => /(?:^|;\s*)vq-surface=(navy|stock)(?:;|$)/.exec(document.cookie)?.[1] || null;
  const night = () => document.body?.classList.toggle('night', root.dataset.surface === 'navy');
  const apply = () => { const c = chosen(); root.dataset.surface = c || (system.matches ? 'stock' : 'navy'); root.dataset.surfaceChoice = c || 'auto'; night(); label(); };
  /** Keep a surface on every vaquum.fi instrument, or forget the choice and follow the system again. */
  function choose(mode) {
    const domain = location.hostname.endsWith('.vaquum.fi') ? '; domain=.vaquum.fi' : '';
    const secure = location.protocol === 'https:' ? '; secure' : '';
    document.cookie = mode ? `${NAME}=${mode}; path=/; max-age=31536000; samesite=lax${domain}${secure}` : `${NAME}=; path=/; max-age=0; samesite=lax${domain}${secure}`;
    apply();
    window.dispatchEvent(new CustomEvent('vq-surface', { detail: root.dataset.surface }));
  }
  // The switch walks: follow the system, navy, stock. It names what it shows, and what a press does next.
  const NEXT = { auto: 'navy', navy: 'stock', stock: null };
  const WORD = { auto: 'Auto', navy: 'Navy', stock: 'Stock' };
  function label() {
    const c = root.dataset.surfaceChoice; const now = root.dataset.surface;
    for (const b of document.querySelectorAll('[data-surface-toggle]')) {
      b.querySelector('[data-surface-word]').textContent = WORD[c];
      const next = NEXT[c];
      b.title = `${c === 'auto' ? `Following the system: ${now}` : `Kept on ${now}`}. Press for ${next ? WORD[next].toLowerCase() : 'the system’s choice'}.`;
      b.setAttribute('aria-label', `Surface: ${WORD[c]}${c === 'auto' ? `, now ${now}` : ''}`);
    }
  }
  apply();
  system.addEventListener('change', () => { if (!chosen()) { apply(); window.dispatchEvent(new CustomEvent('vq-surface', { detail: root.dataset.surface })); } });
  document.addEventListener('DOMContentLoaded', () => {
    night();
    for (const b of document.querySelectorAll('[data-surface-toggle]')) b.addEventListener('click', () => choose(NEXT[root.dataset.surfaceChoice] || null));
    label();
  });
  window.vqSurface = { choose, now: () => root.dataset.surface };
})();
