# CV Chess — Physical Board Match Mode

A desktop app that watches your physical chess board through a camera, detects your moves, and plays back using the Stockfish engine. You make a move on the real board, press Space, and the engine responds — spoken aloud in NATO phonetics via macOS TTS.

> **Note:** This project was built with significant help from [Claude](https://claude.ai) (Anthropic's AI). I directed the design, debugged the vision pipeline, and shaped the UX, but Claude wrote most of the code. I'm being upfront about this so you know what you're looking at.

---

## How It Works

1. **Camera → Warp** — A webcam or phone camera (DroidCam / IP Webcam) streams video. A perspective transform flattens the board into an 800×800px top-down view.
2. **Blue sticker detection** — Each chess piece has a small blue sticker on top. The detector counts blue HSV pixels per square to know which squares are occupied.
3. **Move detection** — When you press Space after moving, the app computes the symmetric difference between the current sticker layout and the baseline, resolving which squares changed to infer the move.
4. **Stockfish** — The move is validated and pushed to a `python-chess` board. Stockfish replies with a move at the configured ELO level.
5. **Voice announcement** — The engine's move is read aloud via macOS `say`, using NATO phonetics for square names (e.g. `Nd6` → *"Knight delta d6"*).

Special moves are handled automatically: **castling** (4 squares changed), **en passant** (3 squares), **captures of blue pieces** (pixel-diff fallback), and **pawn promotion** (popup dialog).

---

## Vision Pipeline

- **Calibration** — `cv2.findChessboardCorners` detects the 49 inner corners of the board, refines them to sub-pixel accuracy, then extrapolates the 4 outer corners. `getPerspectiveTransform` builds a homography matrix that `warpPerspective` applies to every frame, producing a flat 800×800px top-down view.

- **Piece detection** — Each piece carries a blue sticker. After warping, the frame is converted to HSV and `cv2.inRange` isolates blue pixels (`H: 90–130`, `S ≥ 80`). The 800×800 image divides evenly into 64 tiles of 100×100px; a square is "occupied" if ≥ 30 blue pixels fall in its tile. HSV is used instead of RGB because it separates color from brightness, making detection more robust to lighting changes.

- **Move detection** — On each move, the app diffs the current sticker layout against a saved baseline via symmetric difference. The 1–2 squares that changed identify the from/to squares. Captures (destination already blue before the move) fall back to a per-square pixel-intensity diff to locate the destination.

---

## Features

| Feature | Detail |
|---|---|
| Auto calibration | Detects the 7×7 inner-corner grid and extrapolates the outer board corners |
| Manual calibration | Click the 4 outer corners in order; saved to `calibration/calibration_data.json` |
| 10 difficulty levels | ELO 800 (Complete Beginner) → unrestricted Stockfish (Maximum Strength) |
| Heatmap debug | Visualises per-square pixel diff to tune the detection threshold |
| Color debug | Shows HSV blue-pixel counts per square; sliders for H-lo, H-hi, S-lo, min-pixels |
| Flip Ranks / Flip Files | Corrects for cameras mounted on the wrong side or mirrored |
| PGN auto-save | Every game is written to `games/game_YYYYMMDD_HHMMSS.pgn` on completion |
| macOS TTS | All English system voices available; previewed with a sample phrase |
| Keyboard shortcut | `Space` = My Move / Confirm Engine Move |

---

## Tech Stack

- **Python 3.12+**
- **OpenCV** (`opencv-contrib-python`) — camera capture, perspective warp, HSV masking, pixel diff
- **PyQt5** — UI, camera timer loop, SVG board widget
- **python-chess** — board state, legal move validation, PGN export
- **Stockfish** — chess engine (via UCI protocol)
- **macOS `say`** — text-to-speech for engine move announcements

---

## Setup

### 1. Install Stockfish

```bash
brew install stockfish
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure the camera

Edit [config.py](config.py):

```python
# Local webcam
CAMERA_SOURCE = 0

# Android phone via DroidCam
CAMERA_SOURCE = "http://192.168.x.x:4747/video"

# Android phone via IP Webcam
CAMERA_SOURCE = "http://192.168.x.x:8080/video"
```

Both phone and Mac must be on the same WiFi network.

### 4. Run

```bash
python main.py
```

---

## Calibration

The board must be calibrated before playing so the app knows where each square is.

**Auto calibrate** — Point the camera at a clean starting position and press *Auto Calibrate*. OpenCV's chessboard corner detector finds the 7×7 inner grid and extrapolates the four outer corners. Works best with good, even lighting.

**Manual calibrate** — Press *Manual Calibrate* and click the four outer corners of the board in order: `a8` (top-left) → `h8` (top-right) → `h1` (bottom-right) → `a1` (bottom-left). Assumes White is at the bottom of the camera view.

Calibration persists across sessions in `calibration/calibration_data.json`.

---

## Playing a Game

1. Calibrate the camera.
2. Affix a small blue sticker to the top of each piece (all pieces use the same colour; the app tracks position, not identity).
3. Select difficulty level and colour, then press **New Game**.
4. Set up your physical board to the starting position and press OK.
5. Make a move on the physical board.
6. Press **Space** (or the *My Move* button) — the app detects the changed squares, validates the move, updates the digital board, and asks Stockfish to reply.
7. The engine's move is announced aloud and highlighted on the digital board. Make the physical move, then press **Space** again to confirm.
8. Repeat.

### Useful controls during a game

| Control | Action |
|---|---|
| `Space` | My Move / Confirm Engine Move |
| *Set Baseline* | Re-snap the baseline after accidentally touching a piece |
| *Show Heatmap* | Diff visualisation — tune the threshold spinner until idle squares are green |
| *Color Debug* | Blue-pixel overlay — adjust HSV sliders until occupied squares light up cleanly |
| *Flip Ranks / Flip Files* | Fix orientation if the camera sees the board mirrored |

---

## Project Structure

```
chess_vision/
├── main.py                  # Entry point, dark-mode PyQt5 app
├── config.py                # Camera source, Stockfish paths, ELO levels, tuning constants
├── requirements.txt
├── calibration/
│   ├── calibrator.py        # Perspective transform; auto and manual corner detection
│   └── calibration_data.json
├── vision/
│   ├── camera.py            # OpenCV capture wrapper
│   └── board_detector.py    # Blue-sticker detection, pixel diff, heatmap, move resolution
├── engine/
│   ├── stockfish_bridge.py  # UCI wrapper; ELO limiting via UCI_LimitStrength
│   └── game_manager.py      # python-chess board, move validation, PGN export
├── ui/
│   ├── main_window.py       # Main window, camera loop, game flow, TTS
│   ├── board_widget.py      # SVG digital board with move highlights
│   └── camera_widget.py     # Live camera feed, manual calibration click handler
└── games/                   # Auto-saved PGN files
```

---

## Known Limitations

- **macOS only** — TTS uses `say`; the `afplay` sound effects also rely on macOS. The vision and engine logic is platform-agnostic, but the UI integration is not.
- **Lighting sensitivity** — Inconsistent or flickering light causes false positives. The lighting warning banner appears when average board brightness is outside 60–210. A steady lamp pointed at the board helps significantly.
- **Blue stickers required** — The detector relies on HSV colour rather than piece recognition, so all pieces need a sticker. Use the Color Debug overlay to verify your sticker colour falls within the tuned HSV range.
- **Camera orientation** — If ranks or files appear mirrored, toggle *Flip Ranks* / *Flip Files*. The auto-calibrator assumes the camera is roughly overhead; extreme angles degrade corner detection.
