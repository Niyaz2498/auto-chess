import chess
import chess.pgn
import io
from datetime import datetime
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import GAMES_DIR


class IllegalMoveError(Exception):
    pass


class AmbiguousMoveError(Exception):
    pass


class GameManager:
    def __init__(self):
        self._board = chess.Board()
        self._game  = chess.pgn.Game()
        self._node  = self._game          # current PGN node
        self._game.headers["Event"] = "Physical Board Match"
        self._game.headers["Date"]  = datetime.now().strftime("%Y.%m.%d")

    # ── State queries ─────────────────────────────────────────────────────────

    def get_board(self) -> chess.Board:
        return self._board

    def get_fen(self) -> str:
        return self._board.fen()

    def get_legal_moves(self) -> list[chess.Move]:
        return list(self._board.legal_moves)

    def is_game_over(self) -> bool:
        return self._board.is_game_over()

    def get_result(self) -> str:
        return self._board.result()

    def needs_promotion(self, from_sq: chess.Square, to_sq: chess.Square) -> bool:
        piece = self._board.piece_at(from_sq)
        if piece is None or piece.piece_type != chess.PAWN:
            return False
        rank = chess.square_rank(to_sq)
        return (piece.color == chess.WHITE and rank == 7) or \
               (piece.color == chess.BLACK and rank == 0)

    def turn(self) -> chess.Color:
        return self._board.turn

    def fullmove_number(self) -> int:
        return self._board.fullmove_number

    # ── Move resolution ───────────────────────────────────────────────────────

    def resolve_move(
        self,
        changed_squares: list[str],
        promotion: Optional[chess.PieceType] = None,
    ) -> chess.Move:
        """Convert a list of changed square names to a legal chess.Move.

        Raises IllegalMoveError or AmbiguousMoveError if the move cannot be determined.
        """
        n = len(changed_squares)
        if n < 2:
            raise IllegalMoveError(
                f"Only {n} square(s) changed — not a valid move. "
                "Remove your hand completely and press the button again."
            )

        squares = [chess.parse_square(s) for s in changed_squares]

        if n == 2:
            return self._resolve_standard(squares, promotion)
        elif n == 3:
            return self._resolve_en_passant(squares)
        elif n == 4:
            return self._resolve_castling(squares)
        else:
            raise IllegalMoveError(
                f"{n} squares changed — too many. Check for piece collision or re-press."
            )

    def _resolve_standard(
        self, squares: list[chess.Square], promotion: Optional[chess.PieceType]
    ) -> chess.Move:
        # One square lost a piece (origin), one gained (destination).
        # We try both orderings and pick the one that produces a legal move.
        candidates = []
        for from_sq in squares:
            for to_sq in squares:
                if from_sq == to_sq:
                    continue
                move = chess.Move(from_sq, to_sq, promotion=promotion)
                if move in self._board.legal_moves:
                    candidates.append(move)
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) == 0:
            raise IllegalMoveError(
                f"No legal move between {[chess.square_name(s) for s in squares]}."
            )
        raise AmbiguousMoveError(
            f"Ambiguous move — multiple legal options: {candidates}."
        )

    def _resolve_en_passant(self, squares: list[chess.Square]) -> chess.Move:
        for from_sq in squares:
            for to_sq in squares:
                if from_sq == to_sq:
                    continue
                move = chess.Move(from_sq, to_sq)
                if move in self._board.legal_moves and self._board.is_en_passant(move):
                    return move
        raise IllegalMoveError(
            f"3 changed squares but no legal en passant found: "
            f"{[chess.square_name(s) for s in squares]}."
        )

    def _resolve_castling(self, squares: list[chess.Square]) -> chess.Move:
        for from_sq in squares:
            for to_sq in squares:
                if from_sq == to_sq:
                    continue
                move = chess.Move(from_sq, to_sq)
                if move in self._board.legal_moves and self._board.is_castling(move):
                    return move
        raise IllegalMoveError(
            f"4 changed squares but no legal castling found: "
            f"{[chess.square_name(s) for s in squares]}."
        )

    # ── Move application ──────────────────────────────────────────────────────

    def push_move(self, move: chess.Move) -> None:
        if move not in self._board.legal_moves:
            raise IllegalMoveError(f"Illegal move: {move.uci()}")
        self._node = self._node.add_variation(move)
        self._board.push(move)

    # ── PGN ───────────────────────────────────────────────────────────────────

    def get_pgn(self) -> str:
        exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
        return self._game.accept(exporter)

    def auto_save_pgn(self) -> Path:
        GAMES_DIR.mkdir(parents=True, exist_ok=True)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = GAMES_DIR / f"game_{ts}.pgn"
        path.write_text(self.get_pgn())
        return path

    # ── Reset ─────────────────────────────────────────────────────────────────

    def reset(self) -> None:
        self._board = chess.Board()
        self._game  = chess.pgn.Game()
        self._node  = self._game
        self._game.headers["Event"] = "Physical Board Match"
        self._game.headers["Date"]  = datetime.now().strftime("%Y.%m.%d")
