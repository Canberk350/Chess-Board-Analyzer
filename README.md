# Autonomous Chess-Playing Robot

An autonomous system that plays physical chess against a human opponent by combining real-time computer vision, the Stockfish chess engine, and a custom-built 5-DOF robotic arm — using a lightweight **"brain-on-PC"** architecture instead of heavy robotics middleware.

> CENG 483 – Behavioral Robotics · Final Project · Group 10 · Fall 2025
> Izmir Institute of Technology

## Demo

<video src="https://github.com/Canberk350/Chess-Board-Analyzer/raw/main/demo.mp4" controls width="800"></video>

*(If the video doesn't render above, watch it directly: [demo.mp4](https://github.com/Canberk350/Chess-Board-Analyzer/raw/main/demo.mp4))*

## Overview

Most powerful chess engines exist only on a screen — they lack the physical, human-like experience of moving real pieces. This project builds a closed **see → think → act** loop:

1. **See** — A camera watches the board and a computer-vision pipeline works out the current position.
2. **Think** — The position is handed to the Stockfish engine, which returns the best move.
3. **Act** — A 5-DOF robotic arm is meant to physically pick up and place the piece.

The system is split into three modular subsystems: **Perception**, **Control** (game logic / engine), and **Mechanical** (arm + firmware).

## Key Features

### Computer Vision / Perception (`chess_board_analysis.py`)
- **Automatic board calibration** — reuses OpenCV's `findChessboardCorners` checkerboard detector against the physical chessboard's own 7×7 internal grid intersections (an 8×8 chess board *is* a checkerboard pattern), so no manual corner-marking is needed.
- **Perspective transform** — warps the detected board into a fixed-size top-down square grid for per-square analysis.
- **Occupancy detection** — diffs each of the 64 squares against a calibrated empty-board reference frame to determine which squares are occupied.
- **Piece-color classification** — uses brightness/HSV thresholding on each occupied square to distinguish white vs. black pieces from shadows cast by the arm.
- **Motion-aware pausing** — detects when a hand enters the frame and pauses analysis until the scene settles (stability counter + cooldown), preventing false reads mid-move.
- **Legal-move inference** — rather than trying to "solve" an arbitrary board image, it cross-references the *change* in occupancy/color against `python-chess`'s legal move list (including castling and promotion) to robustly determine which move was just played.
- **Live visual debugger** — a rendered 8×8 board overlay compares the engine's internal state against what the camera currently sees (green = match, red = unexpected piece, yellow = missing piece, orange = color mismatch), plus tunable trackbars for diff threshold, min pixel count, color threshold, and contrast.

### Game Logic / Engine Integration
- Built on [`python-chess`](https://python-chess.readthedocs.io/) for board state, legal-move generation, and rules (check, checkmate, stalemate, castling, promotion).
- Move selection delegated to the **Stockfish** engine via UCI (0.5s think time per move).
- Human vs. robot turn handling, with manual turn-swap and promotion-choice controls.

### Kinematics & Motion Control
- Custom Python **inverse kinematics** solver mapping Cartesian `(x, y, z)` targets to joint angles:
  - Base rotation via `atan2(y, x)`.
  - Shoulder/elbow angles via the Law of Cosines over the two arm links.
  - A reachability check (`d < L1 + L2`) that raises a warning instead of stalling the motors when a target is out of range.
- Custom Arduino firmware **`smoothMove`** function that replaces instant servo jumps with linear interpolation (small angular steps + 15 ms delay) to reduce mechanical "jerk," gear stress, and piece slippage on the upright arm.
- **Serial handshake protocol** (115200 baud) — the Python controller sends `PING` and waits for `PONG` from the Arduino to confirm a stable connection before issuing any high-current movement commands.

## Results

| Metric | Result |
|---|---|
| Board corner / perspective registration | **100%** success across lighting conditions |
| Piece occupancy detection accuracy | **92%** (primary error source: dynamic shadowing from the arm) |

## Project Status

| Subsystem | Status |
|---|---|
| Computer vision & board-state tracking | ✅ Fully functional |
| Move detection & validation | ✅ Fully functional |
| Chess engine integration (Stockfish) | ✅ Fully functional |
| Inverse kinematics solver | ✅ Implemented, unit-tested |
| Motion smoothing firmware | ✅ Implemented |
| Autonomous physical piece movement | ⚠️ Not achieved — see below |

**Hardware failure:** during integration testing, simultaneously actuating two primary servos drew more current than the power socket was rated for, causing a thermal fault that burned out the base and shoulder servos. The project was relocated to a supervised lab with strict safety limits (operation only during supervised hours, no simultaneous high-load actuation), which prevented a full end-to-end "robot physically plays a game" demonstration.

As a result, the project scope was adjusted to prioritize and validate the perception and decision-making pipeline, while the robotic arm remains hardware-assembled with working serial communication but incomplete IK calibration for live gameplay.

## Tech Stack

| | |
|---|---|
| **Language** | Python 3.8+, C++ (Arduino firmware) |
| **Computer Vision** | OpenCV |
| **Chess Logic** | [`python-chess`](https://python-chess.readthedocs.io/), Stockfish engine |
| **Math / Arrays** | NumPy |
| **Arm ↔ PC Communication** | PySerial, custom PING/PONG handshake @ 115200 baud |
| **Microcontroller** | Arduino Mega 2560 |
| **Manipulator** | 5-DOF robotic arm, servo motors |
| **Vision Sensor** | IP / mobile phone camera |
| **Power** | Digital laboratory power supply |
| **Tools** | VS Code, Arduino IDE |

## Repository Structure

```
.
├── chess_board_analysis.py       # Perception pipeline + game logic (main script)
├── demo.mp4                      # Project demonstration video
├── G10_CENG483_FinalReport.pdf   # Final written report
├── G10_CENG483_FinalPresentation.pptx  # Final presentation slides
└── README.md
```

## Getting Started

### Requirements
- Python 3.8+
- [Stockfish](https://stockfishchess.org/download/) installed and available on your `PATH` (or at `/usr/games/stockfish` on Ubuntu)
- Python packages:
  ```bash
  pip install opencv-python numpy python-chess pyserial
  ```
- A webcam or IP camera pointed at a physical chess board

### Running the vision + game-logic demo

```bash
python chess_board_analysis.py
```

1. Enter which color the robot is playing (`w`/`b`) when prompted.
2. With the board **empty**, press **`c`** to calibrate — the app auto-detects the board's corners and warps the view to a top-down grid.
3. Set up the starting position on the physical board, then press **`s`** to start the game.
4. Play normally — moves are detected automatically once the scene settles after each move.

**Controls (during a game):**

| Key | Action |
|---|---|
| `c` | Calibrate board corners (before game start) |
| `s` | Start / restart the game after setup |
| `r` | Reset (return to setup state) |
| `u` | Recapture the empty-board lighting reference (use if lighting changes) |
| `t` | Manually swap whose turn it is |
| `q`, `r`, `b`, `n` | Choose promotion piece when prompted |
| `q` (main loop) | Quit |

Four windows are shown while running: **Main** (live camera + overlays), **Settings** (tunable detection thresholds), **Logic Debug** (engine state vs. camera-perceived state), and **Analysis** (raw occupancy threshold mask).

> Note: the `url` variable near the top of the script defaults to `0` (local webcam) for testing — set it to your IP camera stream URL for the original deployment setup.

## Team — Group 10

| Name | Student ID | Role |
|---|---|---|
| Canberk Yılmaz | 300201027 | Robotic Vision, System Architecture |
| Vagif Aliyev | 300201131 | Research, Integration |
| Kaan Cesur | 290201066 | Research, Inverse Kinematics |
| Emir Efe Ulusoy | 300201103 | Mechanical Design, Motion Control |

## Future Work

- Industrial-grade power distribution / current protection to safely enable simultaneous multi-servo actuation.
- Complete inverse-kinematics calibration for reliable pick-and-place.
- Full autonomous "Full Game Loop" demonstration end-to-end.

## Documents

- 📄 [Final Report](G10_CENG483_FinalReport.pdf)
- 📊 [Final Presentation](G10_CENG483_FinalPresentation.pptx)
- 🎥 [Demo Video](demo.mp4)
