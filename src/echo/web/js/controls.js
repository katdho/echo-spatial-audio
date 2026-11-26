/* controls.js: Status line and buttons, slider/toggle/select builders,
the left panel (per-sound controls), the right panel (room, reverb, echo),
and the scene-length slider */

import { $, h, S, G0, ui, colorOf, MOTIONS, PARAM_KEYS, HINT_DEFAULT } from "./state.js";
import { fetchScene, requestDraw } from "./scene.js";
import { openAdd, removeSource } from "./setup.js";

/* ------------------------------------------------------------------ status + buttons */
export function say(msg, kind = "") { const el = $("#status"); el.className = "status " + kind; el.textContent = msg; }
export function markDirty() { if (ui.rendered) ui.dirty = true; updateStatus(); updateButtons(); }

export function updateStatus() {
  if (ui.rendering) return;
  if (!S.sources.length) say("Add a sound to get started");
  else if (ui.rendered && ui.dirty) { 
    say(""); $("#status").replaceChildren(h("span", { 
        class: "dot" }), "Your scene has changed. Render again to hear the updates"); 
  } else if (!ui.rendered) say("Ready. Press Render and play. It takes a few seconds");
}

export function updateButtons() {
  const b = $("#btn-render");
  b.disabled = ui.rendering || !S.sources.length;
  b.textContent = ui.rendering ? "Rendering…" : ui.rendered ? "Render again" : "Render and play";
  $("#btn-build").disabled = !S.sources.length;
  const cur = ui.view === 0 ? 0 : ui.rendered ? 2 : 1;
  document.querySelectorAll("#steps button").forEach((btn, i) => {
    if (i === cur) btn.setAttribute("aria-current", "step"); else btn.removeAttribute("aria-current");
    btn.classList.toggle("done", i < cur);
    btn.disabled = i > 0 && !S.sources.length;
  });
}

export const showHint = t => $("#hint").textContent = t || HINT_DEFAULT;
export const num = (d, u = "") => v => v.toFixed(d) + u;
export const db = v => (v > 0 ? "+" : "") + v.toFixed(1) + " dB";
export const pct = v => Math.round(v * 100) + "%";
const metres = v => (v > 0 ? "+" : "") + v.toFixed(1) + " m";

/* ------------------------------------------------------------------ control builders */
function hoverHint(el, hint) { 
    el.addEventListener("mouseenter", () => showHint(hint));
     el.addEventListener("mouseleave", () => showHint()); 
}

export function slider({ label, min, max, step, get, set, def, fmt, hint, key, idle }) {
  const input = h("input", { type: "range", min, max, step, "aria-label": label, "data-key": key || "" });
  const val = h("span", { class: "val" });
  const name = h("span", { text: label, title: "Double-click to reset" });
  const row = h("div", { class: "row" }, h("div", { class: "row-top" }, name, val), input);
  const paint = () => { 
    val.textContent = fmt(+input.value); 
    input.style.setProperty("--pct", ((input.value - min) / (max - min) * 100) + "%"); };
  const refresh = () => { input.value = get(); paint(); };
  input.addEventListener("input", () => { set(+input.value); paint(); onChange(); });
  name.addEventListener("dblclick", () => { set(def()); refresh(); onChange(); });
  hoverHint(row, hint);
  input.addEventListener("focus", () => showHint(hint));
  input.addEventListener("blur", () => showHint());
  const why = idle ? idle() : null;
  if (why) { row.classList.add("idle"); row.title = "No effect right now: " + why; }
  row.refresh = refresh;
  row.input = input;
  refresh();
  return row;
}

export function toggle(label, get, set, hint) {
  const input = h("input", { type: "checkbox", "aria-label": label });
  input.checked = get();
  const w = h("label", { class: "switch" }, input, h("span"));
  input.addEventListener("change", () => { set(input.checked); onChange(true); });
  hoverHint(w, hint);
  return w;
}

export function select(label, opts, get, set, hint) {
  const sel_ = h("select", { "aria-label": label }, opts.map(([v, t]) => h("option", { value: v, text: t })));
  sel_.value = get();
  sel_.addEventListener("change", () => { set(sel_.value); onChange(true); });
  const f = h("label", { class: "field" }, h("span", { text: label }), sel_);
  hoverHint(f, hint);
  return f;
}

export function group(title, children, onReset, enabled) {
  const head = h("div", { class: "group-head" }, h("h3", { text: title }));
  const right = h("div", { style: "display:flex;gap:8px;align-items:center" });
  if (enabled) right.append(enabled);
  right.append(h("button", { class: "link", text: "Reset", title: "Put these controls back to where they started", 
    onclick: () => { onReset(); onChange(true); } }));
  head.append(right);
  return h("div", { class: "group" }, head, children);
}

export function onChange(rebuild = false) {
  if (rebuild) { renderLeft(); renderRight(); }
  markDirty(); fetchScene(); requestDraw();
}

/* ------------------------------------------------------------------ source controls (left panel) */
const motionLabel = m => (MOTIONS.find(x => x[0] === m) || [0, m])[1].split(" ")[0];

export function renderLeft() {
  const rail = $("#rail-left");
  rail.replaceChildren();
  rail.style.setProperty("--c", colorOf(ui.sel));
  const list = h("ul", { class: "src-list" });
  S.sources.forEach((s, i) => {
    list.append(h("li", { class: "src-item" + (i === ui.sel ? " sel" : ""), style: `--c:${colorOf(i)}` },
      h("button", { class: 
        "src-pick", onclick: () => { ui.sel = i; renderLeft(); requestDraw(); }, 
        "aria-pressed": i === ui.sel }, 
      h("i"), 
      h("b", { text: s.name }), 
      h("small", { text: s.path ? "Keyframes" : motionLabel(s.motion) })),
      h("button", { class: 
        "src-rm", 
        "aria-label": `Remove ${s.name}`, title: "Remove this sound", text: "✕", onclick: () => removeSource(i) })));
  });
  rail.append(
    h("div", { class: "rail-head" }, 
    h("h2", { text: "Sounds" }), 
    h("button", { class: "btn", text: "Add sound", onclick: () => openAdd() })));
  if (!S.sources.length) return rail.append(h("p", { 
    class: "empty-note", text: "No sounds yet. Add one to place it on the map." }));
  rail.append(list);
  const s = S.sources[ui.sel];
  if (!s) return;
  const mk = o => slider({ ...o, get: () => s[o.key], set: v => s[o.key] = v, def: () => s.def[o.key] });
  // Controls whose value is replaced by keyframes in this scene are dimmed, like other no-effect controls.
  const dim = (rows, why, overridden) => rows.forEach(r => {
    const k = r.input && r.input.dataset.key;
    if (k && overridden(k)) { r.classList.add("idle"); r.title = "No effect right now: " + why; }
  });
  const auto = k => !!(s.automation && s.automation[k]);
  const sp = s.motion === "Oscillate" ? "swings/min" : "laps/min";
  const radiusLabel = { 
    Orbit: "Orbit Radius", 
    Spiral: "Spiral Radius", 
    Oscillate: "Sweep Range", 
    Flyby: "Pass Distance/Offset" }[s.motion];

  const moveRows = [select("Movement Pattern", MOTIONS, () => s.motion, v => { s.motion = v; delete s.path; }, 
    "Choose how the sound moves around the listener. If this sound follows keyframes, picking a pattern replaces them")];
  moveRows.push(mk({ key: "x", label: "X-Position (Left/Right)", min: -15, max: 15, step: 0.1, fmt: metres, 
    hint: "Set the sound's horizontal position relative to the listener: Left(-); Right(+). For moving sounds, this sets the center of its movement path." }));
  moveRows.push(mk({ key: "y", label: "Y-Position (Back/Front)", min: -15, max: 15, step: 0.1, fmt: metres, 
    hint: "Set the sound's position behind or in front of the listener: Back(-); Front(+)" }));
  if (s.motion !== "Static") moveRows.push(mk({ 
    key: "radius", label: radiusLabel, min: 0.5, max: 40, step: 0.5, 
    fmt: num(1, " m"), hint: "How big the movement is" }));
  if (["Orbit", "Spiral", "Oscillate"].includes(s.motion)) moveRows.push(mk({ 
    key: "speed", label: "Movement Rate (Speed)", min: -0.5, max: 0.5, step: 0.005, 
    fmt: v => Math.abs(v) < 0.0025 ? "still" : (v > 0 ? "↺ " : "↻ ") + Math.abs(v * 60).toFixed(1) + " " + sp, 
    hint: "Set how quickly the sound moves. The arrow shows the direction seen on the map. Negative reverses its direction" }));
  if (s.motion === "Flyby") moveRows.push(
    mk({ key: "pass_time", label: "Pass Duration", min: 1, max: 30, step: 0.5, fmt: num(1, " s"), 
        hint: "How long the pass takes. A shorter pass is faster, so the pitch bend is stronger." 
    }));
  moveRows.push(mk({ key: "start", label: "Start Time", min: 0, max: S.length, step: 0.5, fmt: num(1, " s"), 
    hint: "When this sound starts, in seconds from the beginning." }));
  dim(moveRows, "this sound follows keyframes. Choose a Movement Pattern to replace them.", k => s.path && k !== "start");
  rail.append(group("Movement", moveRows, () => PARAM_KEYS.slice(0, 7).forEach(k => s[k] = s.def[k])));

  const levelRows = [
    mk({ key: "gain", label: "Volume", min: -30, max: 6, step: 0.5, fmt: db, 
        hint: "How loud this sound is before it travels around" }),
    mk({ key: "send", label: "Reverb amount", min: 0, max: 1, step: 0.01, fmt: pct, 
        hint: "How much goes into the reverb. More makes it sound farther away and washier.", 
        idle: () => S.reverb.enabled ? null : "the reverb is switched off (right side)." })
  ];
  dim(levelRows, "this is automated with keyframes in this scene.", auto);
  rail.append(group("Level", levelRows, () => ["gain", "send"].forEach(k => s[k] = s.def[k])));

  const spatialRows = [
    mk({ key: "doppler", label: "Doppler Effect", min: 0, max: 3, step: 0.05, 
        fmt: v => v === 0 ? "off" : v.toFixed(2) + "x", 
        hint: "Controls how much the pitch changes as the sound moves toward or away from the listener. \
               0 disables the effect; 1 approximates the natural Doppler shift; higher values exaggerate it", 
        idle: () => s.motion === "Static" && !s.path ? "this sound isn't moving, so there is no pitch bend." : null }),
    mk({ key: "rolloff", label: "Distance Attenuation", min: 0, max: 2, step: 0.05, fmt: num(2), 
        hint: "Controls how quickly the sound gets quieter as it moves farther away. \
               0 keeps its volume constant regardless of distance" }),
    mk({ key: "air", label: "Air Absorption", min: 0, max: 4, step: 0.05, fmt: num(2), 
        hint: "Controls how much high-frequency content is lost over distance. Higher values make distant sounds sound duller" }),
    mk({ key: "shadow", label: "Head Shadow", min: 0, max: 1, step: 0.01, fmt: pct, 
        hint: "How much your head muffles the ear facing away from the sound." })
  ];
  dim(spatialRows, "this is automated with keyframes in this scene.", auto);
  rail.append(group("Spatialization", spatialRows, () => ["doppler", "rolloff", "air", "shadow"].forEach(k => s[k] = s.def[k])));
}

/* ------------------------------------------------------------------ room and effects (right panel) */
export function renderRight() {
  const rail = $("#rail-right");
  rail.replaceChildren();
  const R = S.room, V = S.reverb, D = S.delay, g = G0;
  const mkG = (obj, gobj, o) => slider({ ...o, get: () => obj[o.key], set: v => obj[o.key] = v, 
    def: () => gobj[o.key] });
  const grp = (title, obj, gobj, rows, keys, hint) => {
    const gp = group(title, rows, () => keys.forEach(k => obj[k] = gobj[k]), 
    toggle(`${title} on or off`, () => obj.enabled, v => { obj.enabled = v; gp.classList.toggle("off", !v); }, hint));
    gp.classList.toggle("off", !obj.enabled);
    return gp;
  };

  rail.append(grp("Room", R, g.room, [
    mkG(R, g.room, { key: "width", label: "Width", min: 4, max: 60, step: 0.5, fmt: num(1, " m"), 
        hint: "Wider rooms push the echoes off the side walls later." }),
    mkG(R, g.room, { key: "depth", label: "Depth", min: 4, max: 60, step: 0.5, fmt: num(1, " m"), 
        hint: "Deeper rooms push the front and back echoes later." }),
    mkG(R, g.room, { key: "absorption", label: "Wall softness", min: 0, max: 1, step: 0.01, fmt: pct, 
        hint: "0% is bare, bright walls with strong echoes. 100% soaks everything up." })
  ], ["enabled", "width", "depth", "absorption"], "Turns the wall echoes on or off."));

  rail.append(grp("Reverb", V, g.reverb, [
    select("Type", [["fdn", "Smooth (feedback network)"], ["schroeder", "Classic (Schroeder)"]], 
        () => V.kind, v => V.kind = v, "The reverb algorithm. Smooth is denser; Classic is the one from the course notes"),
    mkG(V, g.reverb, { key: "t60", label: "Decay time", min: 0.3, max: 10, step: 0.1, fmt: num(1, " s"), 
        hint: "How long the tail takes to fade away (T60)." }),
    mkG(V, g.reverb, { key: "damping", label: "Darkness", min: 0, max: 0.5, step: 0.01, fmt: num(2), 
        hint: "Higher makes the tail duller as it fades." }),
    mkG(V, g.reverb, { key: "size", label: "Space size", min: 0.5, max: 2.5, step: 0.05, fmt: num(2, "x"), 
        hint: "Stretches the internal delay lengths. Larger sounds like a bigger space." }),
    mkG(V, g.reverb, { key: "predelay", label: "Pre-delay", min: 0, max: 0.2, step: 0.005, 
        fmt: v => Math.round(v * 1000) + " ms", hint: "Silent gap before the reverb starts." }),
    mkG(V, g.reverb, { key: "level_db", label: "Level", min: -30, max: 6, step: 0.5, fmt: db, 
        hint: "How loud the reverb is in the mix." })
  ], ["enabled", "kind", "t60", "damping", "size", "predelay", "level_db"], "Turns the reverb on or off."));

  rail.append(grp("Ping-pong echo", D, g.delay, [
    mkG(D, g.delay, { key: "time", label: "Time between echoes", min: 0.05, max: 1.5, step: 0.005, 
        fmt: v => Math.round(v * 1000) + " ms", hint: "Gap between repeats. Each repeat bounces to the other ear." }),
    mkG(D, g.delay, { key: "feedback", label: "Repeats", min: 0, max: 0.95, step: 0.01, fmt: pct, 
        hint: "How many times it repeats. Higher lasts longer." }),
    mkG(D, g.delay, { key: "level_db", label: "Level", min: -30, max: 6, step: 0.5, fmt: db, 
        hint: "How loud the echoes are." })
  ], ["enabled", "time", "feedback", "level_db"], "Turns the echo on or off"));
}

/* ------------------------------------------------------------------ duration */
export function syncLength() {
  for (const id of ["len-setup", "len-studio"]) {
    const el = $("#" + id);
    el.value = S.length;
    el.style.setProperty("--pct", ((S.length - 3) / 87 * 100) + "%");
    $("#" + id + "-out").textContent = S.length + " s";
  }
  document.querySelectorAll('#rail-left input[data-key="start"]').forEach(inp => {
    inp.max = S.length;
    if (+inp.value > S.length) { inp.value = S.length; inp.dispatchEvent(new Event("input")); }
  });
}

for (const id of ["len-setup", "len-studio"]) $("#" + id).addEventListener("input", e => { 
    S.length = +e.target.value; 
    syncLength(); markDirty(); fetchScene(); requestDraw(); 
});