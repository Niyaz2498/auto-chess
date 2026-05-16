import chess
import chess.svg
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from PyQt5.QtSvg import QSvgWidget
from PyQt5.QtCore import QByteArray, QTimer


class BoardWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._svg_widget = QSvgWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._svg_widget)
        self.setMinimumSize(400, 400)

        self._board         = chess.Board()
        self._player_move:  chess.Move | None = None
        self._engine_move:  chess.Move | None = None
        self._flash_illegal = False
        self._flash_timer   = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._clear_flash)

        self._render()

    def update_board(
        self,
        board: chess.Board,
        player_move:  chess.Move | None = None,
        engine_move:  chess.Move | None = None,
    ) -> None:
        self._board        = board
        self._player_move  = player_move
        self._engine_move  = engine_move
        self._flash_illegal = False
        self._render()

    def flash_illegal(self) -> None:
        self._flash_illegal = True
        self._render()
        self._flash_timer.start(800)

    def _clear_flash(self) -> None:
        self._flash_illegal = False
        self._render()

    def _render(self) -> None:
        arrows = []
        fill   = {}

        if self._flash_illegal:
            # Colour all squares light red
            for sq in chess.SQUARES:
                fill[sq] = "#ff000033"
        else:
            if self._player_move:
                fill[self._player_move.from_square] = "#aaf77f"   # green from
                fill[self._player_move.to_square]   = "#aaf77f"   # green to
            if self._engine_move:
                fill[self._engine_move.from_square] = "#7fb8f7"   # blue from
                fill[self._engine_move.to_square]   = "#5599ee"   # blue to (darker)

        svg_str = chess.svg.board(
            board=self._board,
            fill=fill,
            size=400,
        )
        self._svg_widget.load(QByteArray(svg_str.encode()))
