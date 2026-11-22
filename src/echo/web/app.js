/* app.js: Frontend logic for the ECHO web interface

Manages application state, sound sources, scene controls,
room visualization, audio rendering, playback, and file uploads

Communicates with the Python backend through the /api endpoints
HTML structure is defined in index.html
Styling is defined in style.css */

"use strict";

/* ------------------------------------------------------------------ constants */
const COLORS = ["#5eead4","#ff8fab","#a78bfa","#7cc4ff","#fdba74","#d9f99d","#f0abfc","#fde68a"];
const BASE = {motion:"Static",x:0,y:3,radius:4,speed:0.08,pass_time:6,start:0,gain:0,send:0.3,doppler:1,rolloff:1,air:1,shadow:1};
const ROOM0 = {enabled:true,width:12,depth:10,absorption:0.35};
const REVERB0 = {enabled:true,kind:"fdn",t60:2.5,damping:0.25,size:1,predelay:0.02,level_db:-6};
const DELAY0 = {enabled:false,time:0.375,feedback:0.45,level_db:-8};
const MOTIONS = [["Static","Stay put"],["Orbit","Circle around you"],["Spiral","Spiral in and out"],["Oscillate","Sweep left and right"],["Flyby","Fly past once"]];
const PARAM_KEYS = ["motion","x","y","radius","speed","pass_time","start","gain","send","doppler","rolloff","air","shadow"];
const HINT_DEFAULT = "Drag a sound on the map to move it. Hover any control to see what it does. Double-click a control's name to reset it.";

/* ------------------------------------------------------------------ state */
let catalog = {kinds:[], presets:[]};
let S = freshState();
let G0 = snapshot(S);
let sel = 0;
let view = 0;
let paths = {};
let rendered = null;
let previous = null;
let showingPrev = false;
let dirty = false;
let rendering = false;
let built = false;

function freshState(){ return {length:16, sources:[], room:{...ROOM0}, reverb:{...REVERB0}, delay:{...DELAY0}}; }
function snapshot(s){ return JSON.parse(JSON.stringify(s)); }
function payload(){ return JSON.stringify(S, (k,v)=> k==="def" ? undefined : v); }
const colorOf = i => COLORS[i % COLORS.length];
const uid = () => Math.random().toString(36).slice(2,9);
const $ = (s,el=document) => el.querySelector(s);

function h(tag, props={}, ...kids){
  const e = document.createElement(tag);
  for (const [k,v] of Object.entries(props)){
    if (k==="class") e.className=v;
    else if (k==="text") e.textContent=v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v===true) e.setAttribute(k,"");
    else if (v!==false && v!=null) e.setAttribute(k,v);
  }
  for (const kid of kids.flat()){ if (kid==null||kid===false) continue; e.append(kid.nodeType ? kid : document.createTextNode(kid)); }
  return e;
}

function kindInfo(id){ return catalog.kinds.find(k=>k.id===id) || {label:id,defaults:{}}; }
function uniqueName(base){
  const names = S.sources.map(s=>s.name); if (!names.includes(base)) return base;
  let n=2; while (names.includes(`${base} ${n}`)) n++; return `${base} ${n}`;
}
function newSource(kind, over={}, arg="", name=""){
  const info = kindInfo(kind);
  const s = {id:uid(), kind, arg, name: name || uniqueName(info.label), ...BASE, ...info.defaults, ...over};
  s.def = Object.fromEntries(PARAM_KEYS.map(k=>[k,s[k]]));
  return s;
}
function addSource(kind, over={}, arg="", name=""){
  if (S.sources.length >= 12){ say("That's the maximum of 12 sounds. Remove one to add another.","err"); return; }
  S.sources.push(newSource(kind, over, arg, name));
  sel = S.sources.length-1;
  markDirty(); renderSetupBar(); fetchScene();
}
function removeSource(i){
  S.sources.splice(i,1);
  sel = Math.max(0, Math.min(sel, S.sources.length-1));
  markDirty(); renderSetupBar(); renderLeft(); fetchScene();
}


let sceneBusy=false, scenePending=false;
async function fetchScene(){
  if (sceneBusy){ scenePending=true; return; }
  sceneBusy=true;
  try{
    const r = await fetch("/api/scene",{method:"POST",body:payload()});
    const j = await r.json();
    if (j.paths) paths = j.paths;
  }catch(e){ /* server stopped: the status line reports it on render */ }
  sceneBusy=false;
  if (scenePending){ scenePending=false; fetchScene(); }
  requestDraw();
}

function say(msg, kind=""){ const el=$("#status"); el.className="status "+kind; el.textContent=msg; }
function markDirty(){
  if (rendered && !dirty){ dirty=true; }
  updateStatus(); updateButtons();
}
function updateStatus(){
  const el=$("#status");
  if (rendering) return;
  if (!S.sources.length){ el.className="status"; el.textContent="Add a sound to get started."; return; }
  if (rendered && dirty){ el.className="status"; el.replaceChildren(h("span",{class:"dot"}),"You changed something. Render again to hear it."); return; }
  if (rendered){ return; }
  el.className="status"; el.textContent="Ready. Press Render and play. It takes a few seconds.";
}
function updateButtons(){
  const b=$("#btn-render");
  b.disabled = rendering || !S.sources.length;
  b.textContent = rendering ? "Rendering…" : (rendered ? "Render again" : "Render and play");
  $("#btn-build").disabled = !S.sources.length;
  const cur = view===0 ? 0 : (rendered ? 2 : 1);
  document.querySelectorAll("#steps button").forEach((btn,i)=>{
    if (i===cur) btn.setAttribute("aria-current","step"); else btn.removeAttribute("aria-current");
    btn.classList.toggle("done", i<cur);
    btn.disabled = (i>0 && !S.sources.length);
  });
}

function showHint(t){ $("#hint").textContent = t || HINT_DEFAULT; }
const num = (d,u="") => v => v.toFixed(d)+u;
const db = v => (v>0?"+":"")+v.toFixed(1)+" dB";
const pct = v => Math.round(v*100)+"%";

function slider({label,min,max,step,get,set,def,fmt,hint,key,idle}){
  const input = h("input",{type:"range",min,max,step,"aria-label":label,"data-key":key||""});
  const val = h("span",{class:"val"});
  const name = h("span",{text:label,title:"Double-click to reset"});
  const row = h("div",{class:"row"}, h("div",{class:"row-top"},name,val), input);
  const paint = ()=>{ val.textContent = fmt(+input.value); input.style.setProperty("--pct", ((input.value-min)/(max-min)*100)+"%"); };
  const refresh = ()=>{ input.value=get(); paint(); };
  input.addEventListener("input",()=>{ set(+input.value); paint(); onChange(); });
  name.addEventListener("dblclick",()=>{ set(def()); refresh(); onChange(); });
  row.addEventListener("mouseenter",()=>showHint(hint)); row.addEventListener("mouseleave",()=>showHint());
  input.addEventListener("focus",()=>showHint(hint)); input.addEventListener("blur",()=>showHint());
  const why = idle ? idle() : null;
  if (why){ row.classList.add('idle'); row.title = 'No effect right now: '+why; }
  row.refresh=refresh; row.input=input; refresh();
  return row;
}
function toggle(label,get,set,hint){
  const input=h("input",{type:"checkbox","aria-label":label}); input.checked=get();
  const w=h("label",{class:"switch"},input,h("span"));
  input.addEventListener("change",()=>{ set(input.checked); onChange(true); });
  w.addEventListener("mouseenter",()=>showHint(hint)); w.addEventListener("mouseleave",()=>showHint());
  return w;
}
function select(label,opts,get,set,hint){
  const sel_=h("select",{"aria-label":label}, opts.map(([v,t])=>h("option",{value:v,text:t})));
  sel_.value=get();
  sel_.addEventListener("change",()=>{ set(sel_.value); onChange(true); });
  const f=h("label",{class:"field"},h("span",{text:label}),sel_);
  f.addEventListener("mouseenter",()=>showHint(hint)); f.addEventListener("mouseleave",()=>showHint());
  return f;
}
function group(title,children,onReset,enabled){
  const head=h("div",{class:"group-head"},h("h3",{text:title}));
  const right=h("div",{style:"display:flex;gap:8px;align-items:center"});
  if (enabled) right.append(enabled);
  right.append(h("button",{class:"link",text:"Reset",title:"Put these controls back to where they started",onclick:()=>{onReset();onChange(true);}}));
  head.append(right);
  return h("div",{class:"group"},head,children);
}

function onChange(rebuild=false){
  if (rebuild) { renderLeft(); renderRight(); }
  markDirty(); fetchScene(); requestDraw();
}

function renderLeft(){
  const rail=$("#rail-left"); rail.replaceChildren();
  rail.style.setProperty("--c", colorOf(sel));
  const list=h("ul",{class:"src-list"});
  S.sources.forEach((s,i)=>{
    const li=h("li",{class:"src-item"+(i===sel?" sel":""),style:`--c:${colorOf(i)}`},
      h("button",{class:"src-pick",onclick:()=>{sel=i;renderLeft();requestDraw();},"aria-pressed":i===sel},
        h("i"),h("b",{text:s.name}),h("small",{text:motionLabel(s.motion)})),
      h("button",{class:"src-rm","aria-label":`Remove ${s.name}`,title:"Remove this sound",text:"✕",onclick:()=>removeSource(i)}));
    list.append(li);
  });
  rail.append(h("div",{class:"rail-head"},h("h2",{text:"Sounds"}),h("button",{class:"btn",text:"Add sound",onclick:()=>openAdd()})));
  if (!S.sources.length){ rail.append(h("p",{class:"empty-note",text:"No sounds yet. Add one to place it on the map."})); return; }
  rail.append(list);
  const s=S.sources[sel]; if (!s) return;
  const d = k => s.def[k];
  const mk = (o)=>slider({...o,get:()=>s[o.key],set:v=>{s[o.key]=v;},def:()=>d(o.key)});
  const sp = s.motion==="Oscillate" ? "swings/min" : "laps/min";
  const radiusLabel = {Orbit:"Circle radius",Spiral:"Outer radius",Oscillate:"Sweep width (each side)",Flyby:"Pass distance (each side)"}[s.motion];
  const moveRows=[ select("Path",MOTIONS,()=>s.motion,v=>{s.motion=v;},"How this sound travels around you.") ];
  moveRows.push(mk({key:"x",label:"X-Position (Left/Right)",min:-15,max:15,step:0.1,fmt:v=>(v>0?"+":"")+v.toFixed(1)+" m",hint:"Position left (−) or right (+) of you, in meters. For moving sounds this is the center of the path. You can also drag it on the map."}));
  moveRows.push(mk({key:"y",label:"Y-Position (Behind/Ahead)",min:-15,max:15,step:0.1,fmt:v=>(v>0?"+":"")+v.toFixed(1)+" m",hint:"Position behind (−) or ahead (+) of you. You sit in the center of the map facing up."}));
  if (s.motion!=="Static") moveRows.push(mk({key:"radius",label:radiusLabel,min:0.5,max:40,step:0.5,fmt:num(1," m"),hint:"How big the movement is."}));
  if (s.motion==="Orbit"||s.motion==="Spiral"||s.motion==="Oscillate")
    moveRows.push(mk({key:"speed",label:"Speed",min:-0.5,max:0.5,step:0.005,fmt:v=>Math.abs(v)<0.0025?"still":(v>0?"↺ ":"↻ ")+Math.abs(v*60).toFixed(1)+" "+sp,hint:"How fast it moves. The arrow shows the direction seen on the map. Negative reverses it."}));
  if (s.motion==="Flyby")
    moveRows.push(mk({key:"pass_time",label:"Fly-by time",min:1,max:30,step:0.5,fmt:num(1," s"),hint:"How long the pass takes. A shorter pass is faster, so the pitch bend is stronger."}));
  moveRows.push(mk({key:"start",label:"Starts at",min:0,max:S.length,step:0.5,fmt:num(1," s"),hint:"When this sound starts, in seconds from the beginning."}));
  rail.append(group("Movement",moveRows,()=>{ PARAM_KEYS.slice(0,7).forEach(k=>s[k]=s.def[k]); }));
  rail.append(group("Level",[
    mk({key:"gain",label:"Volume",min:-30,max:6,step:0.5,fmt:db,hint:"How loud this sound is before it travels around."}),
    mk({key:"send",label:"Reverb amount",min:0,max:1,step:0.01,fmt:pct,hint:"How much goes into the reverb. More makes it sound farther away and washier.",idle:()=>S.reverb.enabled?null:"the reverb is switched off (right side)."}),
  ],()=>{ ["gain","send"].forEach(k=>s[k]=s.def[k]); }));
  rail.append(group("Realism",[
    mk({key:"doppler",label:"Pitch bend (Doppler)",min:0,max:3,step:0.05,fmt:v=>v===0?"off":v.toFixed(2)+"×",hint:"Pitch changes as a sound moves toward or away from you. 0 is off, 1 is like real life, higher is exaggerated.",idle:()=>s.motion==="Static"?"this sound isn't moving, so there is no pitch bend.":null}),
    mk({key:"rolloff",label:"Distance fade",min:0,max:2,step:0.05,fmt:num(2),hint:"How quickly it gets quieter with distance. 1 is realistic. 0 keeps the same volume everywhere."}),
    mk({key:"air",label:"Distance dulling",min:0,max:4,step:0.05,fmt:num(2),hint:"How much treble is lost over distance. Higher makes faraway sounds duller."}),
    mk({key:"shadow",label:"Head shadow",min:0,max:1,step:0.01,fmt:pct,hint:"How much your head muffles the ear facing away from the sound."}),
  ],()=>{ ["doppler","rolloff","air","shadow"].forEach(k=>s[k]=s.def[k]); }));
}
function motionLabel(m){ return (MOTIONS.find(x=>x[0]===m)||[0,m])[1].split(" ")[0]; }

function renderRight(){
  const rail=$("#rail-right"); rail.replaceChildren();
  const R=S.room, V=S.reverb, D=S.delay, g=G0;
  const mkG=(obj,gobj,o)=>slider({...o,get:()=>obj[o.key],set:v=>{obj[o.key]=v;},def:()=>gobj[o.key]});
  const grp=(title,obj,gobj,rows,keys,hint)=>{
    const gp=group(title,rows,()=>{ keys.forEach(k=>obj[k]=gobj[k]); },
      toggle(`${title} on or off`,()=>obj.enabled,v=>{obj.enabled=v; gp.classList.toggle("off",!v);},hint));
    gp.classList.toggle("off",!obj.enabled); return gp;
  };
  rail.append(grp("Room",R,g.room,[
    mkG(R,g.room,{key:"width",label:"Width",min:4,max:60,step:0.5,fmt:num(1," m"),hint:"Wider rooms push the echoes off the side walls later."}),
    mkG(R,g.room,{key:"depth",label:"Depth",min:4,max:60,step:0.5,fmt:num(1," m"),hint:"Deeper rooms push the front and back echoes later."}),
    mkG(R,g.room,{key:"absorption",label:"Wall softness",min:0,max:1,step:0.01,fmt:pct,hint:"0% is bare, bright walls with strong echoes. 100% soaks everything up."}),
  ],["enabled","width","depth","absorption"],"Turns the wall echoes on or off."));
  rail.append(grp("Reverb",V,g.reverb,[
    select("Type",[["fdn","Smooth (feedback network)"],["schroeder","Classic (Schroeder)"]],()=>V.kind,v=>{V.kind=v;},"The reverb algorithm. Smooth is denser; Classic is the one from the course notes."),
    mkG(V,g.reverb,{key:"t60",label:"Decay time",min:0.3,max:10,step:0.1,fmt:num(1," s"),hint:"How long the tail takes to fade away (T60)."}),
    mkG(V,g.reverb,{key:"damping",label:"Darkness",min:0,max:0.5,step:0.01,fmt:num(2),hint:"Higher makes the tail duller as it fades."}),
    mkG(V,g.reverb,{key:"size",label:"Space size",min:0.5,max:2.5,step:0.05,fmt:num(2,"×"),hint:"Stretches the internal delay lengths. Larger sounds like a bigger space."}),
    mkG(V,g.reverb,{key:"predelay",label:"Pre-delay",min:0,max:0.2,step:0.005,fmt:v=>Math.round(v*1000)+" ms",hint:"Silent gap before the reverb starts."}),
    mkG(V,g.reverb,{key:"level_db",label:"Level",min:-30,max:6,step:0.5,fmt:db,hint:"How loud the reverb is in the mix."}),
  ],["enabled","kind","t60","damping","size","predelay","level_db"],"Turns the reverb on or off."));
  rail.append(grp("Ping-pong echo",D,g.delay,[
    mkG(D,g.delay,{key:"time",label:"Time between echoes",min:0.05,max:1.5,step:0.005,fmt:v=>Math.round(v*1000)+" ms",hint:"Gap between repeats. Each repeat bounces to the other ear."}),
    mkG(D,g.delay,{key:"feedback",label:"Repeats",min:0,max:0.95,step:0.01,fmt:pct,hint:"How many times it repeats. Higher lasts longer."}),
    mkG(D,g.delay,{key:"level_db",label:"Level",min:-30,max:6,step:0.5,fmt:db,hint:"How loud the echoes are."}),
  ],["enabled","time","feedback","level_db"],"Turns the echo on or off."));
}


const map = $("#map"), ctx = map.getContext("2d");
let drawQueued=false, frozenView=null, drag=null;
function requestDraw(){ if (drawQueued) return; drawQueued=true; requestAnimationFrame(()=>{drawQueued=false; draw();}); }

function computeView(w,h_){
  let rx=8, ry=8;
  if (S.room.enabled){ rx=Math.max(rx,S.room.width/2); ry=Math.max(ry,S.room.depth/2); }
  for (const s of S.sources){
    const p=paths[s.id]; rx=Math.max(rx,Math.abs(s.x)); ry=Math.max(ry,Math.abs(s.y));
    if (p){ for (let i=0;i<p.x.length;i+=3){ rx=Math.max(rx,Math.abs(p.x[i])); ry=Math.max(ry,Math.abs(p.y[i])); } }
  }
  rx*=1.14; ry*=1.14;
  return {sc:Math.min((w/2)/rx,(h_/2)/ry), cx:w/2, cy:h_/2};
}
const toS=(v,x,y)=>[v.cx+x*v.sc, v.cy-y*v.sc];
const toW=(v,sx,sy)=>[(sx-v.cx)/v.sc, (v.cy-sy)/v.sc];

function posAt(s,t){
  const p=paths[s.id]; if (!p) return [s.x,s.y];
  const n=p.x.length, f=Math.max(0,Math.min(1,t/Math.max(S.length,0.001)))*(n-1), i=Math.floor(f), u=f-i, j=Math.min(i+1,n-1);
  return [p.x[i]+(p.x[j]-p.x[i])*u, p.y[i]+(p.y[j]-p.y[i])*u];
}
const playT = () => (rendered && audio) ? audio.currentTime : 0;

function resizeCanvas(){
  const dpr=window.devicePixelRatio||1, r=map.getBoundingClientRect();
  if (map.width!==Math.round(r.width*dpr)||map.height!==Math.round(r.height*dpr)){ map.width=Math.round(r.width*dpr); map.height=Math.round(r.height*dpr); }
  return {w:r.width,h:r.height,dpr};
}
function draw(){
  if (view!==1) return;
  const {w,h:hh,dpr}=resizeCanvas();
  ctx.setTransform(dpr,0,0,dpr,0,0);
  ctx.clearRect(0,0,w,hh);
  const bg=ctx.createRadialGradient(w/2,hh/2,10,w/2,hh/2,Math.max(w,hh)*0.7);
  bg.addColorStop(0,"#161d31"); bg.addColorStop(1,"#0c101c");
  ctx.fillStyle=bg; ctx.fillRect(0,0,w,hh);
  const v = frozenView || computeView(w,hh);
  const maxR = Math.max(w,hh)/2/v.sc;
  const steps=[1,2,5,10,20,50]; const step=steps.find(s=>maxR/s<=7)||50;
  ctx.lineWidth=1; ctx.font="11px "+getComputedStyle(document.body).fontFamily; ctx.textBaseline="middle";
  for (let r=step;r<maxR*1.5;r+=step){
    ctx.strokeStyle="rgba(150,165,205,.13)"; ctx.beginPath(); ctx.arc(v.cx,v.cy,r*v.sc,0,Math.PI*2); ctx.stroke();
    ctx.fillStyle="rgba(150,165,205,.55)"; ctx.textAlign="left"; ctx.fillText(r+" m",v.cx+r*v.sc*0.7071+4,v.cy-r*v.sc*0.7071);
  }
  ctx.strokeStyle="rgba(150,165,205,.12)"; ctx.beginPath(); ctx.moveTo(0,v.cy); ctx.lineTo(w,v.cy); ctx.moveTo(v.cx,0); ctx.lineTo(v.cx,hh); ctx.stroke();
  if (S.room.enabled){
    const [x0,y0]=toS(v,-S.room.width/2,S.room.depth/2), rw=S.room.width*v.sc, rh=S.room.depth*v.sc;
    ctx.fillStyle="rgba(255,207,107,.045)"; ctx.fillRect(x0,y0,rw,rh);
    ctx.strokeStyle="rgba(255,207,107,.55)"; ctx.lineWidth=2; ctx.strokeRect(x0,y0,rw,rh);
    ctx.fillStyle="rgba(255,207,107,.8)"; ctx.textAlign="left"; ctx.fillText(`room ${S.room.width.toFixed(0)} × ${S.room.depth.toFixed(0)} m`,x0+8,y0+14);
  }
  ctx.fillStyle="rgba(190,200,225,.6)"; ctx.font="600 12px "+getComputedStyle(document.body).fontFamily; ctx.textAlign="center";
  ctx.fillText("ahead",v.cx,14); ctx.fillText("behind",v.cx,hh-12);
  ctx.textAlign="left"; ctx.fillText("left",8,v.cy-12); ctx.textAlign="right"; ctx.fillText("right",w-8,v.cy-12);
  const t=playT();
  S.sources.forEach((s,i)=>{
    const p=paths[s.id], col=colorOf(i), on=i===sel;
    if (p && s.motion!=="Static"){
      ctx.strokeStyle=col; ctx.globalAlpha=on?0.9:0.38; ctx.lineWidth=on?2.5:1.5; ctx.setLineDash(on?[]:[5,5]);
      ctx.beginPath(); for (let k=0;k<p.x.length;k++){ const [sx,sy]=toS(v,p.x[k],p.y[k]); k?ctx.lineTo(sx,sy):ctx.moveTo(sx,sy); } ctx.stroke();
      ctx.setLineDash([]); ctx.globalAlpha=1;
      const [ax,ay]=toS(v,s.x,s.y);
      ctx.strokeStyle=col; ctx.lineWidth=2; ctx.beginPath(); ctx.arc(ax,ay,on?7:5,0,Math.PI*2); ctx.moveTo(ax-4,ay); ctx.lineTo(ax+4,ay); ctx.moveTo(ax,ay-4); ctx.lineTo(ax,ay+4); ctx.stroke();
    }
    const [px,py]=toS(v,...posAt(s,t)), live = !rendered || t>=s.start;
    ctx.globalAlpha=live?1:0.4;
    if (rendered && !audio.paused && live){ ctx.shadowColor=col; ctx.shadowBlur=18; }
    ctx.fillStyle=col; ctx.beginPath(); ctx.arc(px,py,on?12:10,0,Math.PI*2); ctx.fill();
    ctx.shadowBlur=0; ctx.globalAlpha=1;
    ctx.fillStyle="#0c101c"; ctx.font="700 12px "+getComputedStyle(document.body).fontFamily; ctx.textAlign="center"; ctx.fillText(String(i+1),px,py+0.5);
    if (on){ ctx.fillStyle="#edf0f7"; ctx.textAlign="left"; ctx.font="600 12px "+getComputedStyle(document.body).fontFamily; ctx.fillText(s.name,px+17,py); }
  });
  ctx.fillStyle="#edf0f7"; ctx.beginPath(); ctx.arc(v.cx,v.cy,9,0,Math.PI*2); ctx.fill();
  ctx.beginPath(); ctx.moveTo(v.cx-6,v.cy-6); ctx.lineTo(v.cx,v.cy-19); ctx.lineTo(v.cx+6,v.cy-6); ctx.fill();
  ctx.fillRect(v.cx-12,v.cy-3,4,7); ctx.fillRect(v.cx+8,v.cy-3,4,7);
  ctx.fillStyle="rgba(190,200,225,.7)"; ctx.font="12px "+getComputedStyle(document.body).fontFamily; ctx.textAlign="left"; ctx.fillText("you",v.cx+16,v.cy+14);
  if (!S.sources.length){ ctx.fillStyle="rgba(190,200,225,.7)"; ctx.textAlign="center"; ctx.font="14px "+getComputedStyle(document.body).fontFamily; ctx.fillText("Add a sound to see it here.",v.cx,v.cy+60); }
}

/* drag sounds on the map */
function pointer(e){ const r=map.getBoundingClientRect(); return [e.clientX-r.left,e.clientY-r.top]; }
function hit(sx,sy){
  const v=computeView(map.clientWidth,map.clientHeight), t=playT();
  for (let i=S.sources.length-1;i>=0;i--){
    const s=S.sources[i];
    for (const [x,y] of [[s.x,s.y],posAt(s,t)]){ const [px,py]=toS(v,x,y); if (Math.hypot(px-sx,py-sy)<=15) return i; }
  }
  return -1;
}
map.addEventListener("pointerdown",e=>{
  const [sx,sy]=pointer(e), i=hit(sx,sy); if (i<0) return;
  if (i!==sel){ sel=i; renderLeft(); }
  const v=computeView(map.clientWidth,map.clientHeight), s=S.sources[i], [wx,wy]=toW(v,sx,sy);
  frozenView=v; drag={i,ox:s.x-wx,oy:s.y-wy,lastX:s.x,lastY:s.y};
  map.setPointerCapture(e.pointerId); showHint("Release to drop it here.");
});
map.addEventListener("pointermove",e=>{
  const [sx,sy]=pointer(e);
  if (!drag){ map.style.cursor = hit(sx,sy)>=0 ? "grab" : "default"; return; }
  map.style.cursor="grabbing";
  const s=S.sources[drag.i], [wx,wy]=toW(frozenView,sx,sy);
  const nx=Math.round(Math.max(-15,Math.min(15,wx+drag.ox))*10)/10, ny=Math.round(Math.max(-15,Math.min(15,wy+drag.oy))*10)/10;
  const dx=nx-drag.lastX, dy=ny-drag.lastY; drag.lastX=nx; drag.lastY=ny;
  s.x=nx; s.y=ny;
  const p=paths[s.id]; if (p){ for (let k=0;k<p.x.length;k++){ p.x[k]+=dx; p.y[k]+=dy; } }
  $("#rail-left").querySelectorAll("input[data-key]").forEach(inp=>{ if (inp.dataset.key==="x"||inp.dataset.key==="y") inp.closest(".row").refresh(); });
  markDirty(); fetchScene(); requestDraw();
});
const endDrag=()=>{ if (drag){ drag=null; frozenView=null; showHint(); requestDraw(); } };
map.addEventListener("pointerup",endDrag); map.addEventListener("pointercancel",endDrag);
window.addEventListener("resize",requestDraw);

/* ------------------------------------------------------------------ render + playback */
const audio = new Audio();
audio.addEventListener("timeupdate",()=>{ updatePlayer(); requestDraw(); });
audio.addEventListener("ended",()=>{ audio.currentTime=0; updatePlayer(); requestDraw(); });
audio.addEventListener("play",()=>{ loop(); updatePlayer(); });
audio.addEventListener("pause",()=>{ updatePlayer(); requestDraw(); });
function loop(){ requestDraw(); if (!audio.paused) requestAnimationFrame(loop); }
const fmtT = s => { s=Math.max(0,s); return Math.floor(s/60)+":"+String(Math.floor(s%60)).padStart(2,"0"); };
function updatePlayer(){
  const ok=!!rendered, dur=ok?(audio.duration||rendered.duration):0;
  $("#btn-play").disabled=!ok; $("#scrub").disabled=!ok;
  $("#time").textContent = ok ? `${fmtT(audio.currentTime)} / ${fmtT(dur)}` : "Render to listen";
  const sc=$("#scrub"); if (ok){ sc.max=dur; if (document.activeElement!==sc) sc.value=audio.currentTime; sc.style.setProperty("--pct",(audio.currentTime/dur*100)+"%"); }
  $("#ico-play").innerHTML = audio.paused ? '<path d="M3 1.5v11l9-5.5z" fill="currentColor"/>' : '<path d="M2.5 1.5h3v11h-3zM8.5 1.5h3v11h-3z" fill="currentColor"/>';
  $("#btn-play").setAttribute("aria-label", audio.paused ? "Play" : "Pause");
  $("#btn-export").hidden=!ok;
  $("#btn-ab").hidden=!(ok&&previous); $("#btn-ab").textContent=showingPrev?"Hear latest":"Hear previous";
}
async function doRender(){
  if (rendering || !S.sources.length) return;
  rendering=true; updateButtons(); audio.pause();
  const t0=performance.now(), timer=setInterval(()=>say(`Rendering… ${((performance.now()-t0)/1000).toFixed(0)} s. Longer scenes and bigger reverbs take longer.`),500);
  say("Rendering…");
  try{
    const r=await fetch("/api/render",{method:"POST",body:payload()});
    if (!r.ok){ const j=await r.json().catch(()=>({})); throw new Error(j.error||`Server error ${r.status}`); }
    const blob=await r.blob();
    if (previous) URL.revokeObjectURL(previous.url);
    previous = rendered; showingPrev=false;
    rendered={url:URL.createObjectURL(blob),duration:parseFloat(r.headers.get("X-Duration"))||0};
    audio.src=rendered.url; audio.load(); $("#btn-export").href=rendered.url;
    dirty=false; clearInterval(timer);
    const ch=parseFloat(r.headers.get("X-Change"));
    let msg=`Rendered ${rendered.duration.toFixed(1)} s, including the reverb and echo tail. Playing now. Headphones on.`;
    if (!isNaN(ch)) msg += ch<0.005 ? " The audio is identical to your last render. Either nothing changed, or the control you moved has no effect in this scene." : ` Difference from your last render: ${Math.round(ch*100)}%. Use Hear previous to compare.`;
    say(msg, !isNaN(ch)&&ch<0.005 ? "err" : "ok");
    audio.currentTime=0; updatePlayer();
    audio.play().catch(()=>say("Rendered. Press the play button to listen.","ok"));
  }catch(err){
    clearInterval(timer);
    say(err.message==="Failed to fetch" ? "Lost contact with ECHO. Check that python app.py is still running." : err.message,"err");
  }finally{ clearInterval(timer); rendering=false; updateButtons(); updatePlayer(); }
}
$("#btn-render").addEventListener("click",doRender);
$("#btn-play").addEventListener("click",()=>{ audio.paused ? audio.play() : audio.pause(); });
$("#btn-ab").addEventListener("click",()=>{
  const t=audio.currentTime, wasPlaying=!audio.paused, target=showingPrev?rendered:previous;
  showingPrev=!showingPrev; audio.src=target.url; audio.load();
  audio.addEventListener("loadedmetadata",()=>{ audio.currentTime=Math.min(t,audio.duration||t); if (wasPlaying) audio.play().catch(()=>{}); updatePlayer(); },{once:true});
  say(showingPrev?"Playing the previous render.":"Playing the latest render.");
});
$("#scrub").addEventListener("input",e=>{ audio.currentTime=+e.target.value; });
document.addEventListener("keydown",e=>{
  if (view!==1 || e.target.closest("select,input[type=text],dialog")) return;
  if (e.key===" " && !e.target.closest("button")){ e.preventDefault(); if (rendered) audio.paused?audio.play():audio.pause(); else doRender(); }
  if ((e.key==="r"||e.key==="R") && !e.metaKey && !e.ctrlKey){ doRender(); }
});

function go(v){
  view=v; $("#setup").hidden=v!==0; $("#studio").hidden=v!==1;
  if (v===1){ if (sel>=S.sources.length) sel=0; renderLeft(); renderRight(); showHint(); requestAnimationFrame(()=>{ draw(); }); fetchScene(); updateStatus(); }
  else { renderSetup(); }
  updateButtons(); updatePlayer();
}
document.querySelectorAll("#steps button").forEach(b=>b.addEventListener("click",()=>{
  const i=+b.dataset.step; if (i===0) go(0); else if (i===1) go(1); else { go(1); rendered ? (audio.paused?audio.play():audio.pause()) : doRender(); }
}));
$("#btn-build").addEventListener("click",()=>{ if (!built) G0=snapshot({...S,sources:[]}); built=true; go(1); });


$("#btn-reset").addEventListener("click",()=>{
  if (view===0){ return; }
  S.length=G0.length; S.room={...G0.room}; S.reverb={...G0.reverb}; S.delay={...G0.delay};
  S.sources.forEach(s=>PARAM_KEYS.forEach(k=>s[k]=s.def[k]));
  syncLength(); renderLeft(); renderRight(); markDirty(); fetchScene(); requestDraw(); say("Sliders reset. Your sounds are unchanged.");
});
let armTimer=null;
$("#btn-start-over").addEventListener("click",e=>{
  const b=e.currentTarget;
  if (!b.classList.contains("armed")){
    b.classList.add("armed"); b.textContent="Click again to clear everything";
    armTimer=setTimeout(()=>disarm(b),3500); return;
  }
  disarm(b); audio.pause(); if (rendered) URL.revokeObjectURL(rendered.url);
  rendered=null; if (previous){URL.revokeObjectURL(previous.url); previous=null;} showingPrev=false; dirty=false; audio.removeAttribute("src"); S=freshState(); G0=snapshot(S); built=false; paths={}; sel=0; syncLength();
  go(0); say("");
});
function disarm(b){ clearTimeout(armTimer); b.classList.remove("armed"); b.textContent="Start over"; }

function syncLength(){
  for (const id of ["len-setup","len-studio"]){ const el=$("#"+id); el.value=S.length; el.style.setProperty("--pct",((S.length-3)/87*100)+"%"); $("#"+id+"-out").textContent=S.length+" s"; }
  document.querySelectorAll('#rail-left input[data-key="start"]').forEach(inp=>{ inp.max=S.length; if (+inp.value>S.length){ inp.value=S.length; inp.dispatchEvent(new Event("input")); } });
}
for (const id of ["len-setup","len-studio"]) $("#"+id).addEventListener("input",e=>{ S.length=+e.target.value; syncLength(); markDirty(); fetchScene(); requestDraw(); });


function renderSetup(){
  const kg=$("#kind-grid"); kg.replaceChildren();
  for (const k of catalog.kinds.filter(k=>!k.hidden)){
    const n=S.sources.filter(s=>s.kind===k.id).length;
    kg.append(h("button",{class:"card",onclick:()=>{ addSource(k.id); renderSetup(); }},
      n?h("i",{class:"count",text:String(n)}):null, h("b",{text:k.label}), h("span",{text:k.blurb})));
  }
  renderSetupBar();
}
function renderSetupBar(){
  const c=$("#chips"); c.replaceChildren();
  if (!S.sources.length) c.append(h("span",{class:"empty",text:"No sounds yet. Click one above or open a demo."}));
  S.sources.forEach((s,i)=>c.append(h("span",{class:"chip",style:`--c:${colorOf(i)}`},h("i"),s.name,
    h("button",{"aria-label":`Remove ${s.name}`,text:"✕",onclick:()=>{ removeSource(i); renderSetup(); }}))));
  $("#btn-build").disabled=!S.sources.length;
  $("#btn-build").textContent = built ? "Back to scene" : "Build scene";
  updateButtons();
}
function loadPreset(p){
  audio.pause(); if (previous){URL.revokeObjectURL(previous.url); previous=null;} showingPrev=false; if (rendered){ URL.revokeObjectURL(rendered.url); rendered=null; dirty=false; audio.removeAttribute("src"); }
  S={length:p.length,sources:[],room:{...ROOM0,...p.room},reverb:{...REVERB0,...p.reverb},delay:{...DELAY0,...p.delay}};
  for (const d of p.sources){ const {kind,name,...over}=d; S.sources.push(newSource(kind,over,"",name)); }
  G0=snapshot(S); built=true; sel=0; paths={}; syncLength(); go(1);
  say(`Loaded "${p.label}". Press Render and play, or drag sounds on the map first.`);
}
function presetState(p){
  const st={length:p.length,sources:[],room:{...ROOM0,...p.room}};
  for (const d of p.sources){ const {kind,name,...over}=d; const s=newSource(kind,over,"",name); st.sources.push(s); }
  return st;
}
async function renderPresetCards(){
  const grid=$("#preset-grid"); grid.replaceChildren();
  for (const p of catalog.presets){
    const cv=h("canvas",{width:460,height:200,"aria-hidden":"true"});
    grid.append(h("button",{class:"card",onclick:()=>loadPreset(p)},cv,h("b",{text:p.label}),h("span",{text:p.blurb})));
    const st=presetState(p);
    fetch("/api/scene",{method:"POST",body:JSON.stringify(st,(k,v)=>k==="def"?undefined:v)}).then(r=>r.json()).then(j=>drawMini(cv,st,j.paths)).catch(()=>{});
  }
}
function drawMini(cv,st,ps){
  const c=cv.getContext("2d"), w=cv.width, hh=cv.height; let rx=6, ry=6;
  if (st.room.enabled){ rx=Math.max(rx,st.room.width/2); ry=Math.max(ry,st.room.depth/2); }
  for (const s of st.sources){ const p=ps[s.id]; if(!p) continue; for(let i=0;i<p.x.length;i+=5){ rx=Math.max(rx,Math.abs(p.x[i])); ry=Math.max(ry,Math.abs(p.y[i])); } }
  rx*=1.1; ry*=1.1; const sc=Math.min(w/2/rx,hh/2/ry), cx=w/2, cy=hh/2;
  c.clearRect(0,0,w,hh);
  if (st.room.enabled){ c.strokeStyle="rgba(255,207,107,.6)"; c.lineWidth=2; c.strokeRect(cx-st.room.width/2*sc,cy-st.room.depth/2*sc,st.room.width*sc,st.room.depth*sc); }
  st.sources.forEach((s,i)=>{
    const p=ps[s.id]; if(!p) return; c.strokeStyle=colorOf(i); c.lineWidth=3; c.globalAlpha=.85; c.beginPath();
    for (let k=0;k<p.x.length;k++){ const X=cx+p.x[k]*sc, Y=cy-p.y[k]*sc; k?c.lineTo(X,Y):c.moveTo(X,Y); } c.stroke(); c.globalAlpha=1;
    c.fillStyle=colorOf(i); c.beginPath(); c.arc(cx+p.x[0]*sc,cy-p.y[0]*sc,6,0,7); c.fill();
  });
  c.fillStyle="#edf0f7"; c.beginPath(); c.arc(cx,cy,6,0,7); c.fill();
}


const dlg=$("#add-dialog");
function openAdd(){
  const g=$("#dlg-grid"); g.replaceChildren();
  for (const k of catalog.kinds.filter(k=>!k.hidden))
    g.append(h("button",{class:"card",onclick:()=>{ addSource(k.id); renderLeft(); requestDraw(); say(`Added ${S.sources[sel].name}.`); dlg.close(); }},h("b",{text:k.label}),h("span",{text:k.blurb})));
  dlg.showModal();
}
$("#dlg-close").addEventListener("click",()=>dlg.close());


async function uploadFile(f){
  if (!f) return;
  say(`Loading ${f.name}…`);
  try{
    const r=await fetch("/api/upload?name="+encodeURIComponent(f.name),{method:"POST",body:f});
    const j=await r.json(); if (!r.ok) throw new Error(j.error);
    addSource("file",{},j.id,uniqueName(j.name.replace(/\.[^.]+$/,"")));
    say(`Added ${S.sources[sel].name} (${j.seconds} s).`,"ok");
    if (view===0) renderSetup(); else renderLeft();
  }catch(err){ say(err.message,"err"); alert(err.message); }
}
$("#btn-file").addEventListener("click",()=>$("#file-input").click());
$("#dlg-file").addEventListener("click",()=>{ dlg.close(); $("#file-input").click(); });
$("#file-input").addEventListener("change",e=>{ uploadFile(e.target.files[0]); e.target.value=""; });
$("#btn-fs").addEventListener("click",async()=>{
  const id=$("#fs-id").value.trim(); if (!/^\d+$/.test(id)){ alert("Enter the number from the Freesound page address."); return; }
  try{
    const r=await fetch("/api/probe",{method:"POST",body:JSON.stringify({kind:"freesound",arg:id})}); const j=await r.json(); if (!r.ok) throw new Error(j.error);
    addSource("freesound",{},id,uniqueName("Freesound "+id)); renderSetup(); $("#fs-id").value="";
  }catch(err){ alert("Couldn't fetch that sound: "+err.message); }
});

(async function(){
  try{ catalog = await (await fetch("/api/catalog")).json(); }
  catch(e){ document.body.innerHTML='<p style="padding:40px">Can\'t reach ECHO. Start it with <code>python app.py</code>.</p>'; return; }
  syncLength(); renderSetup(); renderPresetCards(); updateButtons(); updatePlayer();
})();
