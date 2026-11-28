/* automation.js: Keyframe editor under the room map.

Tabs choose what to automate for the selected sound (Volume, Reverb amount, Doppler),
for the whole scene (Echo repeats), or the sound's Position. Each tab is a graph of
value against time: click to add a point, drag to move it, double-click or right-click
to delete. A tab with no points leaves the normal slider in charge.

Data lives in the shared scene state and is sent to the server with everything else:
  S.sources[i].automation = { gain: [[t, dB(, shape)], ...], send: [...], doppler: [...] }
  S.sources[i].path       = [[t, x, y(, shape)], ...]       (Position)
  S.automation            = { delay_feedback: [[t, value(, shape)], ...] }
`shape` is "smoothstep" (eased) or missing (straight). The shape of a point applies to
the stretch that STARTS at that point. See echo/automation.py for the exact rules.

Position keyframes are edited on the map too: pick a time on the strip under the map,
then drag the sound where it should be at that time. */

import { $, h, S, ui, colorOf } from "./state.js";
import { markDirty, renderLeft, renderRight } from "./controls.js";
import { requestDraw, fetchScene, computeView, toS, toW, posAt, freezeView } from "./scene.js";
import { audio } from "./audio.js";

const GOLD = "#ffcf6b";
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const snap = (v, step) => Math.round(v / step) * step;
const r1 = v => Math.round(v * 10) / 10;
const smooth = u => u * u * (3 - 2 * u);
const fmtDb = v => (v > 0 ? "+" : "") + v.toFixed(1) + " dB";
const fmtPct = v => Math.round(v * 100) + "%";


const LANES = [
  { id: "gain", label: "Volume", scope: "source", min: -40, max: 6, step: 0.5, fmt: fmtDb, base: s => s.gain },
  { id: "send", label: "Reverb amount", scope: "source", min: 0, max: 1, step: 0.01, fmt: fmtPct, base: s => s.send },
  { id: "doppler", label: "Doppler", scope: "source", min: 0, max: 3, step: 0.05, fmt: v => v.toFixed(2) + "x", base: s => s.doppler },
  { id: "delay_feedback", label: "Echo repeats", scope: "scene", min: 0, max: 0.95, step: 0.01, fmt: fmtPct, base: () => S.delay.feedback },
  { id: "path", label: "Position", scope: "path" }
];

let cur = "gain";    
let selKf = -1;       
let editT = 0;        

const laneDef = () => LANES.find(l => l.id === cur);
const src = () => S.sources[ui.sel];
const shapeIdx = l => l.scope === "path" ? 3 : 2;


function rowsOf(l) {
  if (l.scope === "scene") return (S.automation && S.automation[l.id]) || null;
  const s = src();
  if (!s) return null;
  if (l.scope === "path") return s.path || null;
  return (s.automation && s.automation[l.id]) || null;
}

function setRowsOf(l, arr) {
  if (l.scope === "scene") {
    if (!S.automation) S.automation = {};
    if (arr) S.automation[l.id] = arr; else delete S.automation[l.id];
    return;
  }
  const s = src();
  if (l.scope === "path") { if (arr) s.path = arr; else delete s.path; return; }
  if (!s.automation) s.automation = {};
  if (arr) s.automation[l.id] = arr; else delete s.automation[l.id];
}

function insertRow(arr, row) {
  let i = 0;
  while (i < arr.length && arr[i][0] <= row[0]) i++;
  arr.splice(i, 0, row);
  return i;
}

function evalRows(r, vi, si, t) {
  const n = r.length;
  if (t < r[0][0]) return r[0][vi];
  if (t >= r[n - 1][0]) return r[n - 1][vi];
  let i = 0;
  while (i + 1 < n && r[i + 1][0] <= t) i++;
  const t0 = r[i][0], t1 = r[i + 1][0];
  let u = t1 > t0 ? (t - t0) / (t1 - t0) : 1;
  if (r[i][si] === "smoothstep") u = smooth(u);
  return r[i][vi] + (r[i + 1][vi] - r[i][vi]) * u;
}


function structureChanged() { renderLeft(); renderRight(); markDirty(); requestDraw(); }


function helpFor() {
  const l = laneDef(), s = src();
  if (!s) return "";
  if (l.scope === "path") {
    return s.path
      ? "Pick a time on the strip (click it, or click a diamond). Then drag the sound on the map to set where it is at that time. Diamonds on the map can be dragged too."
      : "Position keyframes replace this sound's Movement Pattern. Start from where it is now, then place it at other times.";
  }
  const r = rowsOf(l);
  const off = l.scope === "scene" && !S.delay.enabled ? "The ping-pong echo is off (right panel), so this has no effect yet. " : "";
  if (!r) return `${off}${l.label} stays at ${l.fmt(l.base(s))}. Click the graph to start automating it.`;
  return `${off}Click to add a point. Drag a point to move it. Double-click or right-click a point to delete it.`;
}

const setHelp = t => { $("#lane-help").textContent = t; };

export function renderLanes() {
  const box = $("#lanes"), s = src();
  box.hidden = !s;
  if (!s) return;
  box.style.setProperty("--c", cur === "delay_feedback" ? GOLD : colorOf(ui.sel));
  const l = laneDef(), r = rowsOf(l), si = shapeIdx(l);

  const tabs = h("div", { class: "lane-tabs", role: "group", "aria-label": "What to automate" },
    LANES.map(t => h("button", {
      class: "lane-tab" + (t.id === cur ? " cur" : ""),
      "aria-pressed": t.id === cur,
      onclick: () => { cur = t.id; selKf = -1; renderLanes(); requestDraw(); }
    }, rowsOf(t) ? h("span", { class: "dot" }) : null, t.label)));

  const btn = (text, fn, disabled = false, title = "") =>
    h("button", { class: "btn", text, onclick: fn, disabled, title });
  const tools = h("div", { class: "lane-tools" });
  const hasSel = !!r && selKf >= 0 && selKf < r.length;
  const canShape = hasSel && selKf < r.length - 1;
  const shapeText = canShape && r[selKf][si] === "smoothstep" ? "Curve after point: Smooth" : "Curve after point: Straight";

  if (l.scope === "path" && !r) {
    tools.append(btn("Start keyframes", startPath, false, "Begin at the sound's current position"));
  } else if (r) {
    if (l.scope === "path") tools.append(btn("Add keyframe here", addHere, false, "Add a keyframe at the time cursor, where the sound is now"));
    tools.append(
      btn("Delete point", deleteSel, !hasSel, "Or double-click / right-click a point"),
      btn(shapeText, toggleShape, !canShape, "Straight moves at a steady rate. Smooth eases in and out of the points"),
      btn("Smooth all", smoothAll, false, "Ease every stretch"),
      btn(l.scope === "path" ? "Stop keyframing" : "Clear", clearLane, false,
        l.scope === "path" ? "Go back to the Movement Pattern" : "Go back to the slider's value"));
  }
  $("#lane-bar").replaceChildren(tabs, tools);
  setHelp(helpFor());
}

function startPath() {
  const s = src();
  const [x, y] = posAt(s, 0);
  s.path = [[0, r1(x), r1(y)]];
  selKf = 0;
  editT = 0;
  structureChanged();
  fetchScene();
}

function ensureNode(s, t, x, y) {
  const i = s.path.findIndex(p => Math.abs(p[0] - t) < 0.05);
  return i >= 0 ? i : insertRow(s.path, [t, r1(x), r1(y)]);
}

function addHere() {
  const s = src();
  const [x, y] = posAt(s, editT);
  selKf = ensureNode(s, editT, x, y);
  structureChanged();
  fetchScene();
}

function deleteSel() {
  const l = laneDef(), r = rowsOf(l);
  if (!r || selKf < 0 || selKf >= r.length) return;
  r.splice(selKf, 1);
  selKf = -1;
  if (!r.length) setRowsOf(l, null);
  structureChanged();
  if (l.scope === "path") fetchScene();
}

function toggleShape() {
  const l = laneDef(), r = rowsOf(l), si = shapeIdx(l);
  if (!r || selKf < 0 || selKf >= r.length - 1) return;
  r[selKf][si] = r[selKf][si] === "smoothstep" ? "linear" : "smoothstep";
  renderLanes();
  markDirty();
  requestDraw();
  if (l.scope === "path") fetchScene();
}

function smoothAll() {
  const l = laneDef(), r = rowsOf(l), si = shapeIdx(l);
  if (!r) return;
  r.forEach((row, i) => { if (i < r.length - 1) row[si] = "smoothstep"; });
  renderLanes();
  markDirty();
  requestDraw();
  if (l.scope === "path") fetchScene();
}

function clearLane() {
  const l = laneDef();
  setRowsOf(l, null);
  selKf = -1;
  structureChanged();
  if (l.scope === "path") fetchScene();
}


const cv = $("#lane-canvas");
const cx = cv.getContext("2d");
const M = { l: 48, r: 14, t: 10, b: 22 };      
let drag = null;                           

function fit() {
  const dpr = window.devicePixelRatio || 1;
  const r = cv.getBoundingClientRect();
  if (cv.width !== Math.round(r.width * dpr) || cv.height !== Math.round(r.height * dpr)) {
    cv.width = Math.round(r.width * dpr);
    cv.height = Math.round(r.height * dpr);
  }
  return { w: r.width, h: r.height, dpr };
}

const tx = (t, w) => M.l + (t / Math.max(S.length, 0.001)) * (w - M.l - M.r);
const tInv = (x, w) => (x - M.l) / (w - M.l - M.r) * S.length;
const vy = (v, l, hh) => M.t + (1 - (v - l.min) / (l.max - l.min)) * (hh - M.t - M.b);
const vInv = (y, l, hh) => l.min + (1 - (y - M.t) / (hh - M.t - M.b)) * (l.max - l.min);
const midY = hh => M.t + (hh - M.t - M.b) / 2;
const kfY = (l, row, hh) => l.scope === "path" ? midY(hh) : vy(row[1], l, hh);

function curvePoints(r, l, w, hh) {
  const X = t => tx(t, w), Y = v => vy(v, l, hh);
  const pts = [[M.l - 40, Y(r[0][1])]];
  for (let i = 0; i < r.length; i++) {
    const t0 = r[i][0], v0 = r[i][1];
    pts.push([X(t0), Y(v0)]);
    if (i + 1 < r.length) {
      const t1 = r[i + 1][0], v1 = r[i + 1][1];
      const ease = r[i][2] === "smoothstep";
      const K = ease ? 24 : 1;
      for (let k = 1; k <= K; k++) {
        const u = k / K;
        pts.push([X(t0 + (t1 - t0) * u), Y(v0 + (v1 - v0) * (ease ? smooth(u) : u))]);
      }
    }
  }
  pts.push([w + 40, Y(r[r.length - 1][1])]);
  return pts;
}

export function drawLanes() {
  const { w, h: hh, dpr } = fit();
  cx.setTransform(dpr, 0, 0, dpr, 0, 0);
  cx.clearRect(0, 0, w, hh);
  const s = src();
  if (!s || $("#lanes").hidden) return;
  const l = laneDef(), r = rowsOf(l);
  const col = cur === "delay_feedback" ? GOLD : colorOf(ui.sel);
  const fontFam = getComputedStyle(document.body).fontFamily;
  const plotW = w - M.l - M.r, plotH = hh - M.t - M.b;

  // time axis
  cx.font = "11px " + fontFam;
  cx.textBaseline = "top";
  cx.textAlign = "center";
  const step = [1, 2, 5, 10, 15, 30, 60].find(v => S.length / v <= 10) || 60;
  for (let t = 0; t <= S.length + 1e-6; t += step) {
    const x = tx(t, w);
    cx.strokeStyle = "rgba(150,165,205,.10)";
    cx.beginPath(); cx.moveTo(x, M.t); cx.lineTo(x, M.t + plotH); cx.stroke();
    cx.fillStyle = "rgba(150,165,205,.6)";
    cx.fillText(t + " s", x, M.t + plotH + 5);
  }

  // value axis
  if (l.scope !== "path") {
    cx.textAlign = "right";
    cx.textBaseline = "middle";
    for (const v of [l.min, (l.min + l.max) / 2, l.max]) {
      const y = vy(v, l, hh);
      cx.strokeStyle = "rgba(150,165,205,.13)";
      cx.beginPath(); cx.moveTo(M.l, y); cx.lineTo(M.l + plotW, y); cx.stroke();
      cx.fillStyle = "rgba(150,165,205,.6)";
      cx.fillText(l.fmt(v), M.l - 6, y);
    }
  } else {
    cx.strokeStyle = "rgba(150,165,205,.2)";
    cx.beginPath(); cx.moveTo(M.l, midY(hh)); cx.lineTo(M.l + plotW, midY(hh)); cx.stroke();
  }

  cx.save();
  cx.beginPath(); cx.rect(M.l, 0, plotW, hh); cx.clip();

  if (l.scope !== "path") {
    if (r) {
      cx.strokeStyle = col; cx.lineWidth = 2.5;
      cx.beginPath();
      curvePoints(r, l, w, hh).forEach(([x, y], i) => i ? cx.lineTo(x, y) : cx.moveTo(x, y));
      cx.stroke();
    } else {
      const y = vy(clamp(l.base(s), l.min, l.max), l, hh);
      cx.strokeStyle = col; cx.globalAlpha = 0.5; cx.lineWidth = 1.5; cx.setLineDash([6, 5]);
      cx.beginPath(); cx.moveTo(M.l, y); cx.lineTo(M.l + plotW, y); cx.stroke();
      cx.setLineDash([]); cx.globalAlpha = 1;
    }
  }

  // points
  if (r) {
    r.forEach((row, i) => {
      const x = tx(row[0], w), y = kfY(l, row, hh), on = i === selKf;
      cx.fillStyle = on ? GOLD : col;
      cx.strokeStyle = "#0c101c"; cx.lineWidth = 2;
      cx.beginPath();
      if (l.scope === "path") {                     
        const q = on ? 7 : 5.5;
        cx.moveTo(x, y - q); cx.lineTo(x + q, y); cx.lineTo(x, y + q); cx.lineTo(x - q, y); cx.closePath();
      } else {
        cx.arc(x, y, on ? 7 : 5, 0, Math.PI * 2);
      }
      cx.fill(); cx.stroke();
    });
  }

  if (l.scope === "path" && s.path) {
    const x = tx(editT, w);
    cx.strokeStyle = GOLD; cx.lineWidth = 1.5; cx.setLineDash([4, 3]);
    cx.beginPath(); cx.moveTo(x, M.t); cx.lineTo(x, M.t + plotH); cx.stroke();
    cx.setLineDash([]);
    cx.fillStyle = GOLD; cx.textAlign = "left"; cx.textBaseline = "top"; cx.font = "600 11px " + fontFam;
    cx.fillText(editT.toFixed(1) + " s", x + 5, M.t + 2);
  }
  if (ui.rendered) {
    const x = tx(audio.currentTime, w);
    cx.strokeStyle = "rgba(237,240,247,.75)"; cx.lineWidth = 1.5;
    cx.beginPath(); cx.moveTo(x, M.t); cx.lineTo(x, M.t + plotH); cx.stroke();
  }
  cx.restore();
}


const ptr = e => { const b = cv.getBoundingClientRect(); return [e.clientX - b.left, e.clientY - b.top]; };
const size = () => ({ w: cv.clientWidth, h: cv.clientHeight });
const inPlot = (px, py, w, hh) => px >= M.l && px <= w - M.r && py >= M.t && py <= hh - M.b;

function hitKf(r, l, px, py, w, hh) {
  let best = -1, bd = 11;
  r.forEach((row, i) => {
    const d = Math.hypot(px - tx(row[0], w), py - kfY(l, row, hh));
    if (d < bd) { bd = d; best = i; }
  });
  return best;
}

cv.addEventListener("pointerdown", e => {
  const s = src();
  if (!s || e.button === 2) return;
  cv.focus();
  const l = laneDef(), r = rowsOf(l), { w, h: hh } = size();
  const [px, py] = ptr(e);

  if (l.scope === "path") {
    if (!r) return;
    const i = hitKf(r, l, px, py, w, hh);
    if (i >= 0) { selKf = i; editT = r[i][0]; drag = { kind: "kf", i }; }
    else { selKf = -1; editT = clamp(snap(tInv(px, w), 0.1), 0, S.length); drag = { kind: "cursor" }; }
    cv.setPointerCapture(e.pointerId);
    renderLanes();
    requestDraw();
    return;
  }

  let i = r ? hitKf(r, l, px, py, w, hh) : -1;
  if (i >= 0) {
    selKf = i;
    renderLanes();
  } else {
    if (!inPlot(px, py, w, hh)) return;
    const t = clamp(snap(tInv(px, w), 0.1), 0, S.length);
    const v = clamp(snap(vInv(py, l, hh), l.step), l.min, l.max);
    if (!r) {
      const base = clamp(l.base(s), l.min, l.max);
      const arr = t > 0.05 ? [[0, base], [t, v]] : [[0, v]];
      setRowsOf(l, arr);
      i = arr.length - 1;
      selKf = i;
      structureChanged();
    } else {
      i = insertRow(r, [t, v]);
      selKf = i;
      renderLanes();
      markDirty();
    }
  }
  drag = { kind: "kf", i };
  cv.setPointerCapture(e.pointerId);
  requestDraw();
});

cv.addEventListener("pointermove", e => {
  const s = src();
  if (!s) return;
  const l = laneDef(), r = rowsOf(l), { w, h: hh } = size();
  const [px, py] = ptr(e);

  if (!drag) {
    const i = r ? hitKf(r, l, px, py, w, hh) : -1;
    cv.style.cursor = i >= 0 ? "grab" : (l.scope === "path" && !r ? "default" : "crosshair");
    if (l.scope !== "path" && r && inPlot(px, py, w, hh)) {
      const t = clamp(tInv(px, w), 0, S.length);
      setHelp(`${l.label} at ${t.toFixed(1)} s: ${l.fmt(evalRows(r, 1, 2, t))}`);
    }
    return;
  }
  if (drag.kind === "cursor") {
    editT = clamp(snap(tInv(px, w), 0.1), 0, S.length);
    requestDraw();
    return;
  }
  if (!r || !r[drag.i]) return;
  const row = r[drag.i];
  const lo = drag.i > 0 ? r[drag.i - 1][0] + 0.05 : 0;
  const hi = drag.i < r.length - 1 ? r[drag.i + 1][0] - 0.05 : S.length;
  row[0] = clamp(snap(tInv(px, w), 0.1), lo, Math.max(lo, hi));
  if (l.scope === "path") {
    editT = row[0];
    fetchScene();
  } else {
    row[1] = clamp(snap(vInv(py, l, hh), l.step), l.min, l.max);
    setHelp(`${l.label} at ${row[0].toFixed(1)} s: ${l.fmt(row[1])}`);
  }
  markDirty();
  requestDraw();
});

const endDrag = () => { if (drag) { drag = null; renderLanes(); requestDraw(); } };
cv.addEventListener("pointerup", endDrag);
cv.addEventListener("pointercancel", endDrag);
cv.addEventListener("pointerleave", () => { if (!drag) setHelp(helpFor()); });

function deleteAt(e) {
  const l = laneDef(), r = rowsOf(l), { w, h: hh } = size();
  if (!r) return false;
  const [px, py] = ptr(e);
  const i = hitKf(r, l, px, py, w, hh);
  if (i < 0) return false;
  selKf = i;
  deleteSel();
  return true;
}
cv.addEventListener("dblclick", e => { deleteAt(e); });
cv.addEventListener("contextmenu", e => { e.preventDefault(); deleteAt(e); });
cv.addEventListener("keydown", e => {
  if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); deleteSel(); }
});
window.addEventListener("resize", requestDraw);

export const scrubTime = () => (cur === "path" && src() && src().path ? editT : null);

export function drawKeyframes(ctx, v, s, i) {
  if (cur !== "path" || s !== src() || !s.path) return;
  const col = colorOf(i);
  s.path.forEach((p, k) => {
    const [x, y] = toS(v, p[1], p[2]);
    const on = k === selKf, q = on ? 6 : 4.5;
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(Math.PI / 4);
    ctx.fillStyle = on ? GOLD : "#0c101c";
    ctx.strokeStyle = on ? GOLD : col;
    ctx.lineWidth = 2;
    ctx.fillRect(-q, -q, 2 * q, 2 * q);
    ctx.strokeRect(-q, -q, 2 * q, 2 * q);
    ctx.restore();
    if (on) {
      ctx.fillStyle = GOLD;
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.font = "600 12px " + getComputedStyle(document.body).fontFamily;
      ctx.fillText(p[0].toFixed(1) + " s", x + 12, y - 12);
    }
  });
}


const map = $("#map");
let mdrag = null, mview = null;
const mapPtr = e => { const b = map.getBoundingClientRect(); return [e.clientX - b.left, e.clientY - b.top]; };

map.addEventListener("pointerdown", e => {
  const s = src();
  if (ui.view !== 1 || cur !== "path" || !s || !s.path) return;
  const [sx, sy] = mapPtr(e);
  const v = computeView(map.clientWidth, map.clientHeight);

  const [mx, my] = toS(v, ...posAt(s, editT));
  let hitK = -1;
  if (Math.hypot(mx - sx, my - sy) <= 14) {
    hitK = s.path.findIndex(p => Math.abs(p[0] - editT) < 0.05);   
    if (hitK >= 0) selKf = hitK;
  } else {
    let bd = 12;
    s.path.forEach((p, k) => {
      const [x, y] = toS(v, p[1], p[2]);
      const d = Math.hypot(x - sx, y - sy);
      if (d < bd) { bd = d; hitK = k; }
    });
    if (hitK < 0) return;                            
    selKf = hitK;                                 
    editT = s.path[hitK][0];
  }
  e.stopImmediatePropagation();
  e.preventDefault();
  mdrag = { k: hitK };
  mview = v;
  freezeView(v);                                    
  map.setPointerCapture(e.pointerId);
  renderLanes();
  requestDraw();
}, true);

map.addEventListener("pointermove", e => {
  if (!mdrag) return;
  e.stopImmediatePropagation();
  const s = src();
  if (!s || !s.path) return;
  const [sx, sy] = mapPtr(e);
  const [wx, wy] = toW(mview, sx, sy);
  const x = r1(clamp(wx, -40, 40)), y = r1(clamp(wy, -40, 40));
  if (mdrag.k < 0) { mdrag.k = ensureNode(s, editT, x, y); selKf = mdrag.k; renderLanes(); }
  const p = s.path[mdrag.k];
  p[1] = x;
  p[2] = y;
  markDirty();
  fetchScene();
  requestDraw();
}, true);

const mapEnd = e => {
  if (!mdrag) return;
  e.stopImmediatePropagation();
  mdrag = null;
  freezeView(null);
  renderLanes();
  requestDraw();
};
map.addEventListener("pointerup", mapEnd, true);
map.addEventListener("pointercancel", mapEnd, true);
