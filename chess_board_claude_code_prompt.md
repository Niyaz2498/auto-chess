# Claude Code Prompt — CV-Based Physical Chess Board (Match Mode)

---

## Context & Background

I am building a **computer vision based physical chess board system** for FIDE preparation.
The goal is to play a full game against Stockfish on a real physical chess board, while a Python
application running on my MacBook tracks my moves via a mounted camera and displays the engine's
response on screen.

**Why this exists:** Playing on a physical board trains better spatial thinking for OTB
(over-the-board) tournament play. I want engine-level opposition without staring at a digital
chess interface.

---

## Hardware

- **MacBook** (primary development and runtime machine)
- **Camera:** External USB webcam (1080p), mounted ~70cm above the board on a gooseneck arm
- **Board:** Standard vinyl rollup chess mat — green and cream squares, high contrast,
  clear outer border, algebraic notation (a–h, 1–8) printed on the border.
  The board sits on a plain white tile floor.
- **Pieces:** Standard Staunton chess set. No magnets, no modifications to pieces or board.
- **No markers of any kind on the board.** No ArUco stickers, no coloured paper.
  The board's own checkered pattern is used for detection.

---

## Scope — Match Mode Only

Build **one mode only**: playing a full game against Stockfish on the physical board.
Do not build puzzle mode, opening trainer, or any other mode. Keep the codebase focused.

---

## How the System Works

### Board Calibration — No Markers

The board is detected automatically using its own checkered pattern.

**Primary method — `cv2.findChessboardCorners()`:**
- On an empty board (before pieces are placed), capture one frame.
- Run `cv2.findChessboardCorners()` to detect the inner corners of the 8×8 grid.
- Use inner corners (7×7 = 49 points for an 8×8 board).
- Use `cv2.cornerSubPix()` for sub-pixel accuracy.
- From the 49 inner corners, compute the 4 outer board corners mathematically.
- Use `cv2.getPerspectiveTransform()` to produce a perfect top-down 800×800px board image.
- Save the transform to disk so it persists across sessions (no recalibration each run).

**Fallback method — manual corner click:**
- If automatic detection fails (poor lighting, board too crumpled), show the live camera feed.
- Prompt the user to click the 4 outer corners of the board in order:
  top-left → top-right → bottom-right → bottom-left.
- Compute the perspective transform from those 4 clicked points.
- Save to disk.

Both methods produce the same output: a perspective transform matrix saved to
`calibration/calibration_data.json`. Load on startup if it exists — skip calibration.

After calibration, overlay the 8×8 grid on the live feed so the user can verify
every square aligns correctly before playing.

### Move Detection — Button Press Comparison

- The camera does **not** process video continuously.
- Player makes a move on the physical board, removes hand completely, then presses
  the **"My Move"** button in the UI.
- App captures a new frame, warps it, and compares it against the previously stored frame.
- For each of the 64 squares: grayscale → Gaussian blur → trim edge padding → mean absolute diff.
- Squares with diff score above `DIFF_THRESHOLD` = changed squares.
- Changed squares determine the move. `python-chess` already knows the full game state
  from move 1, so it resolves which piece moved where without needing visual piece recognition.

**Edge cases:**
- 2 changed squares → normal move
- 3 changed squares → en passant
- 4 changed squares → castling
- 1 or 0 changed squares → no valid move detected, notify user to re-press
- Pawn reaches back rank → show promotion dialog (Q / R / B / N)

### Engine Response

- After detecting the player's move, Stockfish calculates its reply at the configured level.
- The engine's move is shown on the **digital board on screen** with highlighted from/to squares.
- Player makes that move on the physical board, presses **"Confirm Engine Move"** button.
- App captures the new board state as the new baseline for the next comparison.
- Cycle continues until checkmate, stalemate, or resignation.

---

## Stockfish Skill Levels — 1 to 10

Implement a 10-level difficulty system mapping to approximate ELO ratings.
Use Stockfish's `UCI_LimitStrength` and `UCI_Elo` options for levels 1–9,
and full strength (no ELO cap) for level 10.

| Level | Label             | Approx ELO | Stockfish config                         |
|-------|-------------------|------------|------------------------------------------|
| 1     | Complete Beginner | ~800       | UCI_LimitStrength=true, UCI_Elo=800      |
| 2     | Beginner          | ~1000      | UCI_LimitStrength=true, UCI_Elo=1000     |
| 3     | Casual            | ~1200      | UCI_LimitStrength=true, UCI_Elo=1200     |
| 4     | Club Player       | ~1400      | UCI_LimitStrength=true, UCI_Elo=1400     |
| 5     | Intermediate      | ~1600      | UCI_LimitStrength=true, UCI_Elo=1600     |
| 6     | Strong Club       | ~1800      | UCI_LimitStrength=true, UCI_Elo=1800     |
| 7     | Expert            | ~2000      | UCI_LimitStrength=true, UCI_Elo=2000     |
| 8     | Candidate Master  | ~2200      | UCI_LimitStrength=true, UCI_Elo=2200     |
| 9     | Master            | ~2500      | UCI_LimitStrength=true, UCI_Elo=2500     |
| 10    | Maximum Strength  | 3000+      | UCI_LimitStrength=false (no cap)         |

Apply level via `engine.configure()` before each game.
Level selector is visible in the UI, changeable between games but not mid-game.
Display the label and approximate ELO next to the selector at all times.

---

## Project Structure

```
chess_vision/
├── main.py
├── config.py
├── calibration/
│   ├── __init__.py
│   ├── calibrator.py              # Auto (findChessboardCorners) + manual click fallback
│   └── calibration_data.json      # Auto-generated on first calibration
├── vision/
│   ├── __init__.py
│   ├── camera.py                  # Camera capture, frame management
│   └── board_detector.py          # Image diff, changed square detection
├── engine/
│   ├── __init__.py
│   ├── stockfish_bridge.py        # Stockfish process, level 1-10, move calculation
│   └── game_manager.py            # python-chess board state, move validation, PGN
├── ui/
│   ├── __init__.py
│   ├── main_window.py             # Main PyQt5 window
│   ├── board_widget.py            # Digital board with move highlighting
│   └── camera_widget.py           # Live camera feed with grid overlay
├── games/                         # PGN files saved here after each game
└── requirements.txt
```

---

## Module Specifications

### `calibration/calibrator.py`

1. **Auto detection:** `cv2.findChessboardCorners(frame, (7,7))` on a grayscale empty-board frame.
   Refine with `cv2.cornerSubPix()`. Derive the 4 outer corners from the 49 inner corners.
2. **Perspective transform:** `cv2.getPerspectiveTransform()` → warp to 800×800px
   (100px per square). Square a1 at bottom-left, h8 at top-right (standard orientation).
3. **Persist:** Save transform matrix and source corners as JSON. Load on startup if present.
4. **Manual fallback:** Show camera feed in a Qt widget. On 4 mouse clicks (in corner order),
   compute transform from those points. Save identically to auto method.
5. **Grid overlay:** Draw the 8×8 grid on the warped image after calibration for verification.
6. **Expose:**
   - `warp_frame(frame)` → 800×800 warped board image
   - `get_square_roi(warped, square)` → cropped square image (e.g. `"e4"`)
   - `is_calibrated()` → bool

### `vision/board_detector.py`

1. Stores the previous warped board image after each confirmed move.
2. On button press: warp current frame, compare all 64 squares against previous.
3. Per-square pipeline: grayscale → Gaussian blur (BLUR_KERNEL_SIZE) →
   trim SQUARE_PADDING pixels from all edges → mean absolute difference.
4. Return changed squares (those above DIFF_THRESHOLD).
5. **Debug heatmap:** Render diff scores as an 8×8 colour grid (low=green, high=red).
   Toggle on/off in the UI. Critical for threshold tuning.
6. `confirm_position(warped)` — saves current frame as new baseline.

### `engine/game_manager.py`

1. Wraps `chess.Board()`.
2. `resolve_move(changed_squares)` — converts changed square list to a `chess.Move`
   using the known board state. Returns the move or raises a clear exception if illegal.
3. `push_move(move)` — applies move to board.
4. `needs_promotion(from_sq, to_sq)` → bool — returns True if a pawn reaches the back rank.
5. `get_legal_moves()`, `get_fen()`, `is_game_over()`, `get_result()`, `get_pgn()`, `reset()`.

### `engine/stockfish_bridge.py`

1. On init, find Stockfish binary by checking paths in order (see config.py).
   If none found, raise a clear error with brew install instruction.
2. `set_level(level: int)` — applies the level config from the table above via
   `engine.configure({"UCI_LimitStrength": ..., "UCI_Elo": ...})`.
3. `get_best_move(fen)` → `chess.Move`, using ENGINE_THINK_TIME_MS as time limit.
4. Clean shutdown on app exit.

### `ui/main_window.py`

**Left panel — camera:**
- Live camera preview with 8×8 grid overlay (updates at ~15fps, not real-time render)
- Large **"My Move ✓"** button — always visible, primary interaction
- **"Confirm Engine Move ✓"** button — visible only after engine has responded
- **"Recalibrate"** button
- Debug heatmap toggle checkbox

**Right panel — game:**
- Digital chess board (chess.svg rendered in QSvgWidget or equivalent)
  Engine move: green = from square, blue = to square
- Scrollable move history in algebraic notation
- Status bar: turn indicator, check/checkmate/stalemate/draw, move number

**Top bar:**
- Level selector (QSlider or QComboBox, 1–10) with label and ELO displayed
- Colour selector: White / Black
- New Game button
- Resign button
- Save PGN button

### `ui/board_widget.py`

1. Render with `chess.svg.board()`, display in Qt SVG widget.
2. Highlight last player move (one colour) and engine move (another colour).
3. Flash red briefly on illegal move.
4. Auto-update after every state change.

---

## `config.py`

```python
from pathlib import Path

# Camera
CAMERA_INDEX = 0
FRAME_WIDTH  = 1920
FRAME_HEIGHT = 1080

# Board detection
DIFF_THRESHOLD   = 30   # Adjust via debug heatmap. Lower = more sensitive.
BLUR_KERNEL_SIZE = 5
SQUARE_PADDING   = 6    # Pixels trimmed from each edge before diffing
WARP_SIZE        = 800  # Total board size in pixels (100px per square)

# Stockfish — macOS paths checked in order
STOCKFISH_PATHS = [
    "/opt/homebrew/bin/stockfish",  # Apple Silicon
    "/usr/local/bin/stockfish",     # Intel Mac
]

# Engine
DEFAULT_LEVEL        = 5
ENGINE_THINK_TIME_MS = 1500

# Paths
BASE_DIR           = Path(__file__).parent
CALIBRATION_FILE   = BASE_DIR / "calibration" / "calibration_data.json"
GAMES_DIR          = BASE_DIR / "games"

# Level → ELO config
LEVEL_CONFIG = {
    1:  {"label": "Complete Beginner", "elo": 800,  "limit": True},
    2:  {"label": "Beginner",          "elo": 1000, "limit": True},
    3:  {"label": "Casual",            "elo": 1200, "limit": True},
    4:  {"label": "Club Player",       "elo": 1400, "limit": True},
    5:  {"label": "Intermediate",      "elo": 1600, "limit": True},
    6:  {"label": "Strong Club",       "elo": 1800, "limit": True},
    7:  {"label": "Expert",            "elo": 2000, "limit": True},
    8:  {"label": "Candidate Master",  "elo": 2200, "limit": True},
    9:  {"label": "Master",            "elo": 2500, "limit": True},
    10: {"label": "Maximum Strength",  "elo": None, "limit": False},
}
```

---

## `requirements.txt`

```
opencv-contrib-python>=4.8.0
python-chess>=1.10.0
PyQt5>=5.15.0
numpy>=1.24.0
Pillow>=10.0.0
stockfish>=3.28.0
```

---

## Setup Instructions (README)

```
1. brew install python stockfish
2. pip install -r requirements.txt
3. Mount camera ~70cm above the empty board, centred, full board visible
4. python main.py
5. Click "Calibrate" → auto detection runs on empty board
   If it fails, follow the manual corner-click prompt
6. Verify the 8×8 grid overlay aligns with every square
7. Select level and colour → New Game
```

---

## Implementation Notes

- **macOS only.** No Windows paths or fallbacks needed.
- **No continuous video.** All CV triggered by button press only.
- **Threshold tuning.** The debug heatmap must be easily accessible from the main UI.
  On first run, show a tip: *"Open the heatmap and make a test move to verify detection
  before playing a real game."*
- **Lighting warning.** After calibration, compute mean brightness of the warped board.
  If outside 60–210, show a persistent banner: *"Lighting may affect detection — adjust lamp."*
- **Initial position.** On New Game, show the starting FEN on the digital board and prompt:
  *"Set up your physical board to match, then press Ready."* Do not visually verify.
- **Promotion.** When a pawn reaches the back rank, show a modal dialog with Q / R / B / N
  buttons. Do not send the move to the engine until the user selects a piece.
- **PGN auto-save.** At game end, always save PGN to `games/game_YYYYMMDD_HHMMSS.pgn`
  automatically. Also offer a Save button for manual saves mid-game.
- **Use `pathlib.Path`** for all file operations.

---

## Build Order

1. `calibration/calibrator.py` — verify grid aligns on your board
2. `vision/board_detector.py` — test diff with manual moves, tune threshold via heatmap
3. `engine/stockfish_bridge.py` — verify all 10 levels respond correctly
4. `engine/game_manager.py` — verify move validation and game state
5. `ui/` — wire into main window
6. End-to-end: play a full game from start to checkmate

---

## Success Criteria

- [ ] Auto calibration detects the board on an empty board without any markers
- [ ] Manual calibration fallback works if auto fails
- [ ] 8×8 grid overlay aligns with physical board squares
- [ ] Normal move (e2→e4) detected correctly after button press
- [ ] Castling (4 changed squares) detected correctly
- [ ] En passant (3 changed squares) detected correctly
- [ ] Promotion dialog appears when pawn reaches back rank
- [ ] Illegal moves rejected with clear message and red flash on digital board
- [ ] All 10 levels produce noticeably different playing strength
- [ ] Level 1 is beatable by a casual player; Level 10 is near-unbeatable
- [ ] Full game playable from start to checkmate
- [ ] PGN auto-saved at game end
- [ ] Stockfish not found → clear error with brew install instruction
