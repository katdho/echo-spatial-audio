
# ECHO: Technical Documentation

## 1. Project Overview

ECHO is an interactive spatial audio instrument for creating and exploring sound in a virtual 2D environment.

The project combines sound synthesis, spatial audio processing, room acoustics, and an interactive browser-based interface. Users can create sound sources, position them in a virtual room, configure their movement and effects, and render the resulting scene as binaural audio.

The system consists of two primary components:

- **Python backend:** Handles sound synthesis, spatial processing, acoustic effects, scene management, and audio rendering.
- **Browser frontend:** Provides the interactive interface for configuring sound sources, editing scenes, adjusting parameters, and listening to rendered audio.

## 2. System Architecture

ECHO uses a Python backend connected to a JavaScript-based browser interface through HTTP API endpoints.

### Backend

The Python backend is responsible for:

- Defining and managing sound sources.
- Generating and processing audio signals.
- Calculating spatial audio effects.
- Simulating room acoustics and reverberation.
- Rendering complete audio scenes.
- Serving the browser interface and handling API requests.

### Frontend

The frontend provides the user-facing controls and visual representation of the audio scene.

Its responsibilities include:

- Managing application state.
- Creating and modifying sound sources.
- Displaying the spatial scene.
- Updating source positions and effect parameters.
- Communicating with the Python backend.
- Requesting audio renders and managing playback.

### Communication

The browser communicates with the Python backend through JSON-based HTTP requests.

The backend runs a local HTTP server using Python's `ThreadingHTTPServer`, allowing the browser to interact with the application without requiring a separate frontend development server.

## 3. Digital Signal Processing

### 3.1 Spatial Audio

ECHO uses binaural processing to simulate the spatial position and movement of sound sources.

The system incorporates several perceptual cues:

**Interaural Time Difference (ITD)**

ITD represents the difference in the arrival time of a sound at the left and right ears.

The delay is calculated based on the source's relative position and an assumed ear spacing of approximately 17.5 cm. The speed of sound is modeled as approximately 343 m/s.

**Distance Attenuation**

Sound amplitude decreases as the distance between the listener and a source increases.

This provides a distance cue that helps distinguish nearby sources from distant ones.

**Air Absorption**

High-frequency sound energy is attenuated with increasing distance, approximating the frequency-dependent absorption of sound traveling through air.

**Head Shadow**

The listener's head creates an acoustic shadow that reduces the intensity of sound reaching the ear farther from the source.

Together, these effects provide spatial cues that help establish the apparent position of sound sources.

### 3.2 Source Movement and Trajectories

ECHO supports moving sound sources through configurable trajectories.

Supported movement patterns include:

- **Orbit:** Moves a source around a central point.
- **Spiral:** Moves a source along an expanding or contracting spiral.
- **Oscillation:** Moves a source repeatedly between positions.
- **Flyby:** Simulates a source passing by the listener.
- **Waypoints:** Moves a source through a sequence of defined positions.

Movement affects the spatial processing of the source over time, allowing the listener to perceive changes in direction, distance, and motion.

### 3.3 Doppler Effect

The Doppler effect describes the perceived change in frequency caused by relative motion between a sound source and a listener.

When a source approaches the listener, its perceived frequency increases. As it moves away, the perceived frequency decreases.

ECHO incorporates Doppler-related processing to make moving sources sound more physically convincing.

### 3.4 Early Reflections and Room Acoustics

ECHO models early reflections using an image-source approach.

Rather than simulating every possible reflection independently, image-source modeling represents reflected sound as if it originated from virtual sources positioned across room boundaries.

These reflections help establish the perceived size and acoustic characteristics of the environment.

### 3.5 Reverberation

ECHO implements both Schroeder-style reverberation and feedback delay network (FDN) reverberation.

**Schroeder Reverberation**

Schroeder reverberation combines delay-based structures, including comb filters and all-pass filters, to approximate the decay of sound in an enclosed environment.

**Feedback Delay Network**

The FDN uses multiple delay lines connected through a feedback mixing matrix.

The implementation uses:

- An eight-line delay network.
- A Hadamard feedback matrix.
- Per-line decay gains.
- Damping filters to control high-frequency decay.

The feedback structure creates a dense reverberant response while allowing the decay characteristics to be adjusted.

The implementation also uses block-based feedback-delay evaluation to improve processing efficiency. Its output was tested against a sample-by-sample circular-buffer implementation.

### 3.6 Ping-Pong Delay

Ping-pong delay alternates delayed audio between the left and right channels.

This produces a stereo echo effect that creates a sense of movement across the listener's auditory field.

### 3.7 Karplus–Strong Plucked Strings

ECHO uses the Karplus–Strong algorithm to synthesize plucked-string sounds.

The algorithm uses a feedback delay line and filtering to create a decaying waveform resembling a vibrating string.

This provides a lightweight method of generating musical sound sources without relying exclusively on prerecorded audio.

## 4. Audio Processing and Rendering

The audio engine combines source generation, spatial processing, and acoustic effects into a complete rendered scene.

A typical rendering workflow is:

1. Define the scene and its sound sources.
2. Configure source properties, positions, and trajectories.
3. Generate the audio signal for each source.
4. Apply spatial processing based on the source's position and movement.
5. Apply room acoustics and configured audio effects.
6. Combine the processed sources into the final output.
7. Render the result as an audio file for playback.

The rendering engine supports multiple simultaneous sources and processes their contributions as part of a shared scene.

The application limits scenes to 12 sources and supports render durations from 3 to 90 seconds.

The rendered output is peak-limited to 0.95 to avoid excessive output amplitude.

## 5. Software Architecture

### 5.1 Python Modules

| Module | Responsibility |
|---|---|
| `app.py` | Starts the application and web interface. |
| `demo.py` | Runs audio demonstrations and compositions. |
| `tests.py` | Runs project tests. |
| `dsp.py` | Implements digital signal-processing utilities and effects. |
| `engine.py` | Coordinates sound sources, processing, and audio rendering. |
| `sources.py` | Defines sound sources and movement trajectories. |
| `spatial.py` | Implements spatial positioning and binaural processing. |
| `webui.py` | Runs the local HTTP server and handles API requests. |

### 5.2 JavaScript Modules

The frontend is divided into smaller JavaScript modules to separate application responsibilities.

| Module | Responsibility |
|---|---|
| `app.js` | Initializes the application and coordinates frontend behavior. |
| `state.js` | Manages application state and shared data. |
| `controls.js` | Handles UI controls and user interactions. |
| `scene.js` | Manages sound sources and spatial scene visualization. |
| `audio.js` | Handles audio rendering, playback, and audio-related requests. |
| `setup.js` | Manages initial application setup and configuration. |

### 5.3 Frontend and Backend Interaction

The JavaScript frontend communicates with the Python backend through HTTP endpoints.

The frontend sends scene configuration and rendering requests to the backend. The backend processes the requests and returns the corresponding data or audio output.

This separation allows the interface and audio-processing implementation to evolve independently.

## 6. HTTP API

The local backend exposes the following API endpoints:

| Endpoint | Purpose |
|---|---|
| `/api/catalog` | Retrieves available sound-source and effect information. |
| `/api/scene` | Handles scene configuration and updates. |
| `/api/render` | Requests audio rendering. |
| `/api/upload` | Handles audio-file uploads. |
| `/api/probe` | Provides information about uploaded audio files. |

The API uses JSON for structured scene and configuration data.

The rendering response also includes metadata headers:

| Header | Purpose |
|---|---|
| `X-Duration` | Provides render-duration information. |
| `X-Render-Seconds` | Reports rendering time. |
| `X-Change` | Provides information about the render or scene change. |

The server uses `ThreadingHTTPServer` and listens on `127.0.0.1`.

## 7. Testing

The project includes a Python test suite covering important DSP, spatial-audio, and backend functionality.

The tests are run from the repository root:

```bash
python src/tests.py
```

The test suite includes checks for:

- Delay-line behavior.
- All-pass filtering.
- One-pole filtering.
- Fractional delay.
- Karplus–Strong plucked-string synthesis.
- Interaural time difference.
- Doppler processing.
- FDN reverberation decay.
- Ping-pong delay.
- Web backend functionality.
- Processing performance.

The tests help verify individual signal-processing components as well as their integration with the application.

## 8. Demonstrations and Example Compositions

The project includes several example renders demonstrating different spatial-audio techniques.

| Render | Demonstration |
|---|---|
| `1_doppler_flyby.wav` | Demonstrates a moving sound source passing the listener and the associated Doppler effect. |
| `2_orbiting_strings.wav` | Demonstrates an orbiting plucked-string source with ping-pong delay in a small room. |
| `3_distant_cathedral.wav` | Demonstrates distant sound positioning, attenuation, and reverberation. |
| `4_composition_sketch.wav` | Demonstrates a composition combining multiple spatial sources and effects. |

These examples provide a practical demonstration of how individual audio-processing features can be combined into larger scenes.

## 9. Design Decisions

### Modular DSP Components

Signal-processing operations are implemented as separate components to make them easier to test, reuse, and combine.

### Separation of Frontend and Backend

The Python backend handles computationally intensive audio processing, while the browser frontend focuses on interaction and visualization.

This separation keeps the interface independent of the underlying DSP implementation.

### Block-Based Processing

Block-based processing is used where appropriate to improve computational efficiency.

The feedback-delay implementation was compared against a sample-by-sample circular-buffer implementation to verify its behavior.

### Configurable Scenes

The application uses configurable sound sources and scene parameters rather than requiring users to modify the underlying Python code for every composition.

This makes the instrument more accessible for experimentation and creative exploration.

## 10. Development and Usage

Install the required dependency:

```bash
pip install pyquist
```

Start the application from the repository root:

```bash
python src/app.py
```

Run tests:

```bash
python src/tests.py
```

Run demonstrations:

```bash
python src/demo.py
```

For additional setup and usage instructions, see [README.md](README.md).

## 11. AI-Assisted Development

AI tools were used as development aids throughout the project.

Their use included assistance with:

- Exploring DSP implementation approaches.
- Debugging and troubleshooting.
- Reviewing code organization.
- Improving documentation and explanations.
- Refining the browser interface.
- Investigating performance and implementation trade-offs.

The resulting implementation was tested and reviewed as part of the development process.

## 12. Project Structure

```text
ECHO/
├── .gitattributes             # Git file-handling configuration.
├── .gitignore                 # Excludes generated and local development files.
├── README.md                  # Project overview and setup instructions.
├── TECHNICAL.md               # Detailed technical documentation.
├── demo.mp4                   # Final project demonstration.
│
└── src/
    ├── app.py                 # Starts the web interface.
    ├── demo.py                # Runs audio demonstrations and compositions.
    ├── tests.py               # Runs project tests.
    │
    ├── echo/
    │   ├── __init__.py        # Initializes the ECHO Python package.
    │   ├── dsp.py             # DSP utilities and audio effects.
    │   ├── engine.py          # Audio processing and rendering engine.
    │   ├── sources.py         # Sound sources and motion trajectories.
    │   ├── spatial.py         # Spatial positioning and binaural processing.
    │   ├── webui.py           # HTTP server and API endpoints.
    │   │
    │   └── web/
    │       ├── index.html     # Web interface structure.
    │       ├── style.css      # Web interface styling.
    │       └── js/
    │           ├── app.js     # Frontend initialization and coordination.
    │           ├── state.js   # Application state management.
    │           ├── controls.js # UI controls and interactions.
    │           ├── scene.js   # Spatial scene visualization.
    │           ├── audio.js   # Audio rendering and playback.
    │           └── setup.js   # Initial setup and configuration.
    │
    └── renders/
        ├── 1_doppler_flyby.wav       # Doppler shift during a moving-source flyby.
        ├── 2_orbiting_strings.wav    # Orbiting spatial audio with plucked strings.
        ├── 3_distant_cathedral.wav   # Distance attenuation and reverberation.
        └── 4_composition_sketch.wav  # Combined spatial audio composition.
```

## 13. References

The project draws on established digital signal-processing and spatial-audio techniques, including:

- Karplus–Strong plucked-string synthesis.
- Schroeder reverberation.
- Feedback delay networks.
- Hadamard feedback matrices.
- Image-source modeling for early reflections.
- Interaural time differences and binaural spatialization.
- Doppler effect and distance-dependent sound propagation.

## 14. Project Sharing

ECHO was developed as a project exploring the intersection of digital signal processing, spatial audio, and interactive creative tools.

The project combines audio-engineering concepts with a browser-based instrument to make spatial sound experimentation more accessible.
