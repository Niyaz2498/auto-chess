import json
import numpy as np
import cv2
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CALIBRATION_FILE, WARP_SIZE


class Calibrator:
    def __init__(self):
        self._matrix: Optional[np.ndarray] = None
        self._load_if_exists()

    # ── Public API ────────────────────────────────────────────────────────────

    def is_calibrated(self) -> bool:
        return self._matrix is not None

    def warp_frame(self, frame: np.ndarray) -> np.ndarray:
        if self._matrix is None:
            raise RuntimeError("Not calibrated yet.")
        return cv2.warpPerspective(frame, self._matrix, (WARP_SIZE, WARP_SIZE))

    def get_square_roi(self, warped: np.ndarray, square: str) -> np.ndarray:
        """Return the cropped image for a square like 'e4'.
        a1 is bottom-left, h8 is top-right (standard orientation).
        """
        col = ord(square[0]) - ord('a')        # 0–7, left to right
        row = int(square[1]) - 1               # 0–7, bottom to top
        sq  = WARP_SIZE // 8
        x   = col * sq
        y   = (7 - row) * sq                   # flip: row 0 = bottom
        return warped[y:y + sq, x:x + sq]

    def draw_grid(self, warped: np.ndarray) -> np.ndarray:
        """Overlay 8×8 grid lines on a warped board image."""
        out = warped.copy()
        sq  = WARP_SIZE // 8
        for i in range(9):
            cv2.line(out, (i * sq, 0), (i * sq, WARP_SIZE), (0, 255, 0), 1)
            cv2.line(out, (0, i * sq), (WARP_SIZE, i * sq), (0, 255, 0), 1)
        return out

    # ── Auto calibration ─────────────────────────────────────────────────────

    def calibrate_auto(self, frame: np.ndarray) -> bool:
        """Try to detect the board from an empty-board frame.
        Returns True on success, False on failure."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        flags = (
            cv2.CALIB_CB_ADAPTIVE_THRESH
            | cv2.CALIB_CB_NORMALIZE_IMAGE
            | cv2.CALIB_CB_FAST_CHECK
        )
        found, corners = cv2.findChessboardCorners(gray, (7, 7), flags)
        if not found:
            return False

        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
        corners   = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
        corners   = corners.reshape(7, 7, 2)

        # Derive the 4 outer board corners from the 49 inner corners.
        # The inner corner grid spans rows 1–7 and cols 1–7 of the 8×8 board.
        # We extrapolate outward by one square-step in each direction.
        tl_inner = corners[0, 0]
        tr_inner = corners[0, 6]
        bl_inner = corners[6, 0]
        br_inner = corners[6, 6]

        step_right = (tr_inner - tl_inner) / 6
        step_down  = (bl_inner - tl_inner) / 6

        outer_tl = tl_inner - step_right - step_down
        outer_tr = tr_inner + step_right - step_down
        outer_br = br_inner + step_right + step_down
        outer_bl = bl_inner - step_right + step_down

        src = np.array([outer_tl, outer_tr, outer_br, outer_bl], dtype=np.float32)
        self._save_and_compute(src)
        return True

    # ── Manual calibration ───────────────────────────────────────────────────

    def calibrate_manual(self, four_points: np.ndarray) -> None:
        """Compute transform from 4 manually clicked outer corners.
        Expected order: top-left, top-right, bottom-right, bottom-left.
        """
        src = np.array(four_points, dtype=np.float32)
        self._save_and_compute(src)

    # ── Internals ────────────────────────────────────────────────────────────

    def _save_and_compute(self, src: np.ndarray) -> None:
        dst = np.array([
            [0, 0],
            [WARP_SIZE, 0],
            [WARP_SIZE, WARP_SIZE],
            [0, WARP_SIZE],
        ], dtype=np.float32)
        self._matrix = cv2.getPerspectiveTransform(src, dst)
        self._persist(src)

    def _persist(self, src: np.ndarray) -> None:
        CALIBRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {"src_points": src.tolist(), "warp_size": WARP_SIZE}
        CALIBRATION_FILE.write_text(json.dumps(data, indent=2))

    def _load_if_exists(self) -> None:
        if not CALIBRATION_FILE.exists():
            return
        data   = json.loads(CALIBRATION_FILE.read_text())
        src    = np.array(data["src_points"], dtype=np.float32)
        dst    = np.array([
            [0, 0],
            [WARP_SIZE, 0],
            [WARP_SIZE, WARP_SIZE],
            [0, WARP_SIZE],
        ], dtype=np.float32)
        self._matrix = cv2.getPerspectiveTransform(src, dst)
