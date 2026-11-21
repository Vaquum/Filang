'use strict';
// Tactile flow: the same physical model as Poise and Eightchord.
const TactileFlow = (() => {
  const model = Object.freeze({ stiffness: 180, damping: 20, mass: 1, travel: 20, information: 8, feedback: 100 });
  function integrate(position, velocity, target, seconds) {
    if (![position, velocity, target, seconds].every(Number.isFinite) || seconds < 0) throw Error('Tactile flow requires finite values and a non-negative time step.');
    const steps = Math.max(1, Math.ceil(seconds / .008)), dt = seconds / steps;
    for (let i = 0; i < steps; i++) {
      velocity += (-model.stiffness * (position - target) - model.damping * velocity) / model.mass * dt;
      position += velocity * dt;
    }
    return { position, velocity };
  }
  function advance(values, velocities, targets, seconds, epsilon = .002, immediate = false) {
    let busy = false;
    const validTime=Number.isFinite(seconds)&&seconds>=0;
    for (let i = 0; i < targets.length; i++) {
      if(validTime&&values[i]===targets[i]&&velocities[i]===0&&Number.isFinite(values[i]))continue;
      const next = integrate(values[i], velocities[i], targets[i], immediate ? 0 : seconds);
      if (immediate || Math.abs(next.position - targets[i]) <= epsilon && Math.abs(next.velocity) <= epsilon * 10) {
        values[i] = targets[i]; velocities[i] = 0;
      } else { values[i] = next.position; velocities[i] = next.velocity; busy = true; }
    }
    return busy;
  }
  // Spring the center and logarithmic span: zoom may overshoot, but never invert the price axis.
  function bounds(values, velocities, targets, seconds, immediate = false) {
    const span=values[1]-values[0],targetSpan=targets[1]-targets[0];
    if(!(span>0)||!(targetSpan>0))throw Error('Tactile framing requires ordered bounds.');
    if(Number.isFinite(seconds)&&seconds>=0&&Number.isFinite(span)&&Number.isFinite(targetSpan)&&values[0]===targets[0]&&values[1]===targets[1]&&velocities[0]===0&&velocities[1]===0)return false;
    const center=[(values[0]+values[1])/2],cv=[velocities[0]],zoom=[Math.log(span)],zv=[velocities[1]];
    const p=advance(center,cv,[(targets[0]+targets[1])/2],seconds,targetSpan*1e-4,immediate);
    const z=advance(zoom,zv,[Math.log(targetSpan)],seconds,.00001,immediate);
    velocities[0]=cv[0];velocities[1]=zv[0];
    if(p||z){const half=Math.exp(zoom[0])/2;values[0]=center[0]-half;values[1]=center[0]+half;}
    else{values[0]=targets[0];values[1]=targets[1];}
    return p||z;
  }
  if (typeof window === 'undefined') return { model, integrate, advance, bounds };
  const preference = matchMedia('(prefers-reduced-motion: reduce)');
  const owners = new WeakMap(), moving = new Set(), settlers = new Set();
  const pendingLayouts=new Map();
  const layoutObserver=typeof ResizeObserver==='function'?new ResizeObserver(entries=>{for(const {target}of entries)flushLayouts(target);}):null;
  function flushLayouts(root){
    for(const [node,complete]of [...pendingLayouts])if(!root||node===root||node.contains(root)||root.contains(node)){
      pendingLayouts.delete(node);layoutObserver.unobserve(node);complete();
    }
  }
  let visibility=new WeakMap();const observed=new Set(),arrivals=new Set();
  let viewportScroll=[scrollX,scrollY];
  const viewport=typeof IntersectionObserver==='function'?new IntersectionObserver(entries=>{for(const entry of entries)visibility.set(entry.target,entry.isIntersecting);},{rootMargin:'160px'}):null;
  // A separate one-shot sample cannot mistake a queued cache observation for
  // this layout's arrival, and does not depend on browser timestamp precision.
  const arrivalSampler=viewport?new IntersectionObserver(entries=>{
    const entering=new Set(entries.filter(entry=>arrivals.has(entry.target)&&entry.isIntersecting&&entry.target.isConnected&&presented(entry.target)&&!reduced()).map(entry=>entry.target));
    for(const entry of entries){
      arrivalSampler.unobserve(entry.target);
      arrivals.delete(entry.target);
    }
    for(const node of entering){let parent=node.parentElement;while(parent&&!entering.has(parent)&&!owners.get(parent)?.has('entry'))parent=parent.parentElement;if(!parent)reveal(node);}
  },{rootMargin:'160px'}):null;
  function releaseObservers(){for(const node of observed)if(!node.isConnected){viewport.unobserve(node);observed.delete(node);arrivalSampler.unobserve(node);arrivals.delete(node);}}
  function observe(nodes){if(viewport)for(const node of nodes)if(!observed.has(node)){observed.add(node);viewport.observe(node);}}
  function resetVisibility(){
    visibility=new WeakMap();viewportScroll=[scrollX,scrollY];if(!viewport)return;
    viewport.takeRecords();
    releaseObservers();for(const node of observed){viewport.unobserve(node);viewport.observe(node);}
  }
  addEventListener('scroll',resetVisibility,true);addEventListener('resize',resetVisibility);
  let frame = 0, previousTime = 0, suspended = document.hidden, printing = false;
  const reduced = () => preference.matches || suspended || printing;
  const bounded = value => Math.max(0, Math.min(1, value));
  const mark = owner => owner.toggleAttribute('data-motion-running', Boolean(owners.get(owner)?.size));
  function destination(channel) {
    const target = typeof channel.to === 'function' ? channel.to() : channel.to;
    for (const [key, value] of Object.entries(target)) {
      if (!Number.isFinite(value) || !Number.isFinite(channel.value[key])) throw Error(`Tactile flow received non-finite ${channel.name}.${key}.`);
      channel.range[key] = Math.max(channel.range[key] || 1, Math.abs(value - channel.value[key]));
    }
    return target;
  }
  function cancel(owner, name) {
    const channel = owners.get(owner)?.get(name);
    if (!channel) return;
    moving.delete(channel); owners.get(owner).delete(name); mark(owner);
  }
  function complete(channel) {
    if(!channel.owner.isConnected){cancel(channel.owner,channel.name);channel.done();return;}
    const target = destination(channel);
    channel.value = { ...target }; channel.write(target);
    // Remove ownership before callbacks, which may create a new request.
    cancel(channel.owner, channel.name); channel.done();
  }
  function tick(now) {
    const dt = Math.max(0, Math.min(.032, (now - previousTime) / 1000)); previousTime = now;
    for (const channel of [...moving]) {
      if (!moving.has(channel)) continue;
      if (!channel.owner.isConnected) { complete(channel); continue; }
      if (now < channel.start) continue;
      const target = destination(channel); let resting = true;
      for (const [key, goal] of Object.entries(target)) {
        const next = integrate(channel.value[key], channel.velocity[key] || 0, goal, dt);
        channel.value[key] = next.position; channel.velocity[key] = next.velocity;
        if (Math.abs(next.position - goal) > channel.range[key] * .002 || Math.abs(next.velocity) > channel.range[key] * .02) resting = false;
      }
      if (resting || reduced()) complete(channel); else channel.write({ ...channel.value });
    }
    frame = moving.size ? requestAnimationFrame(tick) : 0;
  }
  function spring(owner, name, { from, to, write, done = () => {}, delay = 0, rebase = false }) {
    let own = owners.get(owner);
    if (!own) { own = new Map(); owners.set(owner, own); }
    let channel = own.get(name);
    if (!channel) { channel = { owner, name, value: { ...from }, velocity: {}, range: {} }; own.set(name, channel); }
    else if (rebase) channel.value = { ...from };
    Object.assign(channel, { to, write, done, start: performance.now() + delay });
    destination(channel);
    if (reduced()) { complete(channel); return; }
    moving.add(channel); mark(owner); write({ ...channel.value });
    if (!frame) { previousTime = performance.now(); frame = requestAnimationFrame(tick); }
  }
  function value(owner, name) { const c = owners.get(owner)?.get(name); return c ? { ...c.value } : null; }
  function finish(root) {
    flushLayouts(root);
    for(const node of arrivals)if(!root||node===root||root.contains(node)){arrivalSampler.unobserve(node);arrivals.delete(node);}
    for (const channel of [...moving]) if (moving.has(channel) && (!root || channel.owner === root || root.contains(channel.owner))) complete(channel);
    if (!root) for (const settle of settlers) settle();
  }
  function reveal(element, distance = model.information, delay = 0) {
    element.dataset.flowEnter = '';
    spring(element, 'entry', { from: { opacity: 0, y: distance }, to: { opacity: 1, y: 0 }, delay,
      write: ({ opacity, y }) => { element.style.opacity = String(bounded(opacity)); element.style.setProperty('--flow-enter-y', `${y}px`); },
      done: () => { element.style.opacity = ''; element.style.removeProperty('--flow-enter-y'); delete element.dataset.flowEnter; } });
  }
  function visible(element, open, distance = model.information) {
    if (element.hidden === !open && !value(element, 'visibility')) return;
    const hidden = element.hasAttribute('hidden'), display = hidden ? '' : getComputedStyle(element).display;
    element.hidden = !open; element.toggleAttribute('hidden',!open);element.inert = !open;
    element.setAttribute('aria-hidden', String(!open)); element.dataset.flowVisible = '';
    element.style.setProperty('--flow-display', display || getComputedStyle(element).display);
    element.dataset.flowEnter = '';
    spring(element, 'visibility', { from: { progress: hidden ? 0 : 1 }, to: { progress: open ? 1 : 0 },
      write: ({ progress }) => { element.style.opacity = String(bounded(progress)); element.style.setProperty('--flow-enter-y', `${(1 - progress) * distance}px`); },
      done: () => { element.style.opacity = ''; element.style.removeProperty('--flow-enter-y'); element.style.removeProperty('--flow-display'); delete element.dataset.flowVisible; delete element.dataset.flowEnter; } });
  }
  function intrinsic(element, axis = 'height') {
    const clone = element.cloneNode(true);
    for (const node of [clone, ...clone.querySelectorAll('*')]) { node.removeAttribute('id'); node.removeAttribute('data-motion-running'); }
    clone.hidden = false; clone.inert = true; clone.dataset.flowMeasuring = '';
    Object.assign(clone.style, { position: 'fixed', visibility: 'hidden', pointerEvents: 'none', translate: 'none', transform: 'none', opacity: '1', overflow: 'visible', height: 'auto', width: axis === 'height' ? `${element.getBoundingClientRect().width}px` : 'max-content' });
    delete clone.dataset.flowSizing; delete clone.dataset.flowVisible; delete clone.dataset.flowDisclosure;
    element.parentElement.append(clone);
    try { return clone.getBoundingClientRect()[axis]; } finally { clone.remove(); }
  }
  // Natural height changes with content or available width, not with each spring sample.
  const measurements = new WeakMap();
  function invalidate(element) {
    for (let node=element;node;node=node.parentElement) {
      const measurement=measurements.get(node);if(measurement)measurement.dirty=true;
    }
  }
  function natural(element,axis='height',initial=null) {
    const measurement={dirty:!initial,width:initial?.width??NaN,size:initial?.size??0};measurements.set(element,measurement);
    return ()=>{
      const width=element.getBoundingClientRect().width;
      if(measurement.dirty||width!==measurement.width){measurement.size=intrinsic(element,axis);measurement.width=width;measurement.dirty=false;}
      return measurement.size;
    };
  }
  const sizes = new WeakMap();
  function resize(element, change) {
    const height = element.getBoundingClientRect().height,free=!sizes.has(element)&&!element.style.height;
    const result = change();
    if (!element.getClientRects().length || reduced()) return result;
    // These containers have natural CSS height. Read their live target before
    // constraining it; unchanged content size needs neither a spring nor a clone.
    const box=free?element.getBoundingClientRect():null;
    if(box&&Math.abs(box.height-height)<.5)return result;
    if (!sizes.has(element)) sizes.set(element, { height: element.style.height, overflow: element.style.overflow });
    element.dataset.flowSizing = ''; element.style.overflow = 'hidden';
    const target=natural(element,'height',box?{width:box.width,size:box.height}:null);
    spring(element, 'size', { from: { height }, to: () => ({ height: target() }),
      write: ({ height }) => { element.style.height = `${Math.max(0, height)}px`;invalidate(element.parentElement); },
      done: () => { Object.assign(element.style, sizes.get(element)); sizes.delete(element);measurements.delete(element);delete element.dataset.flowSizing;invalidate(element.parentElement); } });
    return result;
  }
  function disclosure(element, open, axis = 'height') {
    if (element.hidden === !open && !value(element, 'disclosure')) return;
    const start = element.getBoundingClientRect()[axis], display = element.hidden ? '' : getComputedStyle(element).display;
    element.hidden = !open; element.inert = !open;
    element.dataset.flowDisclosure = ''; element.dataset.flowVisible = '';
    element.style.setProperty('--flow-display', display || getComputedStyle(element).display);
    element.style.overflow = 'hidden';
    const target=natural(element,axis);
    spring(element, 'disclosure', { from: { size: start, opacity: open && !start ? 0 : Number(getComputedStyle(element).opacity) },
      to: () => ({ size: open ? reduced()?start:target() : 0, opacity: open ? 1 : 0 }),
      write: ({ size, opacity }) => { element.style[axis] = `${Math.max(0, size)}px`; element.style.opacity = String(bounded(opacity));invalidate(element.parentElement); },
      done: () => { element.style[axis] = ''; element.style.opacity = ''; element.style.overflow = ''; element.style.removeProperty('--flow-display'); delete element.dataset.flowDisclosure; delete element.dataset.flowVisible;measurements.delete(element);invalidate(element.parentElement); } });
  }
  function details(root) {
    for (const detail of root.querySelectorAll('details')) {
      let body = detail.querySelector(':scope > .flow-detail-body');
      if (!body) {
        body = document.createElement('div'); body.className = 'flow-detail-body';
        const content=document.createElement('div');content.className='flow-detail-content';
        for (const child of [...detail.childNodes]) if (!(child instanceof Element && child.tagName === 'SUMMARY')) content.append(child);
        body.append(content);
        detail.append(body);
      }
      if(value(body,'disclosure')){if(body.dataset.flowOpen!==String(detail.open))detailVisibility(detail,detail.open);}
      else { body.hidden=false;body.inert=!detail.open; }
    }
  }
  function detailVisibility(detail,open) {
    const body=detail.querySelector(':scope > .flow-detail-body'),height=value(body,'disclosure')?.size??(detail.open?body.getBoundingClientRect().height:0);
    body.dataset.flowOpen=String(open);detail.dataset.flowDetails='';detail.open=open;
    body.hidden=!open;body.inert=!open;body.dataset.flowVisible='';body.dataset.flowDisclosure='';
    body.style.setProperty('--flow-display','block');body.style.overflow='hidden';
    // On the first opening the unconstrained live body already has its natural
    // height. A clone would lay out the entire readings list a second time.
    const box=open&&!reduced()&&!body.style.height?body.getBoundingClientRect():null;
    const target=natural(body,'height',box?{width:box.width,size:box.height}:null);
    spring(body,'disclosure',{from:{size:height,opacity:open&&!height?0:Number(getComputedStyle(body).opacity)},to:()=>({size:open?reduced()?height:target():0,opacity:open?1:0}),
      write:({size,opacity})=>{body.style.height=`${Math.max(0,size)}px`;body.style.opacity=String(bounded(opacity));invalidate(detail);},
      done:()=>{
        body.hidden=false;body.inert=!detail.open;body.style.height='';body.style.opacity='';body.style.overflow='';body.style.removeProperty('--flow-display');
        delete body.dataset.flowVisible;delete body.dataset.flowDisclosure;delete body.dataset.flowOpen;delete detail.dataset.flowDetails;measurements.delete(body);invalidate(detail);
      }});
  }
  document.addEventListener('click',event=>{
    const summary=event.target.closest('summary'),detail=summary?.parentElement;
    if(detail?.tagName!=='DETAILS')return;
    event.preventDefault();details(detail.parentElement);detailVisibility(detail,!detail.open);
  });
  document.addEventListener('toggle',event=>{if(event.target.tagName==='DETAILS'){details(event.target.parentElement);invalidate(event.target);}},true);
  function clip(element,cache=new Map()) {
    const parent=element.parentElement;
    if(!parent||parent===document.body)return{left:0,top:0,right:innerWidth,bottom:innerHeight};
    if(cache.has(parent))return cache.get(parent);
    const bounds={...clip(parent,cache)},style=getComputedStyle(parent),x=/auto|scroll|hidden|clip/.test(style.overflowX),y=/auto|scroll|hidden|clip/.test(style.overflowY);
    const box=x||y?parent.getBoundingClientRect():null;
    if (x) { bounds.left = Math.max(bounds.left, box.left + parent.clientLeft); bounds.right = Math.min(bounds.right, box.left + parent.clientLeft + parent.clientWidth); }
    if (y) { bounds.top = Math.max(bounds.top, box.top + parent.clientTop); bounds.bottom = Math.min(bounds.bottom, box.top + parent.clientTop + parent.clientHeight); }
    cache.set(parent,bounds);return bounds;
  }
  function presented(element) {
    return !element.closest('[hidden]:not([data-flow-visible])')&&!element.parentElement?.closest('details:not([open]):not([data-flow-details])');
  }
  function capture(element,cache) {
    if(!presented(element))return{box:{width:0,height:0},clip:null};
    if(!moving.size&&visibility.get(element)===false)return{box:{width:0,height:0},clip:null,unseen:true};
    const box=element.getBoundingClientRect();return { box, clip: box.width&&box.height?clip(element,cache):null };
  }
  function retire(element, geometry = capture(element), contexts=new Map(), remove=true) {
    const { box, clip: bounds } = geometry;
    const settle=()=>{finish(element);if(remove)element.remove();};
    if(reduced()||!box.width||!box.height)return settle;
    if(box.right<=bounds.left||box.left>=bounds.right||box.bottom<=bounds.top||box.top>=bounds.bottom)return settle;
    const style=getComputedStyle(element);let path=contexts.get(element.parentElement);
    if(!path){
      const template=document.createElement('div');let context=template,opacity=1;
      const ancestors=[];for(let parent=element.parentElement;parent&&parent!==document.body;parent=parent.parentElement)ancestors.unshift(parent);
      for(const parent of ancestors){
        opacity*=Number(getComputedStyle(parent).opacity);
        const shell=parent.cloneNode(false);shell.removeAttribute('id');shell.removeAttribute('hidden');
        for(const attribute of [...shell.attributes])if(attribute.name.startsWith('data-flow-')&&attribute.name!=='data-flow-details'||attribute.name==='data-motion-running')shell.removeAttribute(attribute.name);
        shell.style.cssText+=';display:contents!important;opacity:1!important;translate:none!important;transform:none!important;filter:none!important;contain:none!important;container-type:normal!important';
        context.append(shell);context=shell;
      }
      path={template,opacity};contexts.set(element.parentElement,path);
    }
    const opacity=Number(style.opacity)*path.opacity;
    if (!opacity)return settle;
    // Preserve selector/inheritance context with shallow shells. Copying every computed
    // property of every descendant made a pane switch a hundreds-of-ms blocking task.
    const ghost=document.createElement('div'),content=path.template.cloneNode(true),snapshot=element.cloneNode(true);let context=content;
    while(context.firstElementChild)context=context.firstElementChild;
    for(const node of [snapshot,...snapshot.querySelectorAll('*')])node.removeAttribute('id');
    const frozen=['display','box-sizing','font','color','text-align','padding','border','border-radius','background','gap','flex-direction','align-items','justify-content'].map(property=>`${property}:${style.getPropertyValue(property)}!important`).join(';');
    if(element.tagName==='TR')for(let i=0;i<element.children.length;i++){
      const cell=element.children[i],copy=snapshot.children[i],style=getComputedStyle(cell);
      for(const property of ['border-top','border-bottom','padding'])copy.style.setProperty(property,style.getPropertyValue(property));
      copy.style.width=`${cell.getBoundingClientRect().width}px`;
    }
    snapshot.style.cssText+=`;${frozen};position:absolute!important;left:0!important;top:0!important;width:${box.width}px!important;height:${box.height}px!important;margin:0!important;opacity:1!important;translate:none!important;transform:none!important`;
    context.append(snapshot);
    ghost.append(content);
    ghost.inert = true; ghost.setAttribute('aria-hidden', 'true'); ghost.dataset.flowRetiring = '';
    // Keep the viewport clip still and translate only its contents. Updating a
    // clip path every spring sample repaints the entire retained SVG/text tree.
    // Twice the travel includes the shared spring's small overshoot.
    const room=model.information*2,top=box.top-room,height=box.height+room*2;
    ghost.style.cssText=`position:fixed;left:${box.left}px;top:${top}px;width:${box.width}px;height:${height}px;margin:0;translate:none;transform:none;pointer-events:none;z-index:90;clip-path:inset(${Math.max(0,bounds.top-top)}px ${Math.max(0,box.right-bounds.right)}px ${Math.max(0,top+height-bounds.bottom)}px ${Math.max(0,bounds.left-box.left)}px)`;
    content.style.cssText=`position:absolute;left:0;top:${room}px;width:${box.width}px;height:${box.height}px;overflow:hidden;will-change:translate;pointer-events:none`;
    const commit=()=>{
    settle(); document.body.append(ghost);
    spring(ghost, 'retirement', { from: { opacity, y: 0 }, to: { opacity: 0, y: -model.information },
      write: ({ opacity, y }) => {
        ghost.style.opacity = String(bounded(opacity)); content.style.translate = `0 ${y}px`;
      }, done: () => ghost.remove() });
    };commit.snapshot=ghost;return commit;
  }
  const actors = ':scope > *, [data-reading], [data-detail], .pane-group, .prow, .pnear';
  function layout(root, change, selector = actors, measure = true, defer=false) {
    flushLayouts(root);
    if(viewportScroll[0]!==scrollX||viewportScroll[1]!==scrollY)resetVisibility();
    releaseObservers();
    const active = document.activeElement;
    const restore=()=>{if(active?.isConnected&&root.contains(active)&&document.activeElement!==active)active.focus({preventScroll:true});};
    if(reduced()||!measure){const result=change(new Map());restore();return result;}
    const initial=[...root.querySelectorAll(selector)];observe(initial);
    const clips=new Map(),before = new Map(initial.map(el => [el, capture(el,clips)]));before.retirements=new Map();before.bookends=new Map();
    if(defer){const box=root.getBoundingClientRect();before.origin={left:box.left-root.scrollLeft,top:box.top-root.scrollTop};}
    const result = change(before);
    // Read departing styles before removals/ghost insertion can force another layout.
    for(const [node,commit]of before.retirements){
      let parent=node.parentElement;
      while(parent&&!before.retirements.get(parent)?.snapshot)parent=parent.parentElement;
      if(!parent)commit();
    }
    releaseObservers();
    restore();
    const complete=()=>completeLayout(root,before,selector);
    // A fresh observation runs after native layout and before paint, even when
    // only row order changed. Translate writes do not resize the observed pane.
    if(defer&&layoutObserver&&root.isConnected){pendingLayouts.set(root,complete);layoutObserver.observe(root);}
    else complete();
    return result;
  }
  function completeLayout(root,before,selector){
    const after = [...root.querySelectorAll(selector)], actorsAfter=new Set(after),deltas = new Map(),entries=new Set(),afterClips=new Map();
    const origin=before.origin?root.getBoundingClientRect():null,shift=origin?{x:origin.left-root.scrollLeft-before.origin.left,y:origin.top-root.scrollTop-before.origin.top}:{x:0,y:0};
    observe(after);
    const visible=(box,bounds)=>bounds&&box.width&&box.height&&box.right>bounds.left&&box.left<bounds.right&&box.bottom>bounds.top&&box.top<bounds.bottom;
    for (const el of after) if(owners.get(el)?.has('layout')) { el.style.removeProperty('--flow-layout-x'); el.style.removeProperty('--flow-layout-y'); }
    for (const el of after) {
      if(!presented(el))continue;
      const old = before.get(el);
      // Entry only needs opacity/translation. Measuring a newly inserted tree
      // forces its entire SVG/readings layout inside the input/result task.
      if(!old?.box.width||!old.box.height){
        const channel=old?.unseen&&owners.get(el)?.get('layout');if(channel)complete(channel);
        if(old?.unseen&&arrivalSampler){arrivals.add(el);arrivalSampler.observe(el);}
        else if(before.entrances?.has(el))entries.add(el);
        continue;
      }
      const box=el.getBoundingClientRect();
      const bounds=clip(el,afterClips),previous=shift.x||shift.y?{width:old.box.width,height:old.box.height,left:old.box.left+shift.x,right:old.box.right+shift.x,top:old.box.top+shift.y,bottom:old.box.bottom+shift.y}:old.box;
      const wasVisible=visible(previous,shift.x||shift.y?bounds:old.clip),isVisible=visible(box,bounds);
      if(!wasVisible){
        const channel=owners.get(el)?.get('layout');if(channel)complete(channel);
        if(isVisible)entries.add(el);
        continue;
      }
      if (box.width && box.height) deltas.set(el, { x: previous.left - box.left, y: previous.top - box.top });
    }
    for (const el of after) {
      const delta = deltas.get(el);
      if (!delta) {
        let parent=el.parentElement,nested=false;
        while(parent){
          if(owners.get(parent)?.has('entry')||actorsAfter.has(parent)&&(!before.has(parent)||entries.has(parent)||arrivals.has(parent))){nested=true;break;}
          if(parent===root)break;parent=parent.parentElement;
        }
        if((!before.has(el)||entries.has(el))&&!nested&&presented(el))reveal(el);continue;
      }
      let parent = el.parentElement;
      while (parent && parent !== root && !deltas.has(parent)) parent = parent.parentElement;
      const ancestor = deltas.get(parent), from = { x: delta.x - (ancestor?.x || 0), y: delta.y - (ancestor?.y || 0) };
      if (Math.abs(from.x) < .5 && Math.abs(from.y) < .5 && !value(el, 'layout')) continue;
      el.dataset.flowLayout = '';
      spring(el, 'layout', { from, to: { x: 0, y: 0 }, rebase: true,
        write: ({ x, y }) => { el.style.setProperty('--flow-layout-x', `${x}px`); el.style.setProperty('--flow-layout-y', `${y}px`); },
        done: () => { el.style.removeProperty('--flow-layout-x'); el.style.removeProperty('--flow-layout-y'); delete el.dataset.flowLayout; } });
    }
  }
  const keyPriority=Object.assign(Object.create(null),{'data-motion-key':0,id:1,'data-reading':2,'data-detail':3,'data-key':4,'data-design':5,'data-k':6});
  function key(node, index) {
    if (node.nodeType !== 1) return `text-${index}`;
    let selected=null,priority=Infinity;
    for(const name of node.getAttributeNames())if(keyPriority[name]<priority){selected=name;priority=keyPriority[name];if(priority===0)break;}
    if(selected)return `${node.tagName}:${selected}:${node.getAttribute(selected)}`;
    return `${node.tagName}:${node.classList[0] || ''}:${index}`;
  }
  function attributes(current, incoming) {
    let equal=current.attributes.length===incoming.attributes.length;
    if(equal)for(const attr of current.attributes)if(incoming.getAttribute(attr.name)!==attr.value){equal=false;break;}
    if(equal)return false;
    const preserve = name => name.startsWith('data-flow-') || name === 'data-motion-running' || current.tagName === 'DETAILS' && name === 'open' || name==='inert'&&current.classList.contains('flow-detail-body');
    for (const attr of [...current.attributes]) if (!preserve(attr.name) && attr.name !== 'style' && !incoming.hasAttribute(attr.name)) current.removeAttribute(attr.name);
    for (const attr of incoming.attributes) if (!preserve(attr.name) && attr.name !== 'style' && current.getAttribute(attr.name) !== attr.value) current.setAttribute(attr.name, attr.value);
    if(current.getAttribute('style')===incoming.getAttribute('style'))return false;
    const running=Boolean(owners.get(current)?.size),style=incoming.getAttribute('style');
    // Ordinary chart marks have no spring-owned styles. Apply their declaration
    // once rather than iterating CSSOM properties and invalidating each one.
    if(!running&&!(current.getAttribute('style')||'').includes('--flow-')&&!(style||'').includes('--flow-')){
      if(style===null)current.removeAttribute('style');else current.setAttribute('style',style);
      return false;
    }
    const temporary = name => name.startsWith('--flow-') || running && ['height', 'width', 'opacity', 'overflow', 'overflow-x', 'overflow-y', 'translate'].includes(name);
    let deferred=false;
    for(const name of new Set([...current.style,...incoming.style]))if(temporary(name)&&!name.startsWith('--flow-')&&(current.style.getPropertyValue(name)!==incoming.style.getPropertyValue(name)||current.style.getPropertyPriority(name)!==incoming.style.getPropertyPriority(name)))deferred=true;
    for (const name of [...current.style]) if (!temporary(name) && !incoming.style.getPropertyValue(name)) current.style.removeProperty(name);
    for (const name of incoming.style) if (!temporary(name)&&(current.style.getPropertyValue(name)!==incoming.style.getPropertyValue(name)||current.style.getPropertyPriority(name)!==incoming.style.getPropertyPriority(name))) current.style.setProperty(name, incoming.style.getPropertyValue(name), incoming.style.getPropertyPriority(name));
    return deferred;
  }
  function planReconcile(root, incoming, geometries, animate, retain, contexts) {
    markups.delete(root);
    // A retained disclosure inside this patch may have new children or text.
    const measurement=measurements.get(root);if(measurement)measurement.dirty=true;
    const old = [...root.childNodes], desired = [...incoming.childNodes], used = new Set(), keyed = new Map(old.map((node, i) => [key(node, i), node]));
    const plan=desired.map((next,index)=>{
      let node = keyed.get(key(next, index));
      if (!node || used.has(node) || node.nodeType !== next.nodeType || node.nodeName !== next.nodeName) node = next;
      used.add(node);
      // Another patch in this transaction may have restored a queued actor.
      geometries.retirements?.delete(node);
      return {node,next};
    });
    // Prepare the entire subtree before any retained DOM writes. Preparing a
    // later sibling after an earlier insertion otherwise forces repeated layout.
    const remove=[];
    for (const node of old) if (!used.has(node)) {
      if (node.nodeType === 1 && animate && geometries.has(node)) geometries.retirements.set(node,retire(node,geometries.get(node),contexts));
      else if(node.nodeType===1&&animate&&geometries.retirements){
        const captured=[...geometries].filter(([actor])=>node.contains(actor));
        if(captured.length){
          for(const [actor,geometry]of captured){
            if(geometries.retirements.has(actor))continue;
            let parent=actor.parentElement;while(parent&&!geometries.retirements.get(parent)?.snapshot)parent=parent.parentElement;
            if(!parent)geometries.retirements.set(actor,retire(actor,geometry,contexts));
          }
          geometries.retirements.set(node,()=>{finish(node);node.remove();});
        }else remove.push(node);
      }else remove.push(node);
    }
    for(const item of plan){
      const {node,next}=item;
      if(node!==next){
        if(node.nodeType===1&&!node.isEqualNode(next)){
          item.retain=retain?.(node,next);
          if(!item.retain)item.children=planReconcile(node,next,geometries,animate,retain,contexts);
        }
        else {
          // An equal restored subtree implicitly restores queued descendants.
          if(node.nodeType===1&&geometries.retirements?.size)for(const pending of geometries.retirements.keys())if(node.contains(pending)){
            geometries.retirements.delete(pending);
            for(let ancestor=pending;ancestor;ancestor=ancestor.parentElement){markups.delete(ancestor);if(ancestor===node)break;}
          }
        }
      }
    }
    return {root,plan,remove};
  }
  function applyReconcile({root,plan,remove},geometries){
    for(const node of remove){if(node.nodeType===1)finish(node);node.remove();}
    // A large static reading list can reverse in one accepted result. Batch
    // those moves while preserving the existing nodes and their bindings.
    // Interactive content and selected text keep the incremental path.
    let bulk=false;
    if(plan.length>70&&root.classList?.contains('flow-detail-content')&&plan.every(({node})=>node.nodeName==='DIV'&&node.className==='prow')){
      const controls='a,button,input,select,textarea,[tabindex],[contenteditable]',selection=document.getSelection();
      if(!root.contains(document.activeElement)&&!root.querySelector(controls)&&!plan.some(({node,next})=>node===next&&node.querySelector(controls))&&
        (!selection?.rangeCount||selection.isCollapsed||!selection.getRangeAt(0).intersectsNode(root))){
        const old=[...root.childNodes];bulk=plan.filter(({node},i)=>old[i]!==node).length>plan.length/2;
      }
    }
    let cursor=root.firstChild,deferred=false;
    for(const {node,next,children,retain}of plan){
      if(children){deferred=attributes(node,next)||deferred;deferred=applyReconcile(children,geometries)||deferred;}
      else if(retain){
        deferred=attributes(node,next)||deferred;retain();markups.delete(node);
        const walker=document.createTreeWalker(node,NodeFilter.SHOW_ALL);let child;
        while((child=walker.nextNode())){markups.delete(child);const measurement=measurements.get(child);if(measurement)measurement.dirty=true;}
      }
      else if(node!==next&&node.nodeType!==1&&node.nodeValue!==next.nodeValue)node.nodeValue=next.nodeValue;
      if(!bulk){if(node!==cursor)root.insertBefore(node,cursor);cursor=node.nextSibling;}
    }
    if(bulk)root.replaceChildren(...plan.map(({node})=>node));
    geometries.bookends?.set(root,{first:plan[0]?.node??null,last:plan.at(-1)?.node??null});
    return deferred;
  }
  function reconcile(root,incoming,geometries,animate,retain){
    return applyReconcile(planReconcile(root,incoming,geometries,animate,retain,new Map()),geometries);
  }
  const markups=new WeakMap();let transaction=null;
  function update(root,markup,change,intrinsic=false){
    const previous=markups.get(root);
    if(!previous||previous.first!==root.firstChild||previous.last!==root.lastChild)return false;
    const geometries=transaction?.root.contains(root)?transaction.geometries:null,contexts=new Map();
    const move={depart:node=>{const geometry=geometries?.get(node);if(geometry)geometries.retirements?.set(node,retire(node,geometry,contexts,false));},arrive:node=>{if(geometries)(geometries.entrances??=new Set()).add(node);}};
    const memo=change(previous.memo,move);if(!memo)return false;
    for(let parent=root.parentElement;parent;parent=parent.parentElement)markups.delete(parent);
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_ALL);let node;
    while((node=walker.nextNode())){markups.delete(node);if(intrinsic){const measurement=measurements.get(node);if(measurement)measurement.dirty=true;}}
    if(intrinsic)invalidate(root);
    markups.set(root,{markup,first:root.firstChild,last:root.lastChild,memo});return true;
  }
  function stableUpdate(root,incoming){
    const old=document.createTreeWalker(root,NodeFilter.SHOW_ALL),next=document.createTreeWalker(incoming,NodeFilter.SHOW_ALL),parents=new WeakMap([[root,incoming]]),pairs=[];
    let current=old.nextNode(),desired=next.nextNode();
    while(current||desired){
      if(!current||!desired||current.nodeType!==desired.nodeType||current.nodeName!==desired.nodeName||parents.get(current.parentNode)!==desired.parentNode||key(current,0)!==key(desired,0))return null;
      pairs.push([current,desired]);parents.set(current,desired);current=old.nextNode();desired=next.nextNode();
    }
    let deferred=false;
    for(const [current,desired]of pairs){
      markups.delete(current);const measurement=measurements.get(current);if(measurement)measurement.dirty=true;
      if(current.nodeType===1)deferred=attributes(current,desired)||deferred;
      else if(current.nodeValue!==desired.nodeValue)current.nodeValue=desired.nodeValue;
    }
    return deferred;
  }
  function batch(root,change,measure=true,defer=false){
    return layout(root,geometries=>{
      const previous=transaction;transaction={root,geometries};
      try{return change();}finally{transaction=previous;}
    },actors,measure,defer);
  }
  function patch(root, markup, animate = true, stable = false, retain = null, templateMarkup = markup) {
    const previous=markups.get(root);
    if(previous?.markup===markup&&previous.first===root.firstChild&&previous.last===root.lastChild){details(root);return;}
    for(let parent=root.parentElement;parent;parent=parent.parentElement)markups.delete(parent);
    const template = document.createElement('template'); template.innerHTML = templateMarkup; details(template.content);
    let result=stable&&!retain&&previous&&previous.first===root.firstChild&&previous.last===root.lastChild?stableUpdate(root,template.content):null;
    if(result===null)result=animate?(transaction?.root.contains(root)?reconcile(root,template.content,transaction.geometries,true,retain):layout(root,geometries=>reconcile(root,template.content,geometries,true,retain))):reconcile(root,template.content,new Map(),false,retain);
    details(root);invalidate(root);
    // A spring owns temporary presentation styles until it settles. Do not
    // memoize an incoming style request that reconciliation had to defer.
    const ends=transaction?.root.contains(root)?transaction.geometries.bookends?.get(root):null;
    if(!result)markups.set(root,{markup,first:ends?ends.first:root.firstChild,last:ends?ends.last:root.lastChild});else markups.delete(root);
    return result;
  }
  function switchControl(input) {
    const target = input.checked ? 13 : 0;
    if (!input.hasAttribute('data-flow-switch')) { input.dataset.flowSwitch = ''; input.style.setProperty('--flow-switch-x', `${target}px`); return; }
    spring(input, 'switch', { from: { x: parseFloat(input.style.getPropertyValue('--flow-switch-x')) }, to: { x: target }, write: ({ x }) => input.style.setProperty('--flow-switch-x', `${x}px`) });
  }
  let position = 0, velocity = 0; const samples = [0];
  do { const next = integrate(position, velocity, 1, .008); position = next.position; velocity = next.velocity; samples.push(position); } while (Math.abs(position - 1) > .002 || Math.abs(velocity) > .02);
  samples[samples.length - 1] = 1;
  const css = document.documentElement.style;
  css.setProperty('--flow-settle', `${(samples.length - 1) * 8}ms`); css.setProperty('--flow-spring', `linear(${samples.map(n => n.toFixed(5)).join(',')})`);
  preference.addEventListener('change', () => { if (preference.matches) finish(); });
  addEventListener('resize', () => finish());
  addEventListener('beforeprint', () => { printing = true; finish(); });
  addEventListener('afterprint', () => { printing = false; });
  addEventListener('pagehide', () => { suspended = true; finish(); });
  addEventListener('pageshow', () => { suspended = document.hidden; });
  document.addEventListener('visibilitychange', () => { suspended = document.hidden; if (suspended) finish(); });
  details(document);
  return { model, integrate, advance, bounds, reduced, suspended:()=>suspended||printing, spring, value, cancel, finish, reveal, visible, disclosure, resize, layout, batch, patch, update, details, switchControl, onSettle: fn => settlers.add(fn), active: () => moving.size > 0 || arrivals.size > 0 || pendingLayouts.size > 0 };
})();
