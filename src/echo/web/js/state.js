/* state.js: Shared constants, application state, and small helpers.
Imports nothing from the other modules, so it is always evaluated first.
Mutable state lives in the `ui` object (and in S/G0, which are updated in place),
because an importing module can read but not reassign another module's variables */

/* ------------------------------------------------------------------ constants */
export const COLORS = ["#5eead4", "#ff8fab", "#a78bfa", "#7cc4ff", "#fdba74", "#d9f99d", "#f0abfc", "#fde68a"];
export const BASE = { motion: "Static", x: 0, y: 3, radius: 4, speed: 0.08, pass_time: 6, start: 0, gain: 0, send: 0.3, doppler: 1, rolloff: 1, air: 1, shadow: 1 };
export const ROOM0 = { enabled: true, width: 12, depth: 10, absorption: 0.35 };
export const REVERB0 = { enabled: true, kind: "fdn", t60: 2.5, damping: 0.25, size: 1, predelay: 0.02, level_db: -6 };
export const DELAY0 = { enabled: false, time: 0.375, feedback: 0.45, level_db: -8 };
export const MOTIONS = [["Static", "Stay put"], ["Orbit", "Circle around you"], ["Spiral", "Spiral in and out"], ["Oscillate", "Sweep left and right"], ["Flyby", "Fly past once"]];
export const PARAM_KEYS = ["motion", "x", "y", "radius", "speed", "pass_time", "start", "gain", "send", "doppler", "rolloff", "air", "shadow"];
export const HINT_DEFAULT = "Drag a sound on the map to move it. Hover any control to see what it does. Double-click a control's name to reset it.";

/* ------------------------------------------------------------------ state */
export const freshState = () => ({ length: 16, sources: [], room: { ...ROOM0 }, reverb: { ...REVERB0 }, delay: { ...DELAY0 }, automation: {} });
export const snapshot = s => JSON.parse(JSON.stringify(s));

export const S = freshState();   // everything the engine needs
export const G0 = snapshot(S);   // what "Reset sliders" returns to
export const setState = next => Object.assign(S, next);
export const setG0 = next => Object.assign(G0, snapshot(next));
export const stripDef = (k, v) => k === "def" ? undefined : v;
export const payload = () => JSON.stringify(S, stripDef);

export const ui = {
  catalog: { kinds: [], presets: [] },
  sel: 0,                // selected source index
  view: 0,               // 0 = choose sounds, 1 = studio
  paths: {},             // source id -> { x: [], y: [] }
  rendered: null,        // { url, duration }
  previous: null,        // the render before it, for A/B listening
  showingPrev: false,
  dirty: false,
  rendering: false,
  built: false           // has the studio been opened yet?
};

/* ------------------------------------------------------------------ helpers */
export const colorOf = i => COLORS[i % COLORS.length];
export const uid = () => Math.random().toString(36).slice(2, 9);
export const $ = (s, el = document) => el.querySelector(s);

export function h(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v === true) e.setAttribute(k, "");
    else if (v !== false && v != null) e.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) e.append(kid.nodeType ? kid : document.createTextNode(kid));
  return e;
}

export const kindInfo = id => ui.catalog.kinds.find(k => k.id === id) || { label: id, defaults: {} };

export function uniqueName(base) {
  const names = S.sources.map(s => s.name);
  if (!names.includes(base)) return base;
  let n = 2;
  while (names.includes(`${base} ${n}`)) n++;
  return `${base} ${n}`;
}

export function newSource(kind, over = {}, arg = "", name = "") {
  const info = kindInfo(kind);
  const s = { id: uid(), kind, arg, name: name || uniqueName(info.label), ...BASE, ...info.defaults, ...over };
  s.def = Object.fromEntries(PARAM_KEYS.map(k => [k, s[k]]));
  return s;
}