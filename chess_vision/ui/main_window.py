import cv2
import numpy as np
import chess
import subprocess
from pathlib import Path
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QLabel, QSlider, QComboBox, QCheckBox, QTextEdit, QDialog,
    QDialogButtonBox, QMessageBox, QSizePolicy, QFrame, QGroupBox, QSpinBox,
    QAbstractButton, QApplication, QShortcut,
)
from PyQt5.QtCore import Qt, QTimer, QObject, QEvent, pyqtSlot
from PyQt5.QtGui import QFont, QKeySequence

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import LEVEL_CONFIG, DEFAULT_LEVEL, WARP_SIZE
from calibration.calibrator import Calibrator
from vision.camera import Camera
from vision.board_detector import BoardDetector
from engine.stockfish_bridge import StockfishBridge
from engine.game_manager import GameManager, IllegalMoveError, AmbiguousMoveError
from ui.board_widget import BoardWidget
from ui.camera_widget import CameraWidget


def _get_macos_voices() -> list[tuple[str, str]]:
    """Return list of (display_label, voice_name) for all English macOS voices."""
    import re
    try:
        result = subprocess.run(["say", "-v", "?"], capture_output=True, text=True)
        voices = []
        for line in result.stdout.splitlines():
            m = re.match(r'^(.+?)\s+(en_\w+)\s+#', line)
            if m:
                name   = m.group(1).strip()
                locale = m.group(2)
                voices.append((f"{name}  [{locale}]", name))
        return sorted(voices, key=lambda x: x[0].lower())
    except Exception:
        return [("Samantha  [en_US]", "Samantha")]


def _say(text: str, voice: str = "") -> None:
    """Non-blocking macOS TTS."""
    cmd = ["say"]
    if voice:
        cmd += ["-v", voice]
    cmd.append(text)
    subprocess.Popen(cmd)


_NATO  = {'a':'alpha','b':'bravo','c':'charlie','d':'delta',
          'e':'echo','f':'foxtrot','g':'golf','h':'hotel'}
_PIECE = {'N':'Knight','B':'Bishop','R':'Rook','Q':'Queen','K':'King'}
_P     = ' [[slnc 300]] '   # pause between tokens

def _san_to_speech(san: str) -> str:
    """Convert SAN to clearly spoken text.
    File letters are spoken as 'NATO actual-square', e.g. Nd6 → 'Knight delta d6'.
    """
    suffix = ''
    if san.endswith('#'):
        suffix = _P + 'checkmate'
    elif san.endswith('+'):
        suffix = _P + 'check'

    if san.startswith('O-O-O'):
        return 'Queenside castling' + suffix
    if san.startswith('O-O'):
        return 'Kingside castling' + suffix

    clean = san.rstrip('+#')
    promo_suffix = ''
    if '=' in clean:
        clean, promo = clean.split('=', 1)
        promo_suffix = _P + 'promotes to' + _P + _PIECE.get(promo, promo)

    parts = []
    i = 0
    while i < len(clean):
        ch = clean[i]
        if ch in _PIECE:
            parts.append(_PIECE[ch])
            i += 1
        elif ch == 'x':
            parts.append('takes')
            i += 1
        elif ch in _NATO:
            if i + 1 < len(clean) and clean[i + 1].isdigit():
                # file + rank together → "delta d6"
                parts.append(f"{_NATO[ch]} {ch}{clean[i + 1]}")
                i += 2
            else:
                # disambiguation file only → "bravo b"
                parts.append(f"{_NATO[ch]} {ch}")
                i += 1
        elif ch.isdigit():
            parts.append(ch)
            i += 1
        else:
            i += 1

    return _P.join(parts) + promo_suffix + suffix


def _engine_sq_names(board: chess.Board, move: chess.Move) -> set:
    """Square names whose piece occupancy changes as a result of move.
    Handles castling (4 squares) and en passant (3 squares)."""
    sqs = {chess.square_name(move.from_square), chess.square_name(move.to_square)}
    if board.is_en_passant(move):
        ep = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
        sqs.add(chess.square_name(ep))
    if board.is_castling(move):
        rank = chess.square_rank(move.from_square)
        if chess.square_file(move.to_square) == 6:  # kingside
            sqs |= {chess.square_name(chess.square(7, rank)), chess.square_name(chess.square(5, rank))}
        else:                                        # queenside
            sqs |= {chess.square_name(chess.square(0, rank)), chess.square_name(chess.square(3, rank))}
    return sqs


class MouseFilter(QObject):
    """App-level event filter: left click → My Move, right click → Confirm Engine Move."""

    def __init__(self, on_left, on_right, parent=None):
        super().__init__(parent)
        self._on_left  = on_left
        self._on_right = on_right

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.XButton1:    # side back  → My Move
                self._on_left()
            elif event.button() == Qt.XButton2:  # side forward → Confirm Engine Move
                self._on_right()
        return False   # never consume — let the event propagate normally


class PromotionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pawn Promotion")
        self.setModal(True)
        self.chosen = chess.QUEEN
        layout = QHBoxLayout(self)
        for piece, label in [
            (chess.QUEEN,  "Queen (Q)"),
            (chess.ROOK,   "Rook (R)"),
            (chess.BISHOP, "Bishop (B)"),
            (chess.KNIGHT, "Knight (N)"),
        ]:
            btn = QPushButton(label, self)
            btn.setMinimumWidth(100)
            btn.clicked.connect(lambda _, p=piece: self._pick(p))
            layout.addWidget(btn)

    def _pick(self, piece: chess.PieceType) -> None:
        self.chosen = piece
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CV Chess — Match Mode")
        self.resize(1200, 720)

        self._calibrator    = Calibrator()
        self._camera        = Camera()
        self._detector      = BoardDetector()
        self._game_manager  = GameManager()
        self._engine:       StockfishBridge | None = None
        self._player_color  = chess.WHITE
        self._level         = DEFAULT_LEVEL
        self._game_active   = False
        self._awaiting_engine_confirm = False
        self._engine_move_squares: set = set()   # squares the engine move touches
        self._last_player_move:  chess.Move | None = None
        self._last_engine_move:  chess.Move | None = None
        self._pending_promotion: list[str] | None  = None
        self._manual_corners:   list[tuple[float, float]] = []
        self._manual_calibrating = False

        self._build_ui()
        self._init_camera()
        self._init_engine()
        self._start_camera_timer()
        self._init_mouse_filter()

        if self._calibrator.is_calibrated():
            self._set_status("Calibration loaded. Select level and press New Game.")
        else:
            self._set_status("Not calibrated. Press Calibrate to begin.")

        # First-run heatmap tip
        self._status_bar_label.setToolTip(
            "Tip: Open the heatmap and make a test move to verify detection before playing a real game."
        )

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setSpacing(8)

        root.addWidget(self._build_left_panel(), stretch=1)
        root.addWidget(self._build_right_panel(), stretch=1)

    def _build_left_panel(self) -> QWidget:
        panel  = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(6)

        # Top-bar
        layout.addWidget(self._build_top_bar())

        # Camera
        self._camera_widget = CameraWidget()
        self._camera_widget.corner_clicked.connect(self._on_corner_clicked)
        layout.addWidget(self._camera_widget, stretch=1)

        # Lighting warning
        self._lighting_banner = QLabel()
        self._lighting_banner.setStyleSheet(
            "background: #ff9800; color: #000; padding: 4px; border-radius: 3px;"
        )
        self._lighting_banner.setWordWrap(True)
        self._lighting_banner.setVisible(False)
        layout.addWidget(self._lighting_banner)

        # Buttons
        self._btn_my_move = QPushButton("My Move  [Space]")
        self._btn_my_move.setMinimumHeight(48)
        self._btn_my_move.setFont(QFont("", 14, QFont.Bold))
        self._btn_my_move.setStyleSheet(
            "QPushButton { background:#27ae60; color:white; border-radius:6px; }"
            "QPushButton:hover { background:#2ecc71; }"
            "QPushButton:disabled { background:#555; }"
        )
        self._btn_my_move.clicked.connect(self._on_space)
        self._btn_my_move.setEnabled(False)
        layout.addWidget(self._btn_my_move)

        self._btn_set_baseline = QPushButton("Set Baseline (piece touched)")
        self._btn_set_baseline.setMinimumHeight(32)
        self._btn_set_baseline.setStyleSheet(
            "QPushButton { background:#7f8c8d; color:white; border-radius:6px; font-size:12px; }"
            "QPushButton:hover { background:#95a5a6; }"
            "QPushButton:disabled { background:#444; }"
        )
        self._btn_set_baseline.clicked.connect(self._on_set_baseline)
        self._btn_set_baseline.setEnabled(False)
        layout.addWidget(self._btn_set_baseline)

        # Calibrate + heatmap row
        row = QHBoxLayout()
        self._btn_calibrate = QPushButton("Auto Calibrate")
        self._btn_calibrate.clicked.connect(self._on_calibrate)
        row.addWidget(self._btn_calibrate)
        self._btn_manual_cal = QPushButton("Manual Calibrate")
        self._btn_manual_cal.setStyleSheet(
            "QPushButton { background:#7d4fa0; color:white; border-radius:4px; }"
            "QPushButton:hover { background:#9b6bbf; }"
        )
        self._btn_manual_cal.clicked.connect(self._on_calibrate_manual)
        row.addWidget(self._btn_manual_cal)
        self._chk_heatmap = QCheckBox("Show Heatmap")
        self._chk_heatmap.stateChanged.connect(self._on_heatmap_toggle)
        row.addWidget(self._chk_heatmap)
        self._chk_blue_debug = QCheckBox("Color Debug")
        self._chk_blue_debug.setStyleSheet("color: #66ccff;")
        self._chk_blue_debug.stateChanged.connect(self._on_color_debug_toggled)
        row.addWidget(self._chk_blue_debug)
        self._chk_flip_rows = QCheckBox("Flip Ranks")
        self._chk_flip_rows.setToolTip("Check if ranks are mirrored (camera on wrong side)")
        self._chk_flip_rows.stateChanged.connect(lambda s: self._on_flip_changed())
        row.addWidget(self._chk_flip_rows)
        self._chk_flip_cols = QCheckBox("Flip Files")
        self._chk_flip_cols.setToolTip("Check if files are mirrored (camera left/right swapped)")
        self._chk_flip_cols.stateChanged.connect(lambda s: self._on_flip_changed())
        row.addWidget(self._chk_flip_cols)
        row.addWidget(QLabel("Threshold:"))
        self._threshold_spin = QSpinBox()
        self._threshold_spin.setRange(1, 100)
        self._threshold_spin.setValue(int(self._detector.threshold))
        self._threshold_spin.setToolTip("Diff threshold — lower = more sensitive. Tune with heatmap.")
        self._threshold_spin.valueChanged.connect(self._on_threshold_changed)
        row.addWidget(self._threshold_spin)
        layout.addLayout(row)

        # Status
        self._status_bar_label = QLabel("Initialising…")
        self._status_bar_label.setWordWrap(True)
        self._status_bar_label.setStyleSheet("color: #ccc; padding: 4px;")
        layout.addWidget(self._status_bar_label)

        self._blue_status_label = QLabel("")
        self._blue_status_label.setWordWrap(True)
        self._blue_status_label.setStyleSheet("color: #66ccff; padding: 2px 4px; font-family: monospace;")
        self._blue_status_label.setVisible(False)
        layout.addWidget(self._blue_status_label)

        # HSV slider panel — shown only when Color Debug is on
        self._hsv_panel = self._build_hsv_panel()
        self._hsv_panel.setVisible(False)
        layout.addWidget(self._hsv_panel)

        # Voice selector
        layout.addWidget(self._build_voice_panel())

        return panel

    def _build_hsv_panel(self) -> QWidget:
        panel = QGroupBox("Color Tuning")
        panel.setStyleSheet("QGroupBox { color: #aaa; font-size: 11px; }")
        grid  = QVBoxLayout(panel)
        grid.setSpacing(3)

        def _slider_row(label, color, lo, hi, val, on_change):
            r   = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(70)
            lbl.setStyleSheet(f"color: {color};")
            r.addWidget(lbl)
            sl  = QSlider(Qt.Horizontal)
            sl.setRange(lo, hi)
            sl.setValue(val)
            val_lbl = QLabel(str(val))
            val_lbl.setFixedWidth(30)
            val_lbl.setStyleSheet("color: #eee;")
            def _upd(v, vl=val_lbl, cb=on_change):
                vl.setText(str(v)); cb(v)
            sl.valueChanged.connect(_upd)
            r.addWidget(sl)
            r.addWidget(val_lbl)
            return r

        d = self._detector

        grid.addLayout(_slider_row("H-lo",   "#66aaff", 0, 180, d.blue_h_lo,       lambda v: setattr(d, 'blue_h_lo', v)))
        grid.addLayout(_slider_row("H-hi",   "#66aaff", 0, 180, d.blue_h_hi,       lambda v: setattr(d, 'blue_h_hi', v)))
        grid.addLayout(_slider_row("S-lo",   "#66aaff", 0, 255, d.blue_s_lo,       lambda v: setattr(d, 'blue_s_lo', v)))
        grid.addLayout(_slider_row("Min-px", "#66aaff", 0, 300, d.blue_min_pixels, lambda v: setattr(d, 'blue_min_pixels', v)))

        return panel

    def _build_voice_panel(self) -> QWidget:
        panel  = QGroupBox("Voice")
        panel.setStyleSheet("QGroupBox { color: #aaa; font-size: 11px; }")
        row    = QHBoxLayout(panel)
        row.setSpacing(6)

        self._voice_combo = QComboBox()
        voices = _get_macos_voices()
        for label, name in voices:
            self._voice_combo.addItem(label, name)
        # Default to Samantha if available
        default_idx = next(
            (i for i, (_, n) in enumerate(voices) if n == "Samantha"), 0
        )
        self._voice_combo.setCurrentIndex(default_idx)
        row.addWidget(self._voice_combo, stretch=1)

        btn_play = QPushButton("Play")
        btn_play.setFixedWidth(50)
        btn_play.clicked.connect(self._on_voice_preview)
        row.addWidget(btn_play)

        return panel

    def _build_top_bar(self) -> QWidget:
        bar    = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Level
        layout.addWidget(QLabel("Level:"))
        self._level_combo = QComboBox()
        for lvl, cfg in LEVEL_CONFIG.items():
            self._level_combo.addItem(f"{lvl} — {cfg['label']}", lvl)
        self._level_combo.setCurrentIndex(DEFAULT_LEVEL - 1)
        self._level_combo.currentIndexChanged.connect(self._on_level_changed)
        layout.addWidget(self._level_combo)

        self._elo_label = QLabel()
        self._update_elo_label()
        layout.addWidget(self._elo_label)

        layout.addStretch()

        # Colour
        layout.addWidget(QLabel("Play as:"))
        self._color_combo = QComboBox()
        self._color_combo.addItems(["White", "Black"])
        layout.addWidget(self._color_combo)

        layout.addStretch()

        # Game controls
        self._btn_new_game = QPushButton("New Game")
        self._btn_new_game.clicked.connect(self._on_new_game)
        layout.addWidget(self._btn_new_game)

        self._btn_resign = QPushButton("Resign")
        self._btn_resign.clicked.connect(self._on_resign)
        self._btn_resign.setEnabled(False)
        layout.addWidget(self._btn_resign)

        self._btn_save_pgn = QPushButton("Save PGN")
        self._btn_save_pgn.clicked.connect(self._on_save_pgn)
        layout.addWidget(self._btn_save_pgn)

        return bar

    def _build_right_panel(self) -> QWidget:
        panel  = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(6)

        # Digital board
        self._board_widget = BoardWidget()
        layout.addWidget(self._board_widget)

        # Move info status
        self._game_status_label = QLabel("No game in progress")
        self._game_status_label.setFont(QFont("", 11))
        self._game_status_label.setStyleSheet("color: #eee; padding: 4px;")
        layout.addWidget(self._game_status_label)

        # Move history
        grp = QGroupBox("Move History")
        grp_layout = QVBoxLayout(grp)
        self._move_history = QTextEdit()
        self._move_history.setReadOnly(True)
        self._move_history.setMaximumHeight(200)
        grp_layout.addWidget(self._move_history)
        layout.addWidget(grp)

        return panel

    # ── Init ──────────────────────────────────────────────────────────────────

    def _init_camera(self) -> None:
        if not self._camera.open():
            QMessageBox.warning(self, "Camera Error", "Could not open camera at index 0.")

    def _init_engine(self) -> None:
        try:
            self._engine = StockfishBridge()
            self._engine.set_level(DEFAULT_LEVEL)
        except FileNotFoundError as e:
            QMessageBox.critical(self, "Stockfish Not Found", str(e))

    def _init_mouse_filter(self) -> None:
        sc = QShortcut(QKeySequence(Qt.Key_Space), self)
        sc.setContext(Qt.ApplicationShortcut)
        sc.activated.connect(self._on_space)

    def _start_camera_timer(self) -> None:
        self._cam_timer = QTimer(self)
        self._cam_timer.timeout.connect(self._tick_camera)
        self._cam_timer.start(66)   # ~15 fps

    # ── Camera tick ───────────────────────────────────────────────────────────

    @pyqtSlot()
    def _tick_camera(self) -> None:
        frame = self._camera.read_frame()
        if frame is None:
            return

        if self._manual_calibrating:
            self._camera_widget.display_frame(frame)
        elif self._calibrator.is_calibrated():
            warped = self._calibrator.warp_frame(frame)
            if self._chk_blue_debug.isChecked():
                display  = self._detector.render_color_debug(warped)
                blue_sq  = self._detector.detect_blue_squares(warped)
                base_sq  = self._detector.get_baseline_squares()
                self._blue_status_label.setVisible(True)
                sq_str   = ', '.join(sorted(blue_sq)) or 'none'
                base_str = ', '.join(sorted(base_sq)) or 'none'
                changed  = sorted(base_sq.symmetric_difference(set(blue_sq)))
                self._blue_status_label.setText(
                    f"Now: {len(blue_sq)} — {sq_str}\n"
                    f"Baseline: {len(base_sq)} — {base_str}\n"
                    f"Changed: {changed or 'none'}"
                )
            elif self._chk_heatmap.isChecked() and self._detector.has_baseline():
                display = self._detector.compute_heatmap(warped)
                self._blue_status_label.setVisible(False)
            else:
                display = self._calibrator.draw_grid(warped)
                self._blue_status_label.setVisible(False)
            self._camera_widget.display_frame(display)
        else:
            self._camera_widget.display_frame(frame)

    # ── Calibration ───────────────────────────────────────────────────────────

    @pyqtSlot()
    def _on_calibrate(self) -> None:
        frame = self._camera.read_frame(flush=True)
        if frame is None:
            self._set_status("No frame from camera.")
            return

        self._set_status("Attempting auto calibration…")
        success = self._calibrator.calibrate_auto(frame)
        if success:
            self._set_status("Auto calibration succeeded. Verify the grid overlay.")
            self._check_lighting(frame)
        else:
            self._set_status(
                "Auto calibration failed. Click the 4 outer corners of the board in order: "
                "top-left → top-right → bottom-right → bottom-left."
            )
            self._manual_corners = []
            self._camera_widget.start_manual_calibration()

    @pyqtSlot()
    def _on_calibrate_manual(self) -> None:
        self._manual_corners     = []
        self._manual_calibrating = True
        self._camera_widget.start_manual_calibration()
        self._set_status(
            "Click the 4 outer corners in order:  "
            "1) a8 (top-left)  →  2) h8 (top-right)  →  3) h1 (bottom-right)  →  4) a1 (bottom-left). "
            "Assumes White pieces are at the bottom of the camera view."
        )

    @pyqtSlot(float, float)
    def _on_corner_clicked(self, x: float, y: float) -> None:
        self._manual_corners.append((x, y))
        n = len(self._manual_corners)
        labels = ["a8 (top-left)", "h8 (top-right)", "h1 (bottom-right)", "a1 (bottom-left)"]
        if n < 4:
            self._set_status(f"Corner {n}/4 set ({labels[n-1]}). Click {labels[n]}.")
        else:
            self._calibrator.calibrate_manual(np.array(self._manual_corners, dtype=np.float32))
            self._manual_calibrating = False
            self._set_status("Manual calibration complete. Verify the grid overlay.")
            frame = self._camera.read_frame(flush=True)
            if frame is not None:
                self._check_lighting(frame)

    def _check_lighting(self, frame: np.ndarray) -> None:
        if not self._calibrator.is_calibrated():
            return
        warped      = self._calibrator.warp_frame(frame)
        brightness  = float(np.mean(cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)))
        if brightness < 60 or brightness > 210:
            self._lighting_banner.setText(
                f"Lighting may affect detection — adjust lamp. "
                f"(Brightness: {brightness:.0f}, recommended 60–210)"
            )
            self._lighting_banner.setVisible(True)
        else:
            self._lighting_banner.setVisible(False)

    # ── Game flow ─────────────────────────────────────────────────────────────

    @pyqtSlot()
    def _on_new_game(self) -> None:
        if self._engine is None:
            QMessageBox.warning(self, "Engine Error", "Stockfish is not running.")
            return
        if not self._calibrator.is_calibrated():
            QMessageBox.warning(self, "Not Calibrated", "Please calibrate the camera first.")
            return

        self._level = self._level_combo.currentData()
        self._engine.set_level(self._level)
        self._player_color = chess.WHITE if self._color_combo.currentText() == "White" else chess.BLACK
        self._game_manager.reset()
        self._last_player_move  = None
        self._last_engine_move  = None
        self._awaiting_engine_confirm = False
        self._game_active = True
        self._pending_promotion = None

        self._level_combo.setEnabled(False)
        self._color_combo.setEnabled(False)
        self._btn_resign.setEnabled(True)
        self._btn_set_baseline.setEnabled(True)

        self._board_widget.update_board(self._game_manager.get_board())
        self._update_move_history()

        QMessageBox.information(
            self, "New Game",
            "Set up your physical board to the starting position, then press OK and press Ready / My Move."
        )

        frame = self._camera.read_frame(flush=True)
        if frame is not None and self._calibrator.is_calibrated():
            warped = self._calibrator.warp_frame(frame)
            self._detector.confirm_position(warped)

        self._btn_my_move.setEnabled(True)

        if self._player_color == chess.BLACK:
            self._set_status("You play Black. Engine plays first.")
            self._engine_turn()
        else:
            self._set_status("Your turn. Make a move on the physical board, then press My Move.")
        self._update_game_status()

    @pyqtSlot()
    def _on_space(self) -> None:
        if not self._game_active:
            return

        # ── State 2: confirm engine move was placed on physical board ──────────
        if self._awaiting_engine_confirm:
            frame = self._camera.read_frame(flush=True)
            if frame is not None and self._calibrator.is_calibrated():
                warped = self._calibrator.warp_frame(frame)
                self._detector.confirm_position(warped)
            self._awaiting_engine_confirm = False
            self._engine_move_squares = set()
            subprocess.Popen(["afplay", "/System/Library/Sounds/Tink.aiff"])
            self._set_status("Your turn. Make your move, then press Space.")
            return

        # ── State 1: detect and resolve player's move ─────────────────────────
        frame = self._camera.read_frame(flush=True)
        if frame is None:
            self._set_status("No camera frame — try again.")
            return

        warped = self._calibrator.warp_frame(frame)
        try:
            changed = self._detector.detect_changed_squares(warped)
        except RuntimeError as e:
            self._set_status(str(e))
            return

        if not changed:
            self._set_status("No change detected — make your move then press Space.")
            return

        promotion = None
        if self._pending_promotion:
            changed   = self._pending_promotion
            promotion = self._ask_promotion()
            self._pending_promotion = None

        try:
            move = self._game_manager.resolve_move(changed, promotion)
        except (IllegalMoveError, AmbiguousMoveError) as e:
            self._board_widget.flash_illegal()
            self._set_status(f"Move error: {e}")
            return

        if self._game_manager.needs_promotion(move.from_square, move.to_square) and promotion is None:
            self._pending_promotion = changed
            promotion = self._ask_promotion()
            try:
                move = self._game_manager.resolve_move(changed, promotion)
            except (IllegalMoveError, AmbiguousMoveError) as e:
                self._board_widget.flash_illegal()
                self._set_status(f"Move error: {e}")
                return

        self._game_manager.push_move(move)
        self._last_player_move = move
        self._detector.confirm_position(warped)
        self._board_widget.update_board(
            self._game_manager.get_board(),
            player_move=self._last_player_move,
            engine_move=None,
        )
        self._update_move_history()
        self._update_game_status()

        if self._game_manager.is_game_over():
            self._end_game()
            return

        self._btn_my_move.setEnabled(False)
        self._engine_turn()

    def _engine_turn(self) -> None:
        if self._engine is None:
            return
        self._set_status("Engine is thinking…")
        try:
            engine_move = self._engine.get_best_move(self._game_manager.get_fen())
        except Exception as e:
            self._set_status(f"Engine error: {e}")
            return

        board_before          = self._game_manager.get_board().copy()
        self._last_engine_move = engine_move
        engine_san            = board_before.san(engine_move)
        self._engine_move_squares = _engine_sq_names(board_before, engine_move)
        self._game_manager.push_move(engine_move)
        self._board_widget.update_board(
            self._game_manager.get_board(),
            player_move=self._last_player_move,
            engine_move=engine_move,
        )
        self._update_move_history()
        self._update_game_status()

        from_name = chess.square_name(engine_move.from_square)
        to_name   = chess.square_name(engine_move.to_square)
        self._set_status(
            f"Engine: {engine_san} ({from_name}→{to_name}). "
            "Place it on the board, then press Space."
        )
        _say(_san_to_speech(engine_san), voice=self._voice_combo.currentData())

        self._awaiting_engine_confirm = True
        self._btn_my_move.setEnabled(True)

        if self._game_manager.is_game_over():
            self._end_game()

    @pyqtSlot()
    def _on_set_baseline(self) -> None:
        """Re-snap baseline from the current camera frame (use after accidentally touching a piece)."""
        frame = self._camera.read_frame(flush=True)
        if frame is None or not self._calibrator.is_calibrated():
            self._set_status("Cannot set baseline — no camera frame.")
            return
        warped = self._calibrator.warp_frame(frame)
        self._detector.confirm_position(warped)
        subprocess.Popen(["afplay", "/System/Library/Sounds/Tink.aiff"])
        self._set_status("Baseline updated. Continue playing.")

    @pyqtSlot()
    def _on_resign(self) -> None:
        if not self._game_active:
            return
        self._set_status("You resigned.")
        self._end_game(resigned=True)

    def _end_game(self, resigned: bool = False) -> None:
        self._game_active = False
        self._btn_my_move.setEnabled(False)
        self._btn_set_baseline.setEnabled(False)
        self._btn_resign.setEnabled(False)
        self._level_combo.setEnabled(True)
        self._color_combo.setEnabled(True)

        result = "You resigned." if resigned else self._game_manager.get_result()
        self._set_status(f"Game over — {result}")
        self._update_game_status()

        path = self._game_manager.auto_save_pgn()
        QMessageBox.information(
            self, "Game Over",
            f"Result: {result}\n\nPGN auto-saved to:\n{path}"
        )

    # ── Promotion ─────────────────────────────────────────────────────────────

    def _ask_promotion(self) -> chess.PieceType:
        dlg = PromotionDialog(self)
        dlg.exec_()
        return dlg.chosen

    # ── PGN save ──────────────────────────────────────────────────────────────

    @pyqtSlot()
    def _on_save_pgn(self) -> None:
        path = self._game_manager.auto_save_pgn()
        QMessageBox.information(self, "PGN Saved", f"PGN saved to:\n{path}")

    # ── Level / colour ────────────────────────────────────────────────────────

    @pyqtSlot(int)
    def _on_level_changed(self, _: int) -> None:
        self._level = self._level_combo.currentData()
        self._update_elo_label()

    def _update_elo_label(self) -> None:
        cfg  = LEVEL_CONFIG[self._level_combo.currentData() or DEFAULT_LEVEL]
        elo  = cfg["elo"] or "3000+"
        self._elo_label.setText(f"~{elo} ELO")
        self._elo_label.setStyleSheet("color: #f0c040; font-weight: bold;")

    # ── Heatmap ───────────────────────────────────────────────────────────────

    @pyqtSlot(int)
    def _on_heatmap_toggle(self, state: int) -> None:
        pass   # tick drives display; checking the checkbox is sufficient

    @pyqtSlot(int)
    def _on_color_debug_toggled(self, state: int) -> None:
        on = bool(state)
        self._hsv_panel.setVisible(on)
        self._blue_status_label.setVisible(on)

    @pyqtSlot(int)
    def _on_threshold_changed(self, value: int) -> None:
        self._detector.threshold = float(value)

    def _on_flip_changed(self) -> None:
        self._detector.flip_rows = self._chk_flip_rows.isChecked()
        self._detector.flip_cols = self._chk_flip_cols.isChecked()

    @pyqtSlot()
    def _on_voice_preview(self) -> None:
        _say("charlie [[slnc 200]] echo [[slnc 200]] bravo",
             voice=self._voice_combo.currentData())

    # ── Status / history helpers ──────────────────────────────────────────────

    def _set_status(self, msg: str) -> None:
        self._status_bar_label.setText(msg)

    def _update_game_status(self) -> None:
        board = self._game_manager.get_board()
        if self._game_manager.is_game_over():
            text = f"Game over — {board.result()}"
        elif board.is_check():
            turn = "White" if board.turn == chess.WHITE else "Black"
            text = f"CHECK! Move {board.fullmove_number} — {turn} to move"
        else:
            turn = "White" if board.turn == chess.WHITE else "Black"
            text = f"Move {board.fullmove_number} — {turn} to move"
        self._game_status_label.setText(text)

    def _update_move_history(self) -> None:
        board  = self._game_manager.get_board()
        # Rebuild SAN history from root
        tmp    = chess.Board()
        lines  = []
        for i, move in enumerate(board.move_stack):
            if tmp.turn == chess.WHITE:
                lines.append(f"{tmp.fullmove_number}. {tmp.san(move)}")
            else:
                if lines:
                    lines[-1] += f"  {tmp.san(move)}"
                else:
                    lines.append(f"{tmp.fullmove_number}... {tmp.san(move)}")
            tmp.push(move)
        self._move_history.setPlainText("\n".join(lines))
        # Scroll to bottom
        self._move_history.verticalScrollBar().setValue(
            self._move_history.verticalScrollBar().maximum()
        )

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        self._cam_timer.stop()
        self._camera.release()
        if self._engine:
            self._engine.shutdown()
        super().closeEvent(event)
