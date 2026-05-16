import cv2
import numpy as np
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DIFF_THRESHOLD, BLUR_KERNEL_SIZE, SQUARE_PADDING, WARP_SIZE

SQUARE_SIZE = WARP_SIZE // 8


class BoardDetector:
    def __init__(self):
        self._baseline: Optional[np.ndarray] = None  # warped frame at last confirm_position
        self.threshold: float = float(DIFF_THRESHOLD)  # kept for heatmap debug only
        self.flip_rows: bool = False   # flip rank axis (camera sees board upside-down vertically)
        self.flip_cols: bool = False   # flip file axis (camera sees board mirrored horizontally)

    # ── Baseline management ───────────────────────────────────────────────────

    def confirm_position(self, warped: np.ndarray) -> None:
        """Save current warped frame as the baseline."""
        self._baseline = warped.copy()

    def has_baseline(self) -> bool:
        return self._baseline is not None

    def get_baseline_squares(self) -> set:
        """Return which squares are blue in the stored baseline (uses current threshold)."""
        if self._baseline is None:
            return set()
        return set(self.detect_blue_squares(self._baseline))

    # ── Move detection ────────────────────────────────────────────────────────

    def detect_changed_squares(self, current_warped: np.ndarray) -> list[str]:
        """Return squares whose blue-sticker state changed since last confirm.

        Baseline squares are recomputed on each call using current thresholds,
        so slider adjustments take effect without re-snapping the baseline.

        Capture fallback: when a piece takes an opponent piece (same sticker
        colour), the destination looks blue before AND after — invisible to the
        symmetric-difference. We detect this case (sticker count dropped by 1,
        only 1 square in the diff) and use pixel diff to locate the destination.
        """
        if self._baseline is None:
            raise RuntimeError("No baseline set — call confirm_position first.")
        baseline_sq = set(self.detect_blue_squares(self._baseline))
        current_sq  = set(self.detect_blue_squares(current_warped))
        changed     = list(baseline_sq.symmetric_difference(current_sq))

        if len(changed) == 1 and len(current_sq) < len(baseline_sq):
            # Origin detected via stickers; destination missed because opponent
            # piece was already blue there. Use diff to find it.
            dest = self._find_capture_dest(current_warped, exclude=set(changed))
            if dest:
                changed.append(dest)

        return changed

    def _find_capture_dest(self, current_warped: np.ndarray, exclude: set) -> Optional[str]:
        """Return the highest-diff square outside `exclude` — the capture destination."""
        diff_map   = self._compute_diff_map(current_warped)
        best_sq    = None
        best_score = 0.0
        for row in range(8):
            for col in range(8):
                sq    = _coords_to_square(row, col, self.flip_rows, self.flip_cols)
                score = float(diff_map[row, col])
                if sq not in exclude and score > best_score:
                    best_score = score
                    best_sq    = sq
        # Require at least half the diff threshold to avoid noise
        return best_sq if best_score >= self.threshold * 0.5 else None

    def compute_heatmap(self, current_warped: np.ndarray) -> np.ndarray:
        """Return an 800×800 BGR heatmap image (green=low diff, red=high diff)."""
        if self._baseline is None:
            return np.zeros((WARP_SIZE, WARP_SIZE, 3), dtype=np.uint8)

        diff_map = self._compute_diff_map(current_warped)
        heatmap  = np.zeros((WARP_SIZE, WARP_SIZE, 3), dtype=np.uint8)

        for row in range(8):
            for col in range(8):
                score  = float(diff_map[row, col])
                # Normalise to 0–255 for colour; cap at 3× threshold for saturation
                ratio  = min(score / (self.threshold * 3), 1.0)
                r      = int(255 * ratio)
                g      = int(255 * (1.0 - ratio))
                y1     = row * SQUARE_SIZE
                x1     = col * SQUARE_SIZE
                heatmap[y1:y1 + SQUARE_SIZE, x1:x1 + SQUARE_SIZE] = (0, g, r)

                # Label score
                cv2.putText(
                    heatmap,
                    f"{score:.0f}",
                    (x1 + 5, y1 + SQUARE_SIZE // 2),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )
        return heatmap

    # ── Colour marker detection ───────────────────────────────────────────────

    # Blue marker HSV range (all pieces)
    blue_h_lo: int       = 90
    blue_h_hi: int       = 130
    blue_s_lo: int       = 80
    blue_min_pixels: int = 30

    def detect_blue_squares(self, warped: np.ndarray) -> list[str]:
        cmap = self._compute_color_map(warped, self.blue_h_lo, self.blue_h_hi, self.blue_s_lo)
        return [
            _coords_to_square(row, col, self.flip_rows, self.flip_cols)
            for row in range(8) for col in range(8)
            if cmap[row, col] >= self.blue_min_pixels
        ]

    def render_color_debug(self, warped: np.ndarray) -> np.ndarray:
        """Overlay showing blue pixel count per square."""
        blue_map = self._compute_color_map(warped, self.blue_h_lo, self.blue_h_hi, self.blue_s_lo)
        out = warped.copy()

        for row in range(8):
            for col in range(8):
                cnt   = int(blue_map[row, col])
                has   = cnt >= self.blue_min_pixels
                y1, x1 = row * SQUARE_SIZE, col * SQUARE_SIZE

                roi     = out[y1:y1 + SQUARE_SIZE, x1:x1 + SQUARE_SIZE]
                overlay = roi.copy()
                tint    = (180, 120, 0) if has else (0, 0, 60)
                cv2.rectangle(out, (x1, y1), (x1 + SQUARE_SIZE - 1, y1 + SQUARE_SIZE - 1), tint, -1)
                cv2.addWeighted(overlay, 0.45, roi, 0.55, 0, roi)

                sq = _coords_to_square(row, col, self.flip_rows, self.flip_cols)
                cv2.putText(out, sq,          (x1 + 4, y1 + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
                cv2.putText(out, f"{cnt}px",  (x1 + 4, y1 + 44), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (150, 220, 255), 1, cv2.LINE_AA)

                if has:
                    cv2.rectangle(out, (x1+2, y1+2), (x1+SQUARE_SIZE-2, y1+SQUARE_SIZE-2), (255, 200, 0), 3)

        for i in range(9):
            cv2.line(out, (i * SQUARE_SIZE, 0), (i * SQUARE_SIZE, WARP_SIZE), (180, 180, 180), 1)
            cv2.line(out, (0, i * SQUARE_SIZE), (WARP_SIZE, i * SQUARE_SIZE), (180, 180, 180), 1)
        return out

    def _compute_color_map(self, warped: np.ndarray, h_lo: int, h_hi: int, s_lo: int) -> np.ndarray:
        hsv  = cv2.cvtColor(warped, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([h_lo, s_lo, 40]), np.array([h_hi, 255, 255]))
        cmap = np.zeros((8, 8), dtype=np.float32)
        for row in range(8):
            for col in range(8):
                cmap[row, col] = float(np.count_nonzero(_crop_square_raw(mask, row, col)))
        return cmap

    # ── Internal ──────────────────────────────────────────────────────────────

    def _compute_diff_map(self, current: np.ndarray) -> np.ndarray:
        diff_map = np.zeros((8, 8), dtype=np.float32)
        for row in range(8):
            for col in range(8):
                sq_cur  = _crop_square(current,        row, col)
                sq_base = _crop_square(self._baseline, row, col)
                diff_map[row, col] = _square_diff(sq_cur, sq_base)
        return diff_map


# ── Helpers ───────────────────────────────────────────────────────────────────

def _crop_square_raw(img: np.ndarray, row: int, col: int) -> np.ndarray:
    """Crop without padding — used for colour pixel counting."""
    x1 = col * SQUARE_SIZE
    y1 = row * SQUARE_SIZE
    return img[y1:y1 + SQUARE_SIZE, x1:x1 + SQUARE_SIZE]


def _crop_square(warped: np.ndarray, row: int, col: int) -> np.ndarray:
    x1 = col * SQUARE_SIZE + SQUARE_PADDING
    y1 = row * SQUARE_SIZE + SQUARE_PADDING
    x2 = x1 + SQUARE_SIZE - 2 * SQUARE_PADDING
    y2 = y1 + SQUARE_SIZE - 2 * SQUARE_PADDING
    return warped[y1:y2, x1:x2]


def _square_diff(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape or a.size == 0:
        return 0.0
    gray_a = cv2.GaussianBlur(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), (BLUR_KERNEL_SIZE, BLUR_KERNEL_SIZE), 0)
    gray_b = cv2.GaussianBlur(cv2.cvtColor(b, cv2.COLOR_BGR2GRAY), (BLUR_KERNEL_SIZE, BLUR_KERNEL_SIZE), 0)
    return float(np.mean(np.abs(gray_a.astype(np.int16) - gray_b.astype(np.int16))))


def _coords_to_square(row: int, col: int, flip_rows: bool = False, flip_cols: bool = False) -> str:
    r = (7 - row) if flip_rows else row
    c = (7 - col) if flip_cols else col
    file_char = chr(ord('a') + c)
    rank_char  = str(8 - r)
    return file_char + rank_char
