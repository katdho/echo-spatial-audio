## Project Overview

**ECHO** is a spatial-audio instrument for creating moving sound scenes. Users place audio sources in a virtual room, assign them motion paths around a listener, and render them as binaural stereo audio. The renderer simulates interaural time differences (ITD), Doppler shift, distance-dependent attenuation, early reflections, and reverberation.

The project consists of a Python library (`src/echo/`), a browser-based control panel (`python app.py`), and a Jupyter notebook (`src/echo_notebook.ipynb`) that embeds the same interface. The control panel's front end is plain HTML, CSS, and JavaScript modules served by a small Python standard-library server, so it needs no build step or extra dependencies. Sources can be user recordings, Freesound IDs, or synthesized Karplus–Strong plucked strings. ECHO serves as the spatial mixing stage for my final composition, turning individual audio layers into a moving, reverberant stereo scene.

## Requirements and Features

### R1: Technique

ECHO combines **delay lines, effects, and spatialization (Chapter 13)** with **physical modeling (Chapter 12)**.

Its central technique is a time-varying fractional delay line. For each ear, the renderer reads the source signal at a delay determined by its distance from that ear. The difference between the two delays produces interaural time differences, while changes in delay over time produce Doppler shift.

The same approach simulates early room reflections using mirrored image sources to represent sound paths reflected by the walls. Late reverberation is generated with an eight-line feedback delay network (FDN), using a Hadamard feedback matrix, per-line decay gains, and in-loop damping. A Schroeder reverb is also available. The ping-pong delay uses cross-feedback between stereo channels. The project also incorporates source trajectories (orbit, spiral, oscillation, flyby, and waypoints) and a Karplus–Strong plucked-string generator.

### R2: Implementation

All core signal-processing algorithms are implemented in NumPy.

The implementation is organized into 3 main modules:
- `src/echo/dsp.py`: fractional and feedback delays, filters, Karplus–Strong synthesis, ping-pong delay, and reverb algorithms
- `src/echo/spatial.py`: source trajectories, room image sources, and binaural propagation
- `src/echo/engine.py`: combines source audio, spatialization, reflections, delay, and reverb into the final stereo mix

Feedback algorithms use block-based evaluation instead of the sample-by-sample loops shown in the course notes. Each recurrence is evaluated in blocks of \(M\) samples using vector operations. This is exact because each output sample depends only on input and feedback samples at least \(M\) positions earlier. `tests.py` verifies equivalence with the sample-by-sample circular-buffer implementations from class.

Pyquist handles audio I/O, `Audio` and `Score` objects, pitch helpers, and playback; NumPy handles the DSP algorithms.

`python tests.py` runs 11 checks covering:
- Equivalence of block-based and sample-by-sample feedback delays
- Flat magnitude response of the all-pass filter
- Interaural delay corresponding to the modeled head width (approximately 22 samples)
- Doppler pitch changes during a flyby and their removal when `doppler=0`
- FDN decay matching the requested T60
- Correct tuning of the plucked-string generator
- Alternating stereo echoes from the ping-pong delay
- Successful construction and stereo rendering of all control-panel demo scenes

#### Control-panel Architecture

The control panel is split between a Python back end and a browser front end that talk over a small JSON API

**Back end (`src/echo/webui.py`):** A `ThreadingHTTPServer` bound to `127.0.0.1` that:
- Serves the static files in `src/echo/web/` (`index.html`, `style.css`, and the `js/` modules)
- Holds the sound catalog (`KINDS`) and the demo scenes (`PRESETS`), and returns both from `/api/catalog`
- Converts the browser's JSON scene into an `Echo` engine (`build_echo`, `build_motion`) where all numeric settings are read through `_num`, which falls back to a default for missing or non-finite values and clamps to a safe range
- Caches generated sounds by `(kind, argument)` so repeated renders do not resynthesize them
- Renders on request, scales the mix, and limits it to a 0.95 peak before returning a WAV. Renders are serialized with a lock. It also compares each render with the previous one and reports the relative difference in the `X-Change` header, which the frontend uses for its "Difference from your last render" message

| Endpoint | Purpose |
|---|---|
| `GET /` and static files | Serve `index.html`, `style.css`, and `js/*.js`. |
| `GET /api/catalog` | Available sounds and demo scenes |
| `POST /api/scene` | Sampled source trajectories, used to draw the map |
| `POST /api/render` | Render the scene and return stereo WAV audio. The `X-Duration`, `X-Render-Seconds`, and `X-Change` headers carry length, render time, and difference from the previous render |
| `POST /api/upload` | Store an uploaded recording and check that it can be read (limit 100 MB) |
| `POST /api/probe` | Check that a sound (for example, a Freesound ID) can be loaded |

The scene holds at most 12 sources, and render length can be set between 3 to 90 seconds

**Front end (`src/echo/web/`):** The page is split by responsibility: `index.html` holds only structure; `style.css` holds the theme and layout, and the behavior is in ES modules under `js/`, loaded by a single `<script type="module">` tag that points at `js/app.js`. The page uses absolute paths (`/style.css`, `/js/app.js`), so it must be loaded through the ECHO server rather than opened as a file.

| Module | Responsibility |
|---|---|
| `js/state.js` | Constants (colors, default parameters, motion list, room/reverb/delay defaults), the shared scene state `S`, the reset snapshot `G0`, the UI state object `ui`, and small helpers such as the `h()` element builder |
| `js/controls.js` | Status line and button states, the slider, toggle, and select builders, the left panel (per-sound controls), the right panel (room, reverb, ping-pong echo), and the render-length sliders |
| `js/scene.js` | Fetches trajectories from `/api/scene`, draws the room map on a canvas, and handles dragging sources |
| `js/audio.js` | Calls `/api/render`, drives the audio element and playback bar, keeps the previous render for A/B comparison, and handles keyboard shortcuts |
| `js/setup.js` | Adding and removing sounds, the step 1 setup screen and demo cards, the "Add sound" dialog, file uploads, Freesound lookup, and navigation between steps |
| `js/app.js` | Entry point. Connects the step bar, **Build scene**, **Reset sliders**, and **Start over**, then loads the catalog |

Mutable state lives in the shared objects `S`, `G0`, and `ui`, which are updated in place, because an ES module can read another module's exports but cannot reassign them. A source that is changed on the page is sent to the server as part of the whole scene JSON on each render, so the browser never holds audio data except the finished render.

### R3: Controllability

The control panel exposes parameters for source motion, spatialization, room acoustics, and effects. The ranges below describe the UI controls; the underlying library accepts arbitrary values. Each table lists the plain-language label the panel shows for the control. Note: A few of the panel's internal JSON field names are shorter than the library parameter names (`gain` for `gain_db`, `air` for `air_absorption`, `shadow` for `head_shadow`)
 
**Per-source controls**
 
| Parameter | Panel label | UI range / options | Purpose |
|---|---|---|---|
| `motion` | Movement Pattern | Static ("Stay put"), Orbit ("Circle around you"), Spiral ("Spiral in and out"), Oscillate ("Sweep left and right"), Flyby ("Fly past once") | Selects the source trajectory. `Waypoints` trajectories are available through the Python library but are not offered in the panel |
| `x` | X-Position (Left/Right) | −15 to 15 m | Sets the source's center or starting position. The listener is at the origin, facing +y. Sources can also be dragged on the map. |
| `y` | Y-Position (Back/Front) | −15 to 15 m | Same as `x`, along the front/back axis. |
| `radius` | Orbit Radius, Spiral Radius, Sweep Range, or Pass Distance/Offset (depends on the movement pattern; hidden for Static) | 0.5 to 40 m | Controls orbit radius, oscillation amplitude, spiral outer radius, or flyby half-span. |
| `speed` | Movement Rate (Speed) | −0.5 to +0.5 rev/s or Hz | Controls motion rate (shown in the panel as laps or swings per minute). Positive circular motion is counter-clockwise; negative motion reverses direction. Shown for Orbit, Spiral, and Oscillate only. |
| `pass_time` | Pass Duration | 1 to 30 s | Sets the duration of a flyby. Shown for Flyby only. |
| `start` | Start Time | 0 to the render length | Sets when the source enters the scene, which is how the composition sketch brings its layers in one by one. |
| `gain_db` (`gain` in the panel's JSON) | Volume | −30 to +6 dB | Sets source level. |
| `send` | Reverb amount | 0 to 1 | Sets the amount sent to the reverb. Higher values make the source sound more reverberant and distant. |
| `doppler` | Doppler Effect | 0 to 3 | Scales Doppler shift: 0 disables it, 1 is physical, and values above 1 exaggerate it. |
| `rolloff` | Distance Attenuation | 0 to 2 | Controls distance attenuation. A value of 1 gives inverse-distance behavior; 0 disables level attenuation. |
| `air_absorption` (`air`) | Air Absorption | 0 to 4 | Controls distance-dependent high-frequency attenuation. |
| `head_shadow` (`shadow`) | Head Shadow | 0 to 1 | Controls high-frequency attenuation at the ear facing away from the source. |
 
Controls that would have no effect in the current scene (for example, Doppler on a static source, or reverb send when the reverb is off) are dimmed/greyed-out, with the tooltip explaining why.
 
**Scene controls**
 
| Parameter | Panel label | UI range | Purpose |
|---|---|---|---|
| `length` | Length | 3 to 90 s | Sets the render length. The rendered file is longer than this setting by the reverb and echo tail. |
 
**Room controls**
 
| Parameter | Panel label | UI range | Purpose |
|---|---|---|---|
| `enabled` | On/off switch in the **Room** header | On / Off | Enables or disables early reflections. |
| `width` | Width | 4 to 60 m | Sets room width and therefore side-wall reflection delays. |
| `depth` | Depth | 4 to 60 m | Sets room depth and therefore front/back reflection delays. |
| `absorption` | Wall softness | 0 to 1 | Controls wall absorption. Lower absorption produces stronger, brighter reflections. |
 
**Reverb controls**
 
| Parameter | Panel label | UI range / options | Purpose |
|---|---|---|---|
| `enabled` | On/off switch in the **Reverb** header | On / Off | Enables or disables the reverb. |
| `kind` | Type | `fdn` ("Smooth (feedback network)") / `schroeder` ("Classic (Schroeder)") | Selects the reverb algorithm. |
| `t60` | Decay time | 0.3 to 10 s | Sets the time for the reverb to decay by 60 dB. |
| `damping` | Darkness | 0 to 0.5 | Controls in-loop high-frequency damping. Higher values produce darker reverberation. |
| `size` | Space size | 0.5 to 2.5 | Scales FDN delay lengths, affecting echo spacing and density. |
| `predelay` | Pre-delay | 0 to 0.2 s | Sets the delay before the reverb tail begins. |
| `level_db` | Level | −30 to +6 dB | Sets the reverb return level. |
 
**Ping-pong delay controls** (the section is titled **Ping-pong echo** in the panel)
 
| Parameter | Panel label | UI range | Purpose |
|---|---|---|---|
| `enabled` | On/off switch in the **Ping-pong echo** header | On / Off | Enables or disables the delay. |
| `time` | Time between echoes | 0.05 to 1.5 s | Sets the spacing between echoes. |
| `feedback` | Repeats | 0 to 0.95 | Controls the number and decay of repeats. |
| `level_db` | Level | −30 to +6 dB | Sets the delay return level. |
 
**Plucked-string generator controls**
The built-in generator is available through `sources.pluck_line` and `sources.pluck_instrument`
 
| Parameter | Purpose |
|---|---|
| `pitch` | Sets the note using a note name or MIDI number. |
| `duration` | Sets the note duration in seconds. |
| `t60` | Sets the string's 60 dB decay time. |
| `damping` | Controls high-frequency damping in the feedback loop. |
| `pick_position` | Controls the comb-filter coloration of the pluck; 0 disables it. |

### R4: Demonstration 

`demo.py` renders three demonstration scenes and a composition sketch into `src/renders/`. The same scenes are available in the browser control panel as example cards on the first screen.

1. **Doppler flyby — `1_doppler_flyby.wav`:** Dry noise ticks pass the listener at a distance of 3 m, with room reflections and reverb disabled. This isolates interaural timing, Doppler shift, distance attenuation, and high-frequency darkening. Setting Doppler to zero provides a direct comparison. (The panel's version of this scene also includes a quiet static bass string as a fixed reference point.)
2. **Orbiting strings — `2_orbiting_strings.wav`:** A plucked-string arpeggio moves around a 14 × 11 m room, with FDN reverb and ping-pong delay. A drone provides a stationary background layer
3. **Distant cathedral — `3_distant_cathedral.wav`:** Bell-like plucks spiral through a 40 × 30 m room. A dark FDN reverb with a 7-second T60 and predelay creates a long, spacious tail. The `--files` option allows user recordings to replace the synthesized bells.
4. **Composition sketch — `4_composition_sketch.wav`:** A rough sketch that demonstrates how the spatial effects can be combined into a musical arrangement
  - Its structure is as follows:
    1. A distant drone enters
    2. A plucked-string arpeggio orbits counter-clockwise
    3. A second, counter-arpeggio orbits in the opposite direction
    4. Noise ticks sweep from left to right
    5. A Doppler flyby marks the climax
    6. The layers gradually disappear into the reverberation tail

Demo Video: [demo.mp4](demo.mp4)

### R5 — Composition Plan

I plan to use ECHO as the spatial mixing stage for each layer of my final composition. The source material will include my own recordings and Karplus–Strong strings scheduled with `pq.Score`. Each layer will pass through `Echo.render()` to produce a stereo stem, with `Waypoints` trajectories used to make the movement follow the composition's form.


## Getting Started

### Requirements
- Python 3.10 or later
- `pyquist`
- A current desktop browser (the front end uses ES modules, so it must be loaded from the ECHO server, not by double-clicking `index.html`)

NumPy, `soundfile`, and `sounddevice` are installed with Pyquist. The browser control panel uses only the Python standard library and has no JavaScript dependencies or build step. The optional notebook additionally uses `ipywidgets` and `matplotlib`

Rendering does not require audio hardware. Playback uses the browser's audio output or an available audio device. **Headphones are strongly recommended** because the spatial cues are designed for binaural listening.

### Run the Project

Open a terminal in the `src/` directory:

```sh
pip install pyquist                 # Install dependencies (once)
python tests.py                     # Run the 11 DSP and backend checks
python demo.py                      # Render the three demos and composition sketch
python demo.py --files a.wav        # Use a recording in demos 3 and 4
python app.py                       # Start the browser control panel
python app.py --port 9000            # Start looking for a free port at 9000 instead of 8765
jupyter lab echo_notebook.ipynb     # Open the optional notebook
```

The control panel opens at `http://127.0.0.1:8765`. If that port is busy, the server tries the next 19 ports and prints the address it actually uses, so check the terminal if the browser does not open the page you expect. Stop the local server with Ctrl+C in the terminal.

### Use the Control Panel

The panel guides you through three steps, shown in the bar at the top:

1. **Choose sounds:** Select a demo scene or add sounds individually. You can also upload a recording or add a Freesound ID. Set the render length and click **Build scene**
2. **Shape the scene:** The map shows the listener at the center, facing forward. Colored dots represent sound sources, and lines show their trajectories. Drag a dot to reposition a source. Select a source in the left panel to adjust its movement, start time, level, and spatialization, and use **Add sound** there to add more. Room, reverb, and ping-pong delay settings are on the right, each with an on/off switch
3. **Listen:** Click **Render and play** (or press Space). The audio plays while the dots move along their trajectories. Use the playback bar to seek, and **Export WAV** to save the result. After changing settings, the status line tells you the scene has changed; render again to hear the updated scene. After a second render, **Hear previous** switches between your last two renders at the same moment in time, and the status line reports how much the new render differs from the old one. An identical render usually means the control you moved has no effect in that scene.

Hover over controls for descriptions. Double-click a control's name to reset that control. The section-level **Reset** buttons reset their settings; **Reset sliders** restores settings while keeping the selected sounds; **Start over** clears the scene (click it twice to confirm).

Keyboard shortcuts: **Space** plays or pauses (or renders the first time); **R** renders.

### Troubleshooting
| Problem | What to try |
|---|---|
| `Missing package: pyquist` | Run `pip install pyquist` |
| Browser cannot reach ECHO ("Can't reach ECHO. Start it with `python app.py`") | Make sure the terminal running `python app.py` is still open; restart the server and reload the page |
| Address already in use | ECHO tries the next 19 ports automatically; use the address printed in the terminal. Or start with `python app.py --port 9000` |
| Page loads but is unstyled, or nothing responds | Open the page through the ECHO server (`http://127.0.0.1:<port>/`), not by opening `index.html` from disk. Also check that `style.css` and the `js/` folder are still inside `src/echo/web/` |
| No sound after rendering | Click Play once; the browser may block autoplay. Check the system output device |
| Uploaded file is rejected | Use WAV or FLAC. MP3 support depends on the installed audio libraries. Files must be under 100 MB |
| Freesound ID fails | Freesound access requires an internet connection. Try a built-in sound instead |
| Rendering is slow | Shorten the render length, lower the reverb decay time, or disable the room |

## Code Organization
```text
A9-submission/
├── TECHNICAL.md
├── demo.mp4
└── src/
    ├── app.py                  # Launches the browser control panel
    ├── demo.py                 # Renders the three demos and composition sketch
    ├── tests.py                # DSP and control-panel backend tests
    ├── echo_notebook.ipynb     # Optional notebook
    ├── renders/                # Pre-rendered WAV examples
    └── echo/
        ├── __init__.py          # Public library interface
        ├── dsp.py               # Delay lines, filters, synthesis, and reverb
        ├── spatial.py           # Trajectories, room reflections, and propagation
        ├── engine.py            # Connects sources and effects into the stereo mix
        ├── sources.py           # Plucked-string and noise source generators
        ├── webui.py             # Local server: serves web/, holds the sound and demo catalog,   
        │                          builds scenes from JSON, renders audio
        ├── web/                 # Browser control panel (static files served by webui.py)
        │   ├── index.html       # Page structure: setup screen, studio layout, add-sound dialog
        │   ├── style.css        # Theme, layout, controls, map, playback bar, responsive rules
        │   └── js/
        │       ├── app.js       # Entry point: step bar, Build, Reset, Start over, catalog load
        │       ├── state.js     # Constants, shared state, helpers (imports nothing else)
        │       ├── controls.js  # Status line, slider/toggle/select builders, left and right panels
        │       ├── scene.js     # /api/scene requests, room map drawing and dragging
        │       ├── audio.js     # Rendering, playback, A/B comparison, keyboard shortcuts
        │       └── setup.js     # Adding/removing sounds, setup screen, demos, dialog, uploads
```

## AI Workflow
Building off of the classnotes and previous assignment notebooks, I used AI to help me implement some of the spatialization and DSP algorithms, improve code readability, and debug. I also used it to help revise module documentation, organize the technical summary, and help prepare the demonstration script.

However, I was the one to primarily make design decisions about the project's direction, selected and integrated the techniques, and reviewed the suggested changes before incorporating them. I used the project's test suite to check the DSP algorithms and control-panel functionality, and retained responsibility for understanding and evaluating the final implementation as well.

## Other Tools
- Awesome Screenshot Chrome Extension to Record Demo: ECHO Prototype
- Microsoft SnipTool and Microsoft ClipChamp to Record Demo: Code & Compile Clips Together

## References
- Pyquist Library
- Course notes:
  - `pcm-12-physical`: feedback delay, Karplus–Strong pluck, and `tune`.
  - `pcm-13-effects`: variable fractional delay, multi-tap delay, all-pass filters, Schroeder reverb, wet/dry mixing, ping-pong delay, and panning.
  - `pcm-10-realtime`: block-based processing and control rate.
- Karplus, K., and Strong, A. "Digital Synthesis of Plucked-String and Drum Timbres." *Computer Music Journal* 7(2), 1983.
- Schroeder, M. R. "Natural Sounding Artificial Reverberation." *Journal of the Audio Engineering Society* 10(3), 1962.
- Stautner, J., and Puckette, M. "Designing Multi-Channel Reverberators." *Computer Music Journal* 6(1), 1982.
- Allen, J. B., and Berkley, D. A. "Image method for efficiently simulating small-room acoustics." *Journal of the Acoustical Society of America* 65(4), 1979.

## Additional Comments for the Instructor or TAs
The directory `src/renders/` contains the WAV files generated by `python demo.py`, corresponding to the audio used in the demonstration video.

The block-based feedback-delay evaluation is exact rather than an approximation. `tests.py` compares it against the sample-by-sample circular-buffer implementation from the course notes.

The room model is two-dimensional, with a top-down layout and four walls. Reflections assume sources are inside the room, so the model is intended as an artistic spatial-audio approximation rather than a complete acoustic simulation.

Lastly, I used Speed of sound: 343 m/s. Assumed ear spacing: 17.5 cm


## Project Sharing
Please indicate your preferences for sharing the project in class or on the course website:
- Permission to share the demo video: Yes
- Permission to share the project summary: Yes
- Preferred public attribution name (real name, artist moniker, or "Anonymous"): Katia Ho
