/* app.js: Entry point for the ECHO web interface.
Wires the step bar, Build scene, Reset and Start over buttons, then loads the catalog.

Communicates with the Python backend through the /api endpoints.
HTML structure is defined in index.html. Styling is defined in style.css.

Module map:
  state.js     constants, shared state, helpers
  controls.js  status line, buttons, sliders, left/right panels, scene length
  scene.js     /api/scene, room map drawing and dragging
  audio.js     rendering, playback, A/B, keyboard shortcuts
  setup.js     add/remove sounds, setup screen, demos, dialog, uploads, navigation */

import { $, S, G0, ui, PARAM_KEYS, freshState, setState, setG0 } from "./state.js";
import { say, markDirty, syncLength, renderLeft, renderRight, updateButtons } from "./controls.js";
import { fetchScene, requestDraw } from "./scene.js";
import { doRender, togglePlay, resetAudio, updatePlayer } from "./audio.js";
import { go, renderSetup, renderPresetCards } from "./setup.js";

/* ------------------------------------------------------------------ navigation buttons */
document.querySelectorAll("#steps button").forEach(b => b.addEventListener("click", () => {
  const i = +b.dataset.step;
  if (i < 2) go(i);
  else { go(1); ui.rendered ? togglePlay() : doRender(); }
}));

$("#btn-build").addEventListener("click", () => {
  if (!ui.built) setG0({ ...S, sources: [] });
  ui.built = true;
  go(1);
});

/* ------------------------------------------------------------------ reset */
$("#btn-reset").addEventListener("click", () => {
  if (ui.view === 0) return;
  S.length = G0.length;
  S.room = { ...G0.room };
  S.reverb = { ...G0.reverb };
  S.delay = { ...G0.delay };
  S.sources.forEach(s => PARAM_KEYS.forEach(k => s[k] = s.def[k]));
  syncLength();
  renderLeft();
  renderRight();
  markDirty();
  fetchScene();
  requestDraw();
  say("Sliders reset. Your sounds are unchanged.");
});

let armTimer = null;

function disarm(b) {
  clearTimeout(armTimer);
  b.classList.remove("armed");
  b.textContent = "Start over";
}

$("#btn-start-over").addEventListener("click", e => {
  const b = e.currentTarget;
  if (!b.classList.contains("armed")) {
    b.classList.add("armed");
    b.textContent = "Click again to clear everything";
    armTimer = setTimeout(() => disarm(b), 3500);
    return;
  }
  disarm(b);
  resetAudio();
  setState(freshState());
  setG0(S);
  ui.built = false;
  ui.paths = {};
  ui.sel = 0;
  syncLength();
  go(0);
  say("");
});

/* ------------------------------------------------------------------ initialize */
(async function () {
  try {
    ui.catalog = await (await fetch("/api/catalog")).json();
  } catch (e) {
    document.body.innerHTML = '<p style="padding:40px">Can\'t reach ECHO. Start it with <code>python app.py</code>.</p>';
    return;
  }
  syncLength();
  renderSetup();
  renderPresetCards();
  updateButtons();
  updatePlayer();
})();