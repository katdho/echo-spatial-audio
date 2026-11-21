"""ECHO: a spatial delay-line instrument built on pyquist

Package layout:
  dsp.py      delay-line building blocks (fractional delay, reverbs, plucked string)
  spatial.py  sound paths, the room, and the binaural propagation model
  engine.py   the Echo class: sources + room + reverb + delay -> stereo render
  sources.py  built-in sounds (plucked strings, noise ticks)
  webui.py    local web server for the browser control panel (no DSP)
Import the public names from here:  from echo import Echo, Orbit, ReverbSettings
"""

from echo import dsp, sources
from .engine import DelaySettings, Echo, ReverbSettings, Source
from .spatial import (MOTIONS, Flyby, Oscillate, Orbit, Propagation, Room, Spiral,
                      Static, Waypoints)

__all__ = ["Echo", "Source", "ReverbSettings", "DelaySettings", "Room", "Propagation",
           "Static", "Orbit", "Spiral", "Oscillate", "Flyby", "Waypoints", "MOTIONS",
           "dsp", "sources"]
