import cv2
import numpy as np
from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap


class CameraWidget(QLabel):
    """Displays a live camera frame. Emits clicked_points during manual calibration."""

    corner_clicked = pyqtSignal(float, float)   # (x, y) in original frame coords

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(480, 270)
        self.setStyleSheet("background: #1a1a1a;")
        self._accepting_clicks   = False
        self._click_count        = 0
        self._scale_x            = 1.0
        self._scale_y            = 1.0
        self._frame_w            = 1
        self._frame_h            = 1

    def display_frame(self, frame: np.ndarray) -> None:
        rgb   = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w  = rgb.shape[:2]
        self._frame_w = w
        self._frame_h = h
        qimg  = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
        pm    = QPixmap.fromImage(qimg).scaled(
            self.width(), self.height(),
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        # Track scale for coordinate mapping
        self._scale_x = w / pm.width()  if pm.width()  > 0 else 1.0
        self._scale_y = h / pm.height() if pm.height() > 0 else 1.0
        self.setPixmap(pm)

    def start_manual_calibration(self) -> None:
        self._accepting_clicks = True
        self._click_count      = 0

    def stop_manual_calibration(self) -> None:
        self._accepting_clicks = False

    def mousePressEvent(self, event) -> None:
        if not self._accepting_clicks:
            return
        # Map widget coords → frame coords (account for centred pixmap letterboxing)
        pm     = self.pixmap()
        if pm is None:
            return
        ox     = (self.width()  - pm.width())  // 2
        oy     = (self.height() - pm.height()) // 2
        px     = (event.x() - ox) * self._scale_x
        py     = (event.y() - oy) * self._scale_y
        if 0 <= px <= self._frame_w and 0 <= py <= self._frame_h:
            self.corner_clicked.emit(px, py)
            self._click_count += 1
            if self._click_count >= 4:
                self._accepting_clicks = False
