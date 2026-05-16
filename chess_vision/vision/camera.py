import cv2
import numpy as np
import threading
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CAMERA_SOURCE, FRAME_WIDTH, FRAME_HEIGHT

_is_http = isinstance(CAMERA_SOURCE, str) and CAMERA_SOURCE.startswith("http")


class Camera:
    def __init__(self):
        self._cap:   cv2.VideoCapture | None = None
        self._frame: np.ndarray | None       = None
        self._lock   = threading.Lock()
        self._stop   = threading.Event()
        self._thread: threading.Thread | None = None

    def open(self) -> bool:
        self._cap = cv2.VideoCapture(CAMERA_SOURCE)
        if not self._cap.isOpened():
            return False
        if not _is_http:
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  FRAME_WIDTH)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        # Background thread drains the stream buffer continuously
        self._stop.clear()
        self._thread = threading.Thread(target=self._drain_loop, daemon=True)
        self._thread.start()
        return True

    def read_frame(self, flush: bool = False) -> np.ndarray | None:
        """Return the most recent frame. Always fresh — no buffer lag."""
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    def release(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def _drain_loop(self) -> None:
        while not self._stop.is_set():
            if self._cap is None or not self._cap.isOpened():
                break
            ok, frame = self._cap.read()
            if ok:
                with self._lock:
                    self._frame = frame
