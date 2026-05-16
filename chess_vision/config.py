from pathlib import Path

# Camera
# Set CAMERA_SOURCE to an integer (local webcam index) or a URL string.
#
# Android phone options:
#   IP Webcam app  → "http://192.168.x.x:8080/video"   (MJPEG stream)
#   DroidCam app   → "http://192.168.x.x:4747/video"
#
# Replace 192.168.x.x with your phone's IP (shown in the app).
# Both phone and Mac must be on the same WiFi network.
CAMERA_SOURCE: int | str = "http://192.168.1.14:4747/video"

FRAME_WIDTH  = 1920
FRAME_HEIGHT = 1080

# Board detection
DIFF_THRESHOLD   = 12   # Adjust via debug heatmap. Lower = more sensitive.
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
