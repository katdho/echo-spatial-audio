/* scene.js: Scene data from the backend (/api/scene) and the room map:
drawing, source paths, and drag-to-move interaction */

import { $, S, ui, colorOf, payload } from "./state.js";
import { markDirty, showHint, renderLeft } from "./controls.js";
import { audio } from "./audio.js";

/* ------------------------------------------------------------------ scene data */
let sceneBusy = false;
let scenePending = false;

export async function fetchScene() {
  if (sceneBusy) { scenePending = true; return; }
  sceneBusy = true;
  try {
    const r = await fetch("/api/scene", { method: "POST", body: payload() });
    const j = await r.json();
    if (j.paths) ui.paths = j.paths;
  } catch (e) { /* Server stopped: the status line reports it on render. */ }
  sceneBusy = false;
  if (scenePending) { scenePending = false; fetchScene(); }
  requestDraw();
}

/* ------------------------------------------------------------------ room map */
const map = $("#map");
const ctx = map.getContext("2d");
let drawQueued = false;
let frozenView = null;   // view held fixed while dragging so the map doesn't rescale under the cursor
let drag = null;

const font = spec => spec + " " + getComputedStyle(document.body).fontFamily;

export function requestDraw() {
  if (drawQueued) return;
  drawQueued = true;
  requestAnimationFrame(() => { drawQueued = false; draw(); });
}

function computeView(w, h_) {
  let rx = 8, ry = 8;
  if (S.room.enabled) { rx = Math.max(rx, S.room.width / 2); ry = Math.max(ry, S.room.depth / 2); }
  for (const s of S.sources) {
    const p = ui.paths[s.id];
    rx = Math.max(rx, Math.abs(s.x));
    ry = Math.max(ry, Math.abs(s.y));
    if (p) for (let i = 0; i < p.x.length; i += 3) { rx = Math.max(rx, Math.abs(p.x[i])); ry = Math.max(ry, Math.abs(p.y[i])); }
  }
  rx *= 1.14;
  ry *= 1.14;
  return { sc: Math.min((w / 2) / rx, (h_ / 2) / ry), cx: w / 2, cy: h_ / 2 };
}

const toS = (v, x, y) => [v.cx + x * v.sc, v.cy - y * v.sc];
const toW = (v, sx, sy) => [(sx - v.cx) / v.sc, (v.cy - sy) / v.sc];

function posAt(s, t) {
  const p = ui.paths[s.id];
  if (!p) return [s.x, s.y];
  const n = p.x.length;
  const f = Math.max(0, Math.min(1, t / Math.max(S.length, 0.001))) * (n - 1);
  const i = Math.floor(f), u = f - i, j = Math.min(i + 1, n - 1);
  return [p.x[i] + (p.x[j] - p.x[i]) * u, p.y[i] + (p.y[j] - p.y[i]) * u];
}

const playT = () => ui.rendered ? audio.currentTime : 0;

function resizeCanvas() {
  const dpr = window.devicePixelRatio || 1;
  const r = map.getBoundingClientRect();
  if (map.width !== Math.round(r.width * dpr) || map.height !== Math.round(r.height * dpr)) { map.width = Math.round(r.width * dpr); map.height = Math.round(r.height * dpr); }
  return { w: r.width, h: r.height, dpr };
}

export function draw() {
  if (ui.view !== 1) return;
  const { w, h: hh, dpr } = resizeCanvas();
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, hh);
  const bg = ctx.createRadialGradient(w / 2, hh / 2, 10, w / 2, hh / 2, Math.max(w, hh) * 0.7);
  bg.addColorStop(0, "#161d31");
  bg.addColorStop(1, "#0c101c");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, w, hh);

  // distance rings and axes
  const v = frozenView || computeView(w, hh);
  const maxR = Math.max(w, hh) / 2 / v.sc;
  const step = [1, 2, 5, 10, 20, 50].find(s => maxR / s <= 7) || 50;
  ctx.lineWidth = 1;
  ctx.font = font("11px");
  ctx.textBaseline = "middle";
  for (let r = step; r < maxR * 1.5; r += step) {
    ctx.strokeStyle = "rgba(150,165,205,.13)";
    ctx.beginPath();
    ctx.arc(v.cx, v.cy, r * v.sc, 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillStyle = "rgba(150,165,205,.55)";
    ctx.textAlign = "left";
    ctx.fillText(r + " m", v.cx + r * v.sc * 0.7071 + 4, v.cy - r * v.sc * 0.7071);
  }
  ctx.strokeStyle = "rgba(150,165,205,.12)";
  ctx.beginPath();
  ctx.moveTo(0, v.cy);
  ctx.lineTo(w, v.cy);
  ctx.moveTo(v.cx, 0);
  ctx.lineTo(v.cx, hh);
  ctx.stroke();

  // room outline
  if (S.room.enabled) {
    const [x0, y0] = toS(v, -S.room.width / 2, S.room.depth / 2);
    ctx.fillStyle = "rgba(255,207,107,.045)";
    ctx.fillRect(x0, y0, S.room.width * v.sc, S.room.depth * v.sc);
    ctx.strokeStyle = "rgba(255,207,107,.55)";
    ctx.lineWidth = 2;
    ctx.strokeRect(x0, y0, S.room.width * v.sc, S.room.depth * v.sc);
    ctx.fillStyle = "rgba(255,207,107,.8)";
    ctx.textAlign = "left";
    ctx.fillText(`room ${S.room.width.toFixed(0)} × ${S.room.depth.toFixed(0)} m`, x0 + 8, y0 + 14);
  }

  // direction labels
  ctx.fillStyle = "rgba(190,200,225,.6)";
  ctx.font = font("600 12px");
  ctx.textAlign = "center";
  ctx.fillText("ahead", v.cx, 14);
  ctx.fillText("behind", v.cx, hh - 12);
  ctx.textAlign = "left";
  ctx.fillText("left", 8, v.cy - 12);
  ctx.textAlign = "right";
  ctx.fillText("right", w - 8, v.cy - 12);

  // sources and their paths
  const t = playT();
  S.sources.forEach((s, i) => {
    const p = ui.paths[s.id];
    const col = colorOf(i);
    const on = i === ui.sel;
    if (p && (s.motion !== "Static" || s.path)) {
      ctx.strokeStyle = col;
      ctx.globalAlpha = on ? 0.9 : 0.38;
      ctx.lineWidth = on ? 2.5 : 1.5;
      ctx.setLineDash(on ? [] : [5, 5]);
      ctx.beginPath();
      for (let k = 0; k < p.x.length; k++) { const [sx, sy] = toS(v, p.x[k], p.y[k]); k ? ctx.lineTo(sx, sy) : ctx.moveTo(sx, sy); }
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
      if (!s.path) {   // the centre marker means nothing for a keyframed path
        const [ax, ay] = toS(v, s.x, s.y);
        ctx.strokeStyle = col;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(ax, ay, on ? 7 : 5, 0, Math.PI * 2);
        ctx.moveTo(ax - 4, ay);
        ctx.lineTo(ax + 4, ay);
        ctx.moveTo(ax, ay - 4);
        ctx.lineTo(ax, ay + 4);
        ctx.stroke();
      }
    }
    const [px, py] = toS(v, ...posAt(s, t));
    const live = !ui.rendered || t >= s.start;
    ctx.globalAlpha = live ? 1 : 0.4;
    if (ui.rendered && !audio.paused && live) { ctx.shadowColor = col; ctx.shadowBlur = 18; }
    ctx.fillStyle = col;
    ctx.beginPath();
    ctx.arc(px, py, on ? 12 : 10, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.globalAlpha = 1;
    ctx.fillStyle = "#0c101c";
    ctx.font = font("700 12px");
    ctx.textAlign = "center";
    ctx.fillText(String(i + 1), px, py + 0.5);
    if (on) {
      ctx.fillStyle = "#edf0f7";
      ctx.textAlign = "left";
      ctx.font = font("600 12px");
      ctx.fillText(s.name, px + 17, py);
    }
  });

  // the listener at the center of the room
  ctx.fillStyle = "#edf0f7";
  ctx.beginPath();
  ctx.arc(v.cx, v.cy, 9, 0, Math.PI * 2);
  ctx.fill();
  ctx.beginPath();
  ctx.moveTo(v.cx - 6, v.cy - 6);
  ctx.lineTo(v.cx, v.cy - 19);
  ctx.lineTo(v.cx + 6, v.cy - 6);
  ctx.fill();
  ctx.fillRect(v.cx - 12, v.cy - 3, 4, 7);
  ctx.fillRect(v.cx + 8, v.cy - 3, 4, 7);
  ctx.fillStyle = "rgba(190,200,225,.7)";
  ctx.font = font("12px");
  ctx.textAlign = "left";
  ctx.fillText("you", v.cx + 16, v.cy + 14);
  if (!S.sources.length) {
    ctx.fillStyle = "rgba(190,200,225,.7)";
    ctx.textAlign = "center";
    ctx.font = font("14px");
    ctx.fillText("Add a sound to see it here.", v.cx, v.cy + 60);
  }
}

/* ------------------------------------------------------------------ map interaction */
function pointer(e) { const r = map.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }

function hit(sx, sy) {
  const v = computeView(map.clientWidth, map.clientHeight);
  const t = playT();
  for (let i = S.sources.length - 1; i >= 0; i--) {
    const s = S.sources[i];
    for (const [x, y] of s.path ? [posAt(s, t)] : [[s.x, s.y], posAt(s, t)]) {
      const [px, py] = toS(v, x, y);
      if (Math.hypot(px - sx, py - sy) <= 15) return i;
    }
  }
  return -1;
}

map.addEventListener("pointerdown", e => {
  const [sx, sy] = pointer(e);
  const i = hit(sx, sy);
  if (i < 0) return;
  if (i !== ui.sel) { ui.sel = i; renderLeft(); }
  if (S.sources[i].path) {   // keyframed: the path, not x/y, decides where it is
    showHint("This sound follows keyframes, so it can't be dragged. Choose a Movement Pattern to replace them.");
    setTimeout(() => showHint(), 3500);
    return;
  }
  const v = computeView(map.clientWidth, map.clientHeight);
  const s = S.sources[i];
  const [wx, wy] = toW(v, sx, sy);
  frozenView = v;
  drag = { i, ox: s.x - wx, oy: s.y - wy, lastX: s.x, lastY: s.y };
  map.setPointerCapture(e.pointerId);
  showHint("Release to drop it here.");
});

map.addEventListener("pointermove", e => {
  const [sx, sy] = pointer(e);
  if (!drag) { map.style.cursor = hit(sx, sy) >= 0 ? "grab" : "default"; return; }
  map.style.cursor = "grabbing";
  const s = S.sources[drag.i];
  const [wx, wy] = toW(frozenView, sx, sy);
  const nx = Math.round(Math.max(-15, Math.min(15, wx + drag.ox)) * 10) / 10;
  const ny = Math.round(Math.max(-15, Math.min(15, wy + drag.oy)) * 10) / 10;
  const dx = nx - drag.lastX, dy = ny - drag.lastY;
  drag.lastX = nx;
  drag.lastY = ny;
  s.x = nx;
  s.y = ny;
  const p = ui.paths[s.id];
  if (p) for (let k = 0; k < p.x.length; k++) { p.x[k] += dx; p.y[k] += dy; }
  $("#rail-left").querySelectorAll("input[data-key]").forEach(inp => { 
    if (inp.dataset.key === "x" || inp.dataset.key === "y") inp.closest(".row").refresh(); });
  markDirty();
  fetchScene();
  requestDraw();
});

const endDrag = () => {
  if (!drag) return;
  drag = null;
  frozenView = null;
  showHint();
  requestDraw();
};

map.addEventListener("pointerup", endDrag);
map.addEventListener("pointercancel", endDrag);
window.addEventListener("resize", requestDraw);