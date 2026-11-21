## Project Overview

**ECHO** is a spatial-audio instrument for creating moving sound scenes. Users place audio sources in a virtual room, assign them motion paths around a listener, and render them as binaural stereo audio. The renderer simulates interaural time differences (ITD), Doppler shift, distance-dependent attenuation, early reflections, and reverberation.

The project consists of a Python library (`src/echo/`), a browser-based control panel (`python app.py`), and a Jupyter notebook (`src/echo_notebook.ipynb`) that embeds the same interface. Sources can be user recordings, Freesound IDs, or synthesized Karplus–Strong plucked strings. ECHO serves as the spatial mixing stage for my final composition, turning individual audio layers into a moving, reverberant stereo scene.

## Requirements and Features

### R1: Technique

ECHO combines **delay lines, effects, and spatialization (Chapter 13)** with **physical modeling (Chapter 12)**.

Its central technique is a time-varying fractional delay line. For each ear, the renderer reads the source signal at a delay determined by its distance from that ear. The difference between the two delays produces interaural time differences, while changes in delay over time produce Doppler shift.

The same approach simulates early room reflections using mirrored image sources to represent sound paths reflected by the walls. Late reverberation is generated with an eight-line feedback delay network (FDN), using a Hadamard feedback matrix, per-line decay gains, and in-loop damping. A Schroeder reverb is also available. The ping-pong delay uses cross-feedback between stereo channels. The project also incorporates source trajectories (orbit, spiral, oscillation, flyby, and waypoints) and a Karplus–Strong plucked-string generator.

### R2: Implementation

All core signal-processing algorithms are implemented in NumPy, without relying on external audio-effect, reverb, panning, or time-stretching libraries.

The implementation is organized into 3 main modules:
- `src/echo/dsp.py`: fractional and feedback delays, filters, Karplus–Strong synthesis, ping-pong delay, and reverb algorithms.
- `src/echo/spatial.py`: source trajectories, room image sources, and binaural propagation.
- `src/echo/engine.py`: combines source audio, spatialization, reflections, delay, and reverb into the final stereo mix.

Feedback algorithms use block-based evaluation instead of the sample-by-sample loops shown in the course notes. Each recurrence is evaluated in blocks of \(M\) samples using vector operations. This is exact because each output sample depends only on input and feedback samples at least \(M\) positions earlier. `tests.py` verifies equivalence with the sample-by-sample circular-buffer implementations.

Pyquist handles audio I/O, `Audio` and `Score` objects, pitch helpers, and playback; NumPy handles the DSP algorithms.

`python tests.py` runs 11 checks covering:
- Equivalence of block-based and sample-by-sample feedback delays.
- Flat magnitude response of the all-pass filter.
- Interaural delay corresponding to the modeled head width (approximately 22 samples).
- Doppler pitch changes during a flyby and their removal when `doppler=0`.
- FDN decay matching the requested T60.
- Correct tuning of the plucked-string generator.
- Alternating stereo echoes from the ping-pong delay.
- Successful construction and stereo rendering of all control-panel demo scenes.

### R3: Controllability

The control panel exposes parameters for source motion, spatialization, room acoustics, and effects. The ranges below describe the UI controls; the underlying library accepts arbitrary values.

**Per-source controls**

| Parameter | UI range / options | Purpose |
|---|---|---|
| `motion` | Static, Orbit, Spiral, Oscillate, Flyby, Waypoints | Selects the source trajectory. |
| `x`, `y` | −15 to 15 m | Sets the source's center or starting position. The listener is at the origin, facing +y. |
| `radius` | 0.5 to 40 m | Controls orbit radius, oscillation amplitude, spiral outer radius, or flyby half-span. |
| `speed` | −0.5 to +0.5 rev/s or Hz | Controls motion rate. Positive circular motion is counter-clockwise; negative motion reverses direction. |
| `pass_time` | 1 to 30 s | Sets the duration of a flyby. |
| `gain_db` | −30 to +6 dB | Sets source level. |
| `send` | 0 to 1 | Sets the amount sent to the reverb. Higher values make the source sound more reverberant and distant. |
| `doppler` | 0 to 3 | Scales Doppler shift: 0 disables it, 1 is physical, and values above 1 exaggerate it. |
| `rolloff` | 0 to 2 | Controls distance attenuation. A value of 1 gives inverse-distance behavior; 0 disables level attenuation. |
| `air_absorption` | 0 to 4 | Controls distance-dependent high-frequency attenuation. |
| `head_shadow` | 0 to 1 | Controls high-frequency attenuation at the ear facing away from the source. |

**Room controls**

| Parameter | UI range | Purpose |
|---|---|---|
| `enabled` | On / Off | Enables or disables early reflections. |
| `width`, `depth` | 4 to 60 m | Sets room dimensions and therefore reflection delays. |
| `absorption` | 0 to 1 | Controls wall absorption. Lower absorption produces stronger, brighter reflections. |

**Reverb controls**
| Parameter | UI range / options | Purpose |
|---|---|---|
| `kind` | `fdn` / `schroeder` | Selects the reverb algorithm. |
| `t60` | 0.3 to 10 s | Sets the time for the reverb to decay by 60 dB. |
| `damping` | 0 to 0.5 | Controls in-loop high-frequency damping. Higher values produce darker reverberation. |
| `size` | 0.5 to 2.5 | Scales FDN delay lengths, affecting echo spacing and density. |
| `predelay` | 0 to 0.2 s | Sets the delay before the reverb tail begins. |
| `level_db` | −30 to +6 dB | Sets the reverb return level. |

**Ping-pong delay controls**
| Parameter | UI range | Purpose |
|---|---|---|
| `time` | 0.05 to 1.5 s | Sets the spacing between echoes. |
| `feedback` | 0 to 0.95 | Controls the number and decay of repeats. |
| `level_db` | −30 to +6 dB | Sets the delay return level. |

**Plucked-string generator controls**
The built-in generator is available through `sources.pluck_line` and `sources.pluck_instrument`.

| Parameter | Purpose |
|---|---|
| `pitch` | Sets the note using a note name or MIDI number. |
| `duration` | Sets the note duration in seconds. |
| `t60` | Sets the string's 60 dB decay time. |
| `damping` | Controls high-frequency damping in the feedback loop. |
| `pick_position` | Controls the comb-filter coloration of the pluck; 0 disables it. |

### R4: Demonstration 

`demo.py` renders three demonstration scenes and a composition sketch into `src/renders/`. The same scenes are available in the browser control panel.

1. **Doppler flyby — `1_doppler_flyby.wav`:** Dry noise ticks pass the listener at a distance of 3 m, with room reflections and reverb disabled. This isolates interaural timing, Doppler shift, distance attenuation, and high-frequency darkening. Setting Doppler to zero provides a direct comparison.
2. **Orbiting strings — `2_orbiting_strings.wav`:** A plucked-string arpeggio moves around a 14 × 11 m room, with FDN reverb and ping-pong delay. A drone provides a stationary background layer
3. **Distant cathedral — `3_distant_cathedral.wav`:** Bell-like plucks spiral through a 40 × 30 m room. A dark FDN reverb with a 7-second T60 and predelay creates a long, spacious tail. The `--files` option allows user recordings to replace the synthesized bells.
4. **Composition sketch — `4_composition_sketch.wav`:** A roughly 26-second sketch demonstrates how the spatial effects can be combined into a musical arrangement. Its structure is described in R5

### R5 — Composition Plan

I plan to use ECHO as the spatial mixing stage for each layer of my final composition. The source material will include my own recordings and Karplus–Strong strings scheduled with `pq.Score`. Each layer will pass through `Echo.render()` to produce a stereo stem, with `Waypoints` trajectories used to make the movement follow the composition's form.

The composition will follow the structure of `4_composition_sketch.wav`:
1. A distant drone enters.
2. A plucked-string arpeggio orbits counter-clockwise.
3. A second, counter-arpeggio orbits in the opposite direction.
4. Noise ticks sweep from left to right.
5. A Doppler flyby marks the climax.
6. The layers gradually disappear into the reverberation tail.

Longer T60 and larger room-size settings create open, spacious sections; a smaller room with the delay disabled creates more intimate sections; and ping-pong delay adds rhythmic movement to selected layers

## Getting Started

### Requirements
- Python 3.10 or later
- `pyquist`

NumPy, `soundfile`, and `sounddevice` are installed with Pyquist. The browser control panel uses only the Python standard library. The optional notebook additionally uses `ipywidgets` and `matplotlib`.

Rendering does not require audio hardware. Playback uses the browser's audio output or an available audio device. **Headphones are strongly recommended** because the spatial cues are designed for binaural listening.

### Run the Project

Open a terminal in the `src/` directory:

```sh
pip install pyquist                 # Install dependencies (once)
python tests.py                     # Run the 11 DSP and backend checks
python demo.py                      # Render the three demos and composition sketch
python demo.py --files a.wav        # Use a recording in demos 3 and 4
python app.py                       # Start the browser control panel
python app.py --port 9000            # Use an alternate port if 8765 is busy
jupyter lab echo_notebook.ipynb     # Open the optional notebook
```

The control panel opens at `http://127.0.0.1:8765`. Stop its local server with Ctrl+C in the terminal.

### Use the Control Panel

The panel guides you through three steps:

1. **Choose sounds.** Select a demo scene or add sounds individually. You can also upload a recording or add a Freesound ID. Set the render length and click **Build scene**.
2. **Shape the scene.** The map shows the listener at the center, facing upward. Colored dots represent sound sources, and dashed lines show their trajectories. Drag a dot to reposition a source. Select a source to adjust its motion, position, size, speed, and level. Room, reverb, and ping-pong delay settings are on the right.
3. **Listen.** Click **Render and play** (or press Space). The audio plays while the dots move along their trajectories. Use the playback bar to seek, and **Export WAV** to save the result. After changing settings, render again to hear the updated scene.

Hover over controls for descriptions. Double-click a control's name to reset that control. The section-level **Reset** buttons reset their settings; **Reset sliders** restores settings while keeping the selected sounds; **Start over** clears the scene.

Keyboard shortcuts: **Space** plays or pauses (or renders the first time); **R** renders.

### Troubleshooting
| Problem | What to try |
|---|---|
| `Missing package: pyquist` | Run `pip install pyquist`. |
| Browser cannot reach ECHO | Make sure the terminal running `python app.py` is still open; restart the server and reload the page. |
| Address already in use | Start with `python app.py --port 9000` and open `http://127.0.0.1:9000`. |
| No sound after rendering | Click Play once; the browser may block autoplay. Check the system output device. |
| Uploaded file is rejected | Use WAV or FLAC. MP3 support depends on the installed audio libraries. |
| Freesound ID fails | Freesound access requires an internet connection. Try a built-in sound instead. |
| Rendering is slow | Shorten the render length, lower the reverb decay time, or disable the room. |

## Code Organization
```text
echo_submission/
├── TECHNICAL.md
├── DEMO_GUIDE.md
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
        ├── webui.py             # Local server connecting the panel to the engine
        ├── web/
        │   └── index.html       # Browser control panel
        └── ui.py                # Earlier ipywidgets interface, retained for reference
```

## AI Workflow
Building off of the classnotes and previous assignment notebooks, I used AI to help me implement some of the DSP algorithms, improve code readability, and debug. I also used it to help revise module documentation, organize the technical summary, and prepare the demonstration script.

However, I was the one to primarily make design decisions about the project's direction, selected and integrated the techniques, and reviewed the suggested changes before incorporating them. I used the project's test suite to check the DSP algorithms and control-panel functionality, and retained responsibility for understanding and evaluating the final implementation as well.

## Other Tools
- Awesome Screenshot Chrome Extension to Record Demo


## References
- Course notes:
  - `pcm-12-physical`: feedback delay, Karplus–Strong pluck, and `tune`.
  - `pcm-13-effects`: variable fractional delay, multi-tap delay, all-pass filters, Schroeder reverb, wet/dry mixing, ping-pong delay, and panning.
  - `pcm-10-realtime`: block-based processing and control rate.
- Karplus, K., and Strong, A. "Digital Synthesis of Plucked-String and Drum Timbres." *Computer Music Journal* 7(2), 1983.
- Schroeder, M. R. "Natural Sounding Artificial Reverberation." *Journal of the Audio Engineering Society* 10(3), 1962.
- Stautner, J., and Puckette, M. "Designing Multi-Channel Reverberators." *Computer Music Journal* 6(1), 1982.
- Allen, J. B., and Berkley, D. A. "Image method for efficiently simulating small-room acoustics." *Journal of the Acoustical Society of America* 65(4), 1979.
- Speed of sound: 343 m/s. Assumed ear spacing: 17.5 cm
- Pyquist: used for `Audio`, `Score`, pitch and decibel helpers, and playback. No external audio samples are included; all example sounds are synthesized

## Additional Comments for the Instructor or TAs
The directory `src/renders/` contains the WAV files generated by `python demo.py`, corresponding to the audio used in the demonstration video.

The block-based feedback-delay evaluation is exact rather than an approximation. `tests.py` compares it against the sample-by-sample circular-buffer implementation from the course notes.

The room model is two-dimensional, with a top-down layout and four walls. Reflections assume sources are inside the room, so the model is intended as an artistic spatial-audio approximation rather than a complete acoustic simulation.

## Project Sharing
Please indicate your preferences for sharing the project in class or on the course website:
- Permission to share the demo video: Y
- Permission to share the project summary: Y
- Preferred public attribution name (real name, artist moniker, or "Anonymous"): Katia Ho