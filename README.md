# ECHO
 
ECHO is a spatial-audio instrument. You place sounds in a virtual room, move them around a listener, and it renders a stereo mix for headphones. You hear each sound's direction, distance, movement, and the space around it.
 
Everything is built from delay lines in NumPy on top of pyquist for audio I/O.
 
## What you can hear
| Effect | How it is made |
| --- | --- |
| Direction (left, right, front) | Each ear reads the sound at a slightly different delay |
| Movement and pitch bend (Doppler) | The delay changes over time, so the read point speeds up or slows down |
| Distance | Quieter and duller with distance, plus a muffled far ear (head shadow) |
| Room | Four wall echoes, made by mirrored copies of each sound |
| Space | A feedback-delay-network reverb (or the classic Schroeder reverb) |
| Rhythm | A ping-pong echo that bounces between your ears |
| Plucked strings | A Karplus-Strong physical model, as the built-in sound source |
 
Recommended to **Use headphones:** The 3-D effect is binaural and collapses on speakers
 
## Quick start
```sh
git clone https://github.com/katdho/echo-spatial-audio.git
pip install pyquist
python src/tests.py      # should end with: all 11 tests passed
python src/app.py        # opens the control panel in your browser
```
 
Then follow the following steps at the top of the page
1. **Choose sounds:** Open a demo scene, or click sounds to add them, then press **Build scene**
2. **Shape the scene:** The map is in the middle: drag sounds to move them and hover on any control to see what it does
    - Sliders for each sound are on the left
    - Room, reverb and echo are on the right
3. **Listen:** Press **Render and play** (or Space). The dots move along their paths in time w/ the audio
    - **Export WAV** saves the result
    - Reset options: double-click a control's name to reset it
        - **Reset sliders** to restore everything but keep your sounds
        - **Start over** to clear it all
 
Other commands:
 
```sh
python src/demo.py                     # renders the demo scenes to renders/*.wav
python src/demo.py --files a.wav       # same, using your own recording
python src/app.py --port 9000          # use another port if 8765 is busy
jupyter lab src/echo_notebook.ipynb    # optional: the panel inside a notebook
```
 
## Use it from code
```python
from echo import Echo, Orbit, ReverbSettings, sources
 
e = Echo()
e.add_source(sources.pluck_line([(0, "A3", 2.0)]), motion=Orbit(radius=3, speed=0.1), send=0.4)
e.reverb = ReverbSettings(t60=3.0)
e.render(20.0).write("out.wav")
```
 
## How it fits together
 
```
source audio ─→ spatial.propagate() ─→ dry stereo ─┬─→ ping-pong delay ─┐
      │         (direct sound + 4 wall echoes)     │                    ├─→ stereo out
      └─ × reverb send ─→ reverb ──────────────────┴────────────────────┘
```
 
## Files
 
```
README.md          This file: Overview of Everything
DEMO_GUIDE.md      Step-by-step demo walkthrough, timed script for the video, troubleshooting.
TECHNICAL.md       Project write-up: requirements, every parameter, citations, AI workflow.
src/
  app.py           START HERE. Launches the control panel.
  demo.py          Renders the demo scenes to renders/.
  tests.py         11 checks of the DSP and the panel's backend.
  echo_notebook.ipynb   Optional notebook that embeds the panel and shows code examples
  renders/         Pre-rendered WAVs from demo.py
  echo/
    dsp.py         Delay-line building blocks: fractional delay, feedback delay, all-pass
                   one-pole filter, Karplus-Strong string, ping-pong, both reverbs.
    spatial.py     Sound paths (orbit, spiral, fly-by, ...), the room, and propagate()
                   for time difference, Doppler, distance fade and dulling
    engine.py      The Echo class: combines sources, room, reverb and echo into a mix
    sources.py     Built-in sounds: plucked-string notes and noise ticks
    webui.py       Local web server that connects the control panel to the engine. No DSP
    web/index.html The control panel (page, styling and behavior in one file)
```
 
## Requirements
Python 3.10 or newer and `pip install pyquist`. The control panel needs nothing else. `matplotlib` and `ipywidgets` are only for the optional notebook
 
## Notes and limits
- The room is 2D (top-down, four walls), and sources should be inside it. It is an artistic approximation, not an acoustic simulation
- Rendering takes a few seconds for typical scenes. Longer scenes and longer reverb decay take longer
- Freesound sounds need an internet connection. Uploaded files work best as WAV or FLAC
 