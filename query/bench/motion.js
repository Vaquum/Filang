// Motion for the canvas drawings. A scene keeps its marks between redraws; each mark's numbers are driven
// to their new targets by one damped spring (stiffness 180, damping 20, as the style guide declares).
// A new target keeps the current position and velocity, so an interrupted change continues without a jump.
// Only geometry moves. Printed values are set at once and never count up.
import { s } from '/shared/chart.js';

const STIFFNESS = 180; const DAMPING = 20;
const scenes = new WeakMap(); const active = new Set();
let raf = 0; let last = 0;
const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
/** Motion is skipped for reduced-motion readers and while the page is not visible. */
const still = () => reduce.matches || document.hidden;

let lastTick = 0; let watching = false;

function tick(now) {
  const dt = Math.min(0.034, last ? (now - last) / 1000 : 0.016); last = now; lastTick = performance.now();
  for (const sc of active) if (!sc.step(dt)) { active.delete(sc); sc.svg.classList.remove('moving'); }
  if (active.size) raf = requestAnimationFrame(tick); else { raf = 0; last = 0; }
}
/** Put every moving mark at its target now. The drawing is then exact, whatever the frame clock is doing. */
export function settleAll() {
  for (const sc of active) sc.settle();
  active.clear();
  if (raf) cancelAnimationFrame(raf);
  raf = 0; last = 0;
}
// Browsers stop animation frames for pages that are not on screen. A frozen mid-move drawing would misstate
// the data, so a watchdog settles the scenes whenever frames have stalled.
function watchdog() {
  watching = false;
  if (!active.size) return;
  if (performance.now() - lastTick > 160) settleAll(); else { watching = true; setTimeout(watchdog, 220); }
}
document.addEventListener('visibilitychange', () => { if (document.hidden) settleAll(); });

class Scene {
  constructor(host, layers) {
    this.svg = s('svg', { role: 'img' }); this.layers = {}; this.items = new Map(); this.fresh = true; this.swaps = {};
    for (const name of layers) { this.layers[name] = s('g'); this.svg.append(this.layers[name]); }
    host.replaceChildren(this.svg);
  }
  size(W, H) { this.W = W; this.H = H; this.svg.setAttribute('viewBox', `0 0 ${W} ${H}`); this.svg.setAttribute('width', W); this.svg.setAttribute('height', H); }
  begin() { for (const it of this.items.values()) it.seen = false; }
  /** Declare one mark. `values` is its geometry as a flat list of numbers; `apply` writes them to the element. */
  put(key, layer, make, values, apply, cls) {
    let it = this.items.get(key);
    if (!it || it.tgt.length !== values.length) {
      if (it) it.el.remove();
      const el = make(); this.layers[layer].append(el);
      it = { el, cur: Float64Array.from(values), vel: new Float64Array(values.length), tgt: Float64Array.from(values), cls: null };
      this.items.set(key, it);
      if (cls !== undefined) { el.setAttribute('class', cls + (this.fresh || still() ? '' : ' m-enter')); it.cls = cls; }
      apply(el, it.cur);
    } else {
      it.tgt.set(values);
      if (cls !== undefined && it.cls !== cls) { it.el.setAttribute('class', cls); it.cls = cls; }
    }
    it.apply = apply; it.seen = true;
  }
  /** Replace an unkeyed group (the density cells) with a short cross-fade. */
  swap(layer, group) {
    const old = this.swaps[layer]; const quiet = this.fresh || still();
    if (old) { if (quiet || !group) old.remove(); else { old.classList.add('m-exit'); setTimeout(() => old.remove(), 180); } }
    if (group) { if (!quiet && old) group.classList.add('m-enter'); this.layers[layer].append(group); }
    this.swaps[layer] = group || null;
  }
  end() {
    for (const [key, it] of this.items) if (!it.seen) { this.items.delete(key); if (still()) it.el.remove(); else { it.el.classList.add('m-exit'); setTimeout(() => it.el.remove(), 180); } }
    this.fresh = false;
    if (still()) { this.settle(); active.delete(this); return; }
    this.svg.classList.add('moving'); active.add(this);
    if (!raf) { lastTick = performance.now(); raf = requestAnimationFrame(tick); }
    if (!watching) { watching = true; setTimeout(watchdog, 220); }
  }
  settle() { for (const it of this.items.values()) { it.cur.set(it.tgt); it.vel.fill(0); it.apply(it.el, it.cur); } this.svg.classList.remove('moving'); }
  step(dt) {
    let moving = false;
    for (const it of this.items.values()) {
      const { cur, vel, tgt } = it; let changed = false;
      for (let i = 0; i < cur.length; i++) {
        const d = cur[i] - tgt[i];
        if (Math.abs(d) < 0.04 && Math.abs(vel[i]) < 0.4) { if (d !== 0) { cur[i] = tgt[i]; changed = true; } vel[i] = 0; continue; }
        vel[i] += (-STIFFNESS * d - DAMPING * vel[i]) * dt; cur[i] += vel[i] * dt; changed = true; moving = true;
      }
      if (changed) it.apply(it.el, cur);
    }
    return moving;
  }
}

/** The scene for a host element, created on first use. */
export function sceneFor(host, layers) {
  let sc = scenes.get(host);
  if (!sc || !host.contains(sc.svg)) { sc = new Scene(host, layers); scenes.set(host, sc); }
  return sc;
}
