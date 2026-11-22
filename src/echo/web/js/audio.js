/* audio.js: Rendering through /api/render, the audio element, the player bar,
A/B comparison with the previous render, and keyboard shortcuts */

import { $, S, ui, payload } from "./state.js";
import { say, updateButtons } from "./controls.js";
import { requestDraw } from "./scene.js";

/* ------------------------------------------------------------------ audio element */
export const audio = new Audio();

audio.addEventListener("timeupdate", () => { updatePlayer(); requestDraw(); });
audio.addEventListener("ended", () => { audio.currentTime = 0; updatePlayer(); requestDraw(); });
audio.addEventListener("play", () => { loop(); updatePlayer(); });
audio.addEventListener("pause", () => { updatePlayer(); requestDraw(); });

function loop() {
  requestDraw();
  if (!audio.paused) requestAnimationFrame(loop);
}

export const togglePlay = () => audio.paused ? audio.play() : audio.pause();

// Stop playback and forget both renders (used by Start over and when loading a demo).
export function resetAudio() {
  audio.pause();
  if (ui.rendered) URL.revokeObjectURL(ui.rendered.url);
  ui.rendered = null;
  if (ui.previous) URL.revokeObjectURL(ui.previous.url);
  ui.previous = null;
  ui.showingPrev = false;
  ui.dirty = false;
  audio.removeAttribute("src");
}

/* ------------------------------------------------------------------ player bar */
const fmtT = s => { s = Math.max(0, s); return Math.floor(s / 60) + ":" + String(Math.floor(s % 60)).padStart(2, "0"); };

export function updatePlayer() {
  const ok = !!ui.rendered;
  const dur = ok ? (audio.duration || ui.rendered.duration) : 0;
  $("#btn-play").disabled = !ok;
  $("#scrub").disabled = !ok;
  $("#time").textContent = ok ? `${fmtT(audio.currentTime)} / ${fmtT(dur)}` : "Render to listen";
  const sc = $("#scrub");
  if (ok) {
    sc.max = dur;
    if (document.activeElement !== sc) sc.value = audio.currentTime;
    sc.style.setProperty("--pct", (audio.currentTime / dur * 100) + "%");
  }
  $("#ico-play").innerHTML = audio.paused ? '<path d="M3 1.5v11l9-5.5z" fill="currentColor"/>' : '<path d="M2.5 1.5h3v11h-3zM8.5 1.5h3v11h-3z" fill="currentColor"/>';
  $("#btn-play").setAttribute("aria-label", audio.paused ? "Play" : "Pause");
  $("#btn-export").hidden = !ok;
  $("#btn-ab").hidden = !(ok && ui.previous);
  $("#btn-ab").textContent = ui.showingPrev ? "Hear latest" : "Hear previous";
}

/* ------------------------------------------------------------------ render */
export async function doRender() {
  if (ui.rendering || !S.sources.length) return;
  ui.rendering = true;
  updateButtons();
  audio.pause();
  const t0 = performance.now();
  const timer = setInterval(() => say(`Rendering… ${((performance.now() - t0) / 1000).toFixed(0)} s. Longer scenes and bigger reverbs take longer.`), 500);
  say("Rendering…");
  try {
    const r = await fetch("/api/render", { method: "POST", body: payload() });
    if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.error || `Server error ${r.status}`); }
    const blob = await r.blob();
    if (ui.previous) URL.revokeObjectURL(ui.previous.url);
    ui.previous = ui.rendered;
    ui.showingPrev = false;
    ui.rendered = { url: URL.createObjectURL(blob), duration: parseFloat(r.headers.get("X-Duration")) || 0 };
    audio.src = ui.rendered.url;
    audio.load();
    $("#btn-export").href = ui.rendered.url;
    ui.dirty = false;
    clearInterval(timer);
    const ch = parseFloat(r.headers.get("X-Change"));
    let msg = `Rendered ${ui.rendered.duration.toFixed(1)} s, including the reverb and echo tail. Playing now. Headphones on.`;
    if (!isNaN(ch)) msg += ch < 0.005 ? " The audio is identical to your last render. Either nothing changed, or the control you moved has no effect in this scene." : ` Difference from your last render: ${Math.round(ch * 100)}%. Use Hear previous to compare.`;
    say(msg, !isNaN(ch) && ch < 0.005 ? "err" : "ok");
    audio.currentTime = 0;
    updatePlayer();
    audio.play().catch(() => say("Rendered. Press the play button to listen.", "ok"));
  } catch (err) {
    clearInterval(timer);
    say(err.message === "Failed to fetch" ? "Lost contact with ECHO. Check that python app.py is still running." : err.message, "err");
  } finally {
    clearInterval(timer);
    ui.rendering = false;
    updateButtons();
    updatePlayer();
  }
}

/* ------------------------------------------------------------------ player controls */
$("#btn-render").addEventListener("click", doRender);
$("#btn-play").addEventListener("click", togglePlay);
$("#scrub").addEventListener("input", e => audio.currentTime = +e.target.value);

$("#btn-ab").addEventListener("click", () => {
  const t = audio.currentTime;
  const wasPlaying = !audio.paused;
  const target = ui.showingPrev ? ui.rendered : ui.previous;
  ui.showingPrev = !ui.showingPrev;
  audio.src = target.url;
  audio.load();
  audio.addEventListener("loadedmetadata", () => {
    audio.currentTime = Math.min(t, audio.duration || t);
    if (wasPlaying) audio.play().catch(() => {});
    updatePlayer();
  }, { once: true });
  say(ui.showingPrev ? "Playing the previous render." : "Playing the latest render.");
});

document.addEventListener("keydown", e => {
  if (ui.view !== 1 || e.target.closest("select,input[type=text],dialog")) return;
  if (e.key === " " && !e.target.closest("button")) { e.preventDefault(); ui.rendered ? togglePlay() : doRender(); }
  if ((e.key === "r" || e.key === "R") && !e.metaKey && !e.ctrlKey) doRender();
});