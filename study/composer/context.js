'use strict';
// Grid #59/#63: repeat the 500 ms dwell for every hover; focus and touch explain immediately.
const ForecastContext = (() => {
  function install(root, box, flow) {
    let timer=null, owner=null, pending=null, described=null, description=null, point=null;
    const resolve=node=>node?.closest?.('[data-tip]');
    function hide(){
      clearTimeout(timer);timer=null;pending=null;point=null;
      if(described){if(description===null)described.removeAttribute('aria-describedby');else described.setAttribute('aria-describedby',description);}
      owner=null;described=null;description=null;flow.visible(box,false);
    }
    function show(target,x,y,control=target){
      clearTimeout(timer);timer=null;pending=null;
      if(!target?.isConnected||!target.dataset.tip){hide();return;}
      const text=target.dataset.tip;
      hide();owner=target;described=control;point={x,y};description=control.getAttribute('aria-describedby');
      control.setAttribute('aria-describedby',[description,box.id].filter(Boolean).join(' '));
      box.textContent=text;flow.visible(box,true);
      const r=box.getBoundingClientRect(),vw=window.innerWidth,vh=window.innerHeight;
      const left=Math.max(8,Math.min(x+14,vw-r.width-8));
      const top=Math.max(8,y+16+r.height<=vh-8?y+16:y-r.height-12);
      Object.assign(box.style,{left:`${left}px`,top:`${top}px`});
    }
    root.addEventListener('pointerover',e=>{
      if(e.pointerType==='touch')return;
      const target=resolve(e.target),previous=resolve(e.relatedTarget);
      if(!target||target===previous)return;
      hide();pending=target;const x=e.clientX,y=e.clientY;
      timer=setTimeout(()=>{if(pending===target)show(target,x,y);},500);
    });
    root.addEventListener('pointerout',e=>{if(e.pointerType!=='touch'&&resolve(e.target)!==resolve(e.relatedTarget))hide();});
    root.addEventListener('focusin',e=>{const target=resolve(e.target);if(target){const r=e.target.getBoundingClientRect();show(target,r.left,r.bottom,e.target);}});
    root.addEventListener('focusout',hide);
    root.addEventListener('pointerdown',e=>{if(e.pointerType==='touch'){const target=resolve(e.target);if(target)show(target,e.clientX,e.clientY);else hide();}});
    document.addEventListener('pointerdown',e=>{if(owner&&!root.contains(e.target))hide();});
    document.addEventListener('keydown',e=>{if(e.key==='Escape')hide();});
    document.addEventListener('scroll',hide,{capture:true,passive:true});
    window.addEventListener('resize',hide);
    return {hide,cancelFor(container){if(container.contains(owner)||container.contains(pending)||container.contains(described))hide();},refresh(){if(owner&&point){const target=owner,control=described,p={...point};show(target,p.x,p.y,control);}}};
  }
  return {install};
})();
