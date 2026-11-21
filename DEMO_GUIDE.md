# ECHO demo guide

Everything you need to run ECHO, use the control panel, and record the demo video.

## 1. Before you start (2 minutes)

1. **Headphones on.** ECHO's 3-D effect is binaural. On speakers the movement collapses to left/right.
2. Open a terminal in the `src/` folder.
3. Install once: `pip install pyquist`
4. Check everything works: `python tests.py` should end with `all 11 tests passed`.
5. Optional but recommended: `python demo.py` writes the four WAV files to `renders/`. Keep them as a backup in case a live render ever misbehaves during recording.

## 2. What to run

| Command (from `src/`) | What it does |
| --- | --- |
| `python app.py` | Starts the control panel and opens it in your browser at http://127.0.0.1:8765. Stop with Ctrl+C. |
| `python app.py --port 9000` | Same, on another port (use if 8765 is busy). |
| `python tests.py` | 11 checks of the DSP and the panel's backend. |
| `python demo.py` | Renders the 3 demos and the composition sketch to `renders/*.wav`. |
| `python demo.py --files a.wav` | Same, with your own recording as the source in demos 3 and 4. |
| `jupyter lab echo_notebook.ipynb` | Optional: the same panel inside a notebook, plus short code examples. |

For the video, you only need `python app.py` plus an editor open on `src/echo/spatial.py` and `src/echo/dsp.py`.

## 3. Using the control panel

The panel has three steps, shown at the top.

**Step 1: Choose sounds.** Either click a demo scene (it opens straight in the studio), or click sounds under "Or build your own" (click twice for two copies). You can also upload a recording or add a Freesound ID. Your picks collect in the bar at the bottom. Set the render **Length**, then press **Build scene**.

**Step 2: Shape the scene.** The map is in the middle. You are the head in the centre, facing up. Colored dots are the sounds; dashed lines are the paths they will travel.
- **Drag a dot** to move a sound. For moving sounds, the small crosshair ring is the centre of the path.
- **Left side:** pick a sound in the list, then change how it moves (Path, position, size, speed), how loud it is, and how realistic the physics are.
- **Right side:** the room (walls), the reverb, and the ping-pong echo. Each has an on/off switch.
- **Hover** any control to read what it does in the hint line under the map.
- **Reset:** double-click a control's name to reset that one control, click **Reset** on a section, **Reset sliders** (top right) to restore everything but keep your sounds, or **Start over** (click twice) to clear it all.

**Step 3: Listen.** Press **Render and play** (or Space). A few seconds later it plays, and the dots travel along their paths in time with the audio. Drag the playback bar to jump around. If you change anything afterwards, the status line tells you to **Render again**. **Export WAV** saves the result.

Shortcuts: **Space** plays/pauses (or renders the first time), **R** renders.

## 4. Demo script (about 4 minutes)

Speak in your own words; this is a guide to hit every point. Lines in *italics* are actions. Adjust to your video's required length.

### 0:00 Introduction (20 s)

*Start on the Step 1 screen.*

> "This is ECHO, a spatial-audio instrument. You place sounds in a virtual room, move them around the listener, and it renders a stereo mix for headphones. Everything you'll hear is built from delay lines, the technique from chapters 12 and 13: no library reverb, panner or effect. Please listen on headphones."

### 0:20 Demo 1: Doppler fly-by (60 s)

*Click **Doppler fly-by**. Point at the line across the map.*

> "A ticking sound flies past me at about 11 metres per second, 3 metres in front of me. A bass string sits still on my left as a reference. The room and reverb are off, so you only hear the basic cues."

*Press **Render and play**. Let it play.*

> "Hear it pan from left to right: that's the interaural time difference, each ear reads the sound at a slightly different delay. It gets louder as it passes, then quieter. And the pitch drops as it leaves: that's the Doppler shift."

*On the left, move **Pitch bend (Doppler)** to 0, press **Render again**.*

> "With Doppler at zero, the panning and loudness are the same, but the pitch bend is gone. So Doppler is its own cue."

*Switch to your editor, open `spatial.py`, scroll to `propagate`.*

> "Here's how: each ear reads the source through a time-varying fractional delay, `fractional_delay` in `dsp.py`. The delay is the distance to that ear divided by the speed of sound. The difference between the ears is the time difference. When the delay changes over time, the read head moves faster or slower than real time, and that's the Doppler shift."

### 1:20 Demo 2: Orbiting strings (60 s)

*Back in the browser, click **Start over** twice, then **Orbiting strings**.*

> "Now a plucked-string arpeggio circles my head in a 14 by 11 metre room, over a low drone."

*Press **Render and play**. While it plays, drag the drone to the right side of the map.*

> "I can drag the drone anywhere. The strings are my own Karplus-Strong model: a burst of noise through a damped feedback delay line."

*Press **Render again**. Then on the right: lower **Wall softness**, raise **Decay time** to about 6 s, turn **Ping-pong echo** off, render again.*

> "Harder walls give brighter early reflections. A longer decay makes a bigger space. And the ping-pong echo bounces each repeat between my ears. Switching it off makes the scene much drier."

*Open `dsp.py` at `feedback_delay` and `fdn_reverb`.*

> "The reverb is a feedback delay network: eight delay lines mixed by a Hadamard matrix, each with a gain set so the tail decays by 60 dB at exactly the decay time I choose. The notes write feedback loops one sample at a time. I noticed the output only depends on samples at least M back, so `feedback_delay` handles M samples at a time with vector operations. It gives identical output, and `tests.py` checks that against the notes' circular-buffer loop."

### 2:20 Demo 3: Distant cathedral (30 s)

*Click **Start over** twice, then **Distant cathedral**. Render and play.*

> "Same engine, different settings: a 40 by 30 metre room, a 7-second dark reverb with a pre-delay, and bells drifting in a slow spiral. Large reverb amount and a dull, far-away filter make it sound distant."

### 2:50 Composition sketch (45 s)

*Click **Start over** twice, then **Composition sketch**. Point at the five dots on the map.*

> "This is the plan for my final composition. A distant drone enters first. An arpeggio circles one way, a counter-melody enters at 12 seconds and circles the other way. Ticks sweep left to right, then a single fly-by with Doppler marks the climax, and everything dissolves into the reverb tail."

*Press **Render and play** and let it run.*

> "In the final piece I'll use ECHO as the spatial mixing stage: my own recordings and the string instrument go in dry, and come out as a moving, reverberant stereo scene."

### 3:35 Wrap-up (25 s)

*Switch to a terminal. Run `python tests.py`.*

> "Last, the tests. They check that the fast delay lines match the notes' versions exactly, that the interaural delay matches head width, that a fly-by really shifts pitch up then down, and that the reverb's measured decay time matches the setting. Eleven out of eleven pass. Thanks for listening."

### Recording tips

- Record your screen and the audio output together. Check that the recording captures the sound before you do the real take.
- Render each scene once before recording so you know how long it takes; fill the wait with the next sentence.
- If a live render ever fails, play the matching file from `renders/` instead.
- Close extra browser tabs so notifications don't interrupt.

## 5. What each file does

```
echo_submission/
├── TECHNICAL.md              Project summary, requirements, parameters, citations, AI workflow (the write-up).
├── DEMO_GUIDE.md             This file.
└── src/
    ├── app.py                START HERE. Launches the control panel in your browser.
    ├── demo.py               Renders the 3 demo scenes + composition sketch to renders/ (same scenes as the panel's demos).
    ├── tests.py              11 checks: fast delay lines vs. the notes' loops, ITD, Doppler, reverb decay time, tuning, panel backend.
    ├── echo_notebook.ipynb   Optional notebook: embeds the panel and shows the engine used from code.
    ├── renders/              Pre-rendered WAVs from demo.py (listen on headphones).
    └── echo/                 The library.
        ├── __init__.py       Exposes the public names (Echo, Orbit, Room, ...).
        ├── dsp.py            The delay-line building blocks: fractional_delay, feedback_delay, allpass, one_pole,
        │                     pluck (Karplus-Strong), ping_pong, schroeder_reverb, fdn_reverb.
        ├── spatial.py        Where sounds go and how they sound there: trajectories (Orbit, Spiral, Flyby, ...),
        │                     the Room (wall reflections), and propagate() (ITD, Doppler, distance fade, dulling).
        ├── engine.py         The Echo class: takes sources + room + reverb + delay and renders the stereo mix.
        ├── sources.py        Sound generators: plucked-string notes (as pyquist instruments) and noise ticks.
        ├── webui.py          The bridge for the control panel: a small local web server that turns the page's
        │                     settings into an Echo scene and sends back the rendered WAV. No DSP in here.
        ├── web/index.html    The control panel itself (page, styling and interactions, one file, no downloads).
        └── ui.py             The earlier ipywidgets panel, kept for reference. The browser panel replaces it.
```

## 6. If something goes wrong

| Symptom | Fix |
| --- | --- |
| `Missing package: pyquist` | `pip install pyquist` |
| Browser says "Can't reach ECHO" | The terminal running `python app.py` was stopped. Start it again and reload. |
| "Address in use" or the page won't load | `python app.py --port 9000` and open http://127.0.0.1:9000 |
| No sound after rendering | Click the play button once (browsers can block autoplay), and check the system output device. |
| Uploaded file is rejected | Use WAV or FLAC. MP3 works only if your pyquist/soundfile install supports it. |
| Freesound ID fails | It needs internet and Freesound access via pyquist. Use a built-in sound instead. |
| Render feels slow | Shorten **Length**, lower **Decay time**, or turn off the room. Most scenes render in a few seconds. |
