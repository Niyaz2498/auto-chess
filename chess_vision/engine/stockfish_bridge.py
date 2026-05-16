import chess
import chess.engine
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import STOCKFISH_PATHS, ENGINE_THINK_TIME_MS, LEVEL_CONFIG


class StockfishBridge:
    def __init__(self):
        self._engine: Optional[chess.engine.SimpleEngine] = None
        self._level: int = 5
        path = self._find_stockfish()
        self._engine = chess.engine.SimpleEngine.popen_uci(str(path))

    def set_level(self, level: int) -> None:
        if level not in LEVEL_CONFIG:
            raise ValueError(f"Level must be 1–10, got {level}")
        cfg = LEVEL_CONFIG[level]
        if cfg["limit"]:
            self._engine.configure({"UCI_LimitStrength": True, "UCI_Elo": cfg["elo"]})
        else:
            self._engine.configure({"UCI_LimitStrength": False})
        self._level = level

    def get_best_move(self, fen: str) -> chess.Move:
        board  = chess.Board(fen)
        limit  = chess.engine.Limit(time=ENGINE_THINK_TIME_MS / 1000.0)
        result = self._engine.play(board, limit)
        return result.move

    def shutdown(self) -> None:
        if self._engine is not None:
            self._engine.quit()
            self._engine = None

    @staticmethod
    def _find_stockfish() -> Path:
        for p in STOCKFISH_PATHS:
            path = Path(p)
            if path.exists():
                return path
        raise FileNotFoundError(
            "Stockfish not found. Install it with:\n\n"
            "    brew install stockfish\n\n"
            f"Searched paths: {STOCKFISH_PATHS}"
        )
