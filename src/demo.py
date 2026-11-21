"""demo.py: render the example scenes shown in the demo video
    python demo.py                       # synthetic sources only (no files needed)
    python demo.py --files a.wav b.wav   # also use your own recordings as sources
    python demo.py --play                # play each render after writing it

Writes four stereo WAV files (44.1 kHz) to ./renders/:
  1_doppler_flyby      dry ticks fly past: time difference, Doppler, loudness
  2_orbiting_strings   plucked arpeggio orbits in a room w/ reverb and ping-pong echo
  3_distant_cathedral  bells spiral in a huge, dark, reverberant space
  4_composition_sketch layered scene that previews the final composition
These are the same scenes as the demo cards in the control panel. Best on headphones
"""

import argparse
import time
from pathlib import Path

import pyquist as pq

from echo import DelaySettings, Echo, Flyby, Orbit, Oscillate, Propagation, ReverbSettings, Room, Spiral, Static, Waypoints
from echo import (sources)

OUT = Path("renders")


def finish(name, audio, play):
    OUT.mkdir(exist_ok=True)
    audio.write(str(OUT / f"{name}.wav"))
    print(f"  wrote renders/{name}.wav  ({audio.duration:.1f} s)")
    if play:
        pq.play(audio, normalize=True)


def pentatonic_arp(seconds, step=0.25, base=("A3", "C4", "D4", "E4", "G4", "A4", "E4", "D4")):
    n = int(seconds / step)
    return [(i * step, base[i % len(base)], 2.0) for i in range(n)]


def demo1_doppler_flyby(play):
    """Demo 1- Doppler Flyby: dry ticking source flies past the listener: ITD, Doppler, level"""
    e = Echo()
    e.reverb.enabled = False
    e.room.enabled = False
    ticks = sources.noise_bursts([i * 0.1 for i in range(80)], length=0.08)
    e.add_source(ticks, "flyby", motion=Flyby(-40, 3, 40, 3, duration=7.0, start=0.5),
                 prop=Propagation(doppler=1.0, rolloff=1.0, air_absorption=1.0))
    plucked = sources.pluck_line([(i * 0.5, n, 1.5) for i, n in enumerate(["A2", "E3", "A3", "C4"] * 4)],
                                 t60=1.5, damping=0.5)
    e.add_source(plucked, "bass string", motion=Static(-1.5, 1.0), gain_db=-3, send=0.0)
    finish("1_doppler_flyby", e.render(8.0), play)


def demo2_orbiting_strings(play):
    """Demo 2- Orbiting Strings: plucked-string arpeggio orbiting in a live room w/ ping-pong echo"""
    e = Echo()
    e.room = Room(width=14, depth=11, absorption=0.25)
    e.reverb = ReverbSettings(kind="fdn", t60=3.0, damping=0.25, level_db=-8.0)
    e.delay = DelaySettings(enabled=True, time=0.375, feedback=0.5, level_db=-9.0)
    arp = sources.pluck_line(pentatonic_arp(16), t60=2.0, damping=0.4, pick_position=0.2)
    e.add_source(arp, "arp", motion=Orbit(radius=3.5, speed=0.08), send=0.35)
    drone = sources.pluck_line([(0, "A1", 8.0), (8, "E2", 8.0)], t60=24.0, damping=0.5)
    e.add_source(drone, "drone", motion=Static(0.0, 5.0), gain_db=-4, send=0.6)
    finish("2_orbiting_strings", e.render(16.0), play)


def demo3_distant_cathedral(play, files):
    """Demo 3- Distant Cathedral: big, dark, distant; spiralling source in a huge reverberant room"""
    e = Echo()
    e.room = Room(width=40, depth=30, absorption=0.1)
    e.reverb = ReverbSettings(kind="fdn", t60=7.0, damping=0.4, size=1.8, predelay=0.06, level_db=-3.0)
    e.delay = DelaySettings(enabled=False)
    if files:
        e.add_source(files[0], motion=Spiral(r_min=4, r_max=14, speed=0.05), send=0.8,
                     prop=Propagation(air_absorption=2.0))
    else:
        bells = sources.pluck_line([(0, "E3", 6), (2.5, "B3", 6), (5, "G4", 6), (7.5, "E4", 6)],
                                   t60=5.0, damping=0.25, pick_position=0.12)
        e.add_source(bells, "bells", motion=Spiral(r_min=4, r_max=14, speed=0.05), send=0.8,
                     prop=Propagation(air_absorption=2.0))
    finish("3_distant_cathedral", e.render(14.0), play)


def sketch(play, files):
    """Composition sketch (~30 s): layers enter one by one, move in opposite directions,
    then everything dissolves into reverb tail"""
    e = Echo()
    e.room = Room(width=16, depth=12, absorption=0.3)
    e.reverb = ReverbSettings(t60=4.0, damping=0.3, level_db=-6.0)
    e.delay = DelaySettings(enabled=True, time=0.45, feedback=0.55, level_db=-10.0)
    drone = sources.pluck_line([(0, "A1", 12), (12, "F1", 12), (24, "E1", 10)], t60=30.0)
    e.add_source(drone, "drone", motion=Static(0, 6.0), gain_db=-6, send=0.8)
    arp = sources.pluck_line(pentatonic_arp(24, 0.3), t60=2.0, damping=0.4, pick_position=0.18)
    e.add_source(arp, "arp A", motion=Orbit(radius=4, speed=0.07), start=6.0, send=0.4)
    arp2 = sources.pluck_line(pentatonic_arp(18, 0.45, base=("E4", "A4", "C5", "D5", "G4")),
                              t60=3.0, damping=0.5)
    e.add_source(arp2, "arp B", motion=Orbit(radius=4, speed=-0.05, phase=3.14), start=12.0, send=0.5)
    ticks = sources.noise_bursts([i * 0.3 for i in range(40)], length=0.05)
    e.add_source(ticks, "ticks", motion=Oscillate(cy=2.0, amplitude=5, speed=0.2), start=18.0,
                 gain_db=-8, send=0.2)
    e.add_source(sources.pluck_line([(0, "A3", 4)], t60=4.0), "fly",
                 motion=Flyby(-25, 3, 25, 3, duration=5.0, start=22.0), start=22.0, loop=False, send=0.3)
    finish("4_composition_sketch", e.render(26.0), play)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="*", default=[], help="optional audio files to use as sources")
    ap.add_argument("--play", action="store_true")
    args = ap.parse_args()
    for fn, a in [(demo1_doppler_flyby, ()), (demo2_orbiting_strings, ()),
                  (demo3_distant_cathedral, (args.files,)), (sketch, (args.files,))]:
        t0 = time.time()
        print(fn.__name__)
        fn(args.play, *a)
        print(f"  {time.time() - t0:.1f} s to render")
