/* setup.js: Adding and removing sounds, the setup screen (sound cards, demos),
navigation between setup and studio, the "Add sound" dialog, and file uploads */

import { $, h, S, ui, colorOf, ROOM0, REVERB0, DELAY0, setState, setG0, newSource, uniqueName, stripDef } from "./state.js";
import { say, markDirty, updateStatus, updateButtons, renderLeft, renderRight, showHint, syncLength } from "./controls.js";
import { fetchScene, requestDraw, draw } from "./scene.js";
import { updatePlayer, resetAudio } from "./audio.js";

/* ------------------------------------------------------------------ sources */
export function addSource(kind, over = {}, arg = "", name = "") {
  if (S.sources.length >= 12) return say("That's the maximum of 12 sounds. Remove one to add another", "err");
  S.sources.push(newSource(kind, over, arg, name));
  ui.sel = S.sources.length - 1;
  markDirty();
  renderSetupBar();
  fetchScene();
}

export function removeSource(i) {
  S.sources.splice(i, 1);
  ui.sel = Math.max(0, Math.min(ui.sel, S.sources.length - 1));
  markDirty();
  renderSetupBar();
  renderLeft();
  fetchScene();
}

/* ------------------------------------------------------------------ navigation */
export function go(v) {
  ui.view = v;
  $("#setup").hidden = v !== 0;
  $("#studio").hidden = v !== 1;
  if (v === 1) {
    if (ui.sel >= S.sources.length) ui.sel = 0;
    renderLeft();
    renderRight();
    showHint();
    requestAnimationFrame(draw);
    fetchScene();
    updateStatus();
  } else renderSetup();
  updateButtons();
  updatePlayer();
}

/* ------------------------------------------------------------------ setup screen */
export function renderSetup() {
  const kg = $("#kind-grid");
  kg.replaceChildren();
  for (const k of ui.catalog.kinds.filter(k => !k.hidden)) {
    const n = S.sources.filter(s => s.kind === k.id).length;
    kg.append(h("button", { class: "card", onclick: () => { addSource(k.id); renderSetup(); } }, n ? h("i", { class: "count", text: String(n) }) : null, h("b", { text: k.label }), h("span", { text: k.blurb })));
  }
  renderSetupBar();
}

export function renderSetupBar() {
  const c = $("#chips");
  c.replaceChildren();
  if (!S.sources.length) c.append(h("span", { class: "empty", text: "No sounds yet. Click one above or open a demo." }));
  S.sources.forEach((s, i) => c.append(h("span", { class: "chip", style: `--c:${colorOf(i)}` }, h("i"), s.name, h("button", { "aria-label": `Remove ${s.name}`, text: "✕", onclick: () => { removeSource(i); renderSetup(); } }))));
  $("#btn-build").disabled = !S.sources.length;
  $("#btn-build").textContent = ui.built ? "Back to scene" : "Build scene";
  updateButtons();
}

/* ------------------------------------------------------------------ demos */
export function loadPreset(p) {
  resetAudio();
  setState({ length: p.length, sources: [], room: { ...ROOM0, ...p.room }, reverb: { ...REVERB0, ...p.reverb }, delay: { ...DELAY0, ...p.delay },
    automation: JSON.parse(JSON.stringify(p.automation || {})) });
  for (const d of p.sources) { const { kind, name, ...over } = JSON.parse(JSON.stringify(d)); S.sources.push(newSource(kind, over, "", name)); }
  setG0(S);
  ui.built = true;
  ui.sel = 0;
  ui.paths = {};
  syncLength();
  go(1);
  say(`Loaded "${p.label}". Press Render and play, or drag sounds on the map first.`);
}

function presetState(p) {
  const st = { length: p.length, sources: [], room: { ...ROOM0, ...p.room } };
  for (const d of p.sources) { const { kind, name, ...over } = d; st.sources.push(newSource(kind, over, "", name)); }
  return st;
}

export function renderPresetCards() {
  const grid = $("#preset-grid");
  grid.replaceChildren();
  for (const p of ui.catalog.presets) {
    const cv = h("canvas", { width: 460, height: 200, "aria-hidden": "true" });
    grid.append(h("button", { class: "card", onclick: () => loadPreset(p) }, cv, h("b", { text: p.label }), h("span", { text: p.blurb })));
    const st = presetState(p);
    fetch("/api/scene", { method: "POST", body: JSON.stringify(st, stripDef) }).then(r => r.json()).then(j => drawMini(cv, st, j.paths)).catch(() => {});
  }
}

function drawMini(cv, st, ps) {
  const c = cv.getContext("2d");
  const w = cv.width, hh = cv.height;
  let rx = 6, ry = 6;
  if (st.room.enabled) { rx = Math.max(rx, st.room.width / 2); ry = Math.max(ry, st.room.depth / 2); }
  for (const s of st.sources) {
    const p = ps[s.id];
    if (!p) continue;
    for (let i = 0; i < p.x.length; i += 5) { rx = Math.max(rx, Math.abs(p.x[i])); ry = Math.max(ry, Math.abs(p.y[i])); }
  }
  rx *= 1.1;
  ry *= 1.1;
  const sc = Math.min(w / 2 / rx, hh / 2 / ry);
  const cx = w / 2, cy = hh / 2;
  c.clearRect(0, 0, w, hh);
  if (st.room.enabled) {
    c.strokeStyle = "rgba(255,207,107,.6)";
    c.lineWidth = 2;
    c.strokeRect(cx - st.room.width / 2 * sc, cy - st.room.depth / 2 * sc, st.room.width * sc, st.room.depth * sc);
  }
  st.sources.forEach((s, i) => {
    const p = ps[s.id];
    if (!p) return;
    c.strokeStyle = colorOf(i);
    c.lineWidth = 3;
    c.globalAlpha = 0.85;
    c.beginPath();
    for (let k = 0; k < p.x.length; k++) { const X = cx + p.x[k] * sc, Y = cy - p.y[k] * sc; k ? c.lineTo(X, Y) : c.moveTo(X, Y); }
    c.stroke();
    c.globalAlpha = 1;
    c.fillStyle = colorOf(i);
    c.beginPath();
    c.arc(cx + p.x[0] * sc, cy - p.y[0] * sc, 6, 0, 7);
    c.fill();
  });
  c.fillStyle = "#edf0f7";
  c.beginPath();
  c.arc(cx, cy, 6, 0, 7);
  c.fill();
}

/* ------------------------------------------------------------------ add-sound dialog */
const dlg = $("#add-dialog");

export function openAdd() {
  const g = $("#dlg-grid");
  g.replaceChildren();
  for (const k of ui.catalog.kinds.filter(k => !k.hidden)) {
    g.append(h("button", { class: "card", onclick: () => { addSource(k.id); renderLeft(); requestDraw(); say(`Added ${S.sources[ui.sel].name}.`); dlg.close(); } }, h("b", { text: k.label }), h("span", { text: k.blurb })));
  }
  dlg.showModal();
}

$("#dlg-close").addEventListener("click", () => dlg.close());

/* ------------------------------------------------------------------ file uploads and Freesound */
async function uploadFile(f) {
  if (!f) return;
  say(`Loading ${f.name}…`);
  try {
    const r = await fetch("/api/upload?name=" + encodeURIComponent(f.name), { method: "POST", body: f });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error);
    addSource("file", {}, j.id, uniqueName(j.name.replace(/\.[^.]+$/, "")));
    say(`Added ${S.sources[ui.sel].name} (${j.seconds} s).`, "ok");
    ui.view === 0 ? renderSetup() : renderLeft();
  } catch (err) {
    say(err.message, "err");
    alert(err.message);
  }
}

$("#btn-file").addEventListener("click", () => $("#file-input").click());
$("#dlg-file").addEventListener("click", () => { dlg.close(); $("#file-input").click(); });
$("#file-input").addEventListener("change", e => { uploadFile(e.target.files[0]); e.target.value = ""; });

$("#btn-fs").addEventListener("click", async () => {
  const id = $("#fs-id").value.trim();
  if (!/^\d+$/.test(id)) return alert("Enter the number from the Freesound page address.");
  try {
    const r = await fetch("/api/probe", { method: "POST", body: JSON.stringify({ kind: "freesound", arg: id }) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error);
    addSource("freesound", {}, id, uniqueName("Freesound " + id));
    renderSetup();
    $("#fs-id").value = "";
  } catch (err) {
    alert("Couldn't fetch that sound: " + err.message);
  }
});