"""
ULTIMATE TIC-TAC-TOE
A polished single-file Python game with:
- Ultimate Tic-Tac-Toe rules (9 small boards inside one 3x3 meta-board)
- Human vs AI
- 3 AI difficulties
- Strong AI using tactical search + alpha-beta on local boards + strategic heuristics
- Persistent ranking points and ranks
- Match history / statistics
- New game, reset stats, and player-name support
- No third-party packages required (Tkinter is part of standard Python on Windows)

Run:
    python ultimate_tic_tac_toe.py
"""

from __future__ import annotations

import json
import math
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

import tkinter as tk
from tkinter import ttk
from tkinter import messagebox, simpledialog, filedialog


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

APP_TITLE = "UTT — Ultimate Tic-Tac-Toe"
SAVE_FILE = Path.home() / ".ultimate_tic_tac_toe_profile.json"
KATRINA_MEMORY_FILE = Path.home() / ".ultimate_tic_tac_toe_katrina_memory.json"
LEADERBOARD_FILE = Path.home() / ".ultimate_tic_tac_toe_leaderboard.json"
AI_RP_FILE = Path.home() / ".ultimate_tic_tac_toe_ai_rp.json"

OFFICIAL_AI_LEVELS = ("Easy", "Medium", "Hard", "Nightmare", "Oracle", "Katrina2")


BG = "#10131a"
PANEL = "#171c26"
PANEL_2 = "#202735"
TEXT = "#f4f7fb"
MUTED = "#9ba7b8"
X_COLOR = "#5cc8ff"
O_COLOR = "#ff6b8a"
GOLD = "#ffd166"
GREEN = "#55d187"
RED = "#ff6577"
LINE = "#384355"
CELL_BG = "#141923"
HOVER = "#293346"
ACTIVE = "#34425a"

META_LINES = (
    (0, 1, 2), (3, 4, 5), (6, 7, 8),
    (0, 3, 6), (1, 4, 7), (2, 5, 8),
    (0, 4, 8), (2, 4, 6),
)

# A small-board position's strategic weight.
LOCAL_POSITION_WEIGHT = (3, 2, 3, 2, 4, 2, 3, 2, 3)

RANKS = [
    (0, "Unranked"),
    (100, "Bronze"),
    (250, "Silver"),
    (450, "Gold"),
    (700, "Platinum"),
    (1000, "Diamond"),
    (1400, "Master"),
    (1900, "Grandmaster"),
    (2500, "Legend"),
]

# Ranking reward depends on the AI difficulty defeated.
# The loss penalty also scales with difficulty, so beating stronger AI
# meaningfully accelerates progression.
AI_RATING = {
    "Easy": {"win": 10, "loss": 5},
    "Medium": {"win": 25, "loss": 10},
    "Hard": {"win": 50, "loss": 20},
    "Nightmare": {"win": 100, "loss": 35},
    "Oracle": {"win": 175, "loss": 50},
    "Katrina2": {"win": 250, "loss": 0},
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Profile:
    name: str = "Player"
    points: int = 100
    wins: int = 0
    losses: int = 0
    draws: int = 0
    games: int = 0
    best_streak: int = 0
    current_streak: int = 0
    recent_results: list[str] = field(default_factory=list)

    @property
    def rank(self) -> str:
        current = RANKS[0][1]
        for threshold, name in RANKS:
            if self.points >= threshold:
                current = name
        return current


class UltimateBoard:
    """
    Board representation:
      cells[board_index][cell_index] where each is "", "X", or "O".
      small_status[board_index] is "", "X", "O", or "D" (drawn).
      next_board is the forced small board index, or None if any board is legal.
    """

    def __init__(self):
        self.cells = [[""] * 9 for _ in range(9)]
        self.small_status = [""] * 9
        self.meta_status = ""
        self.next_board: int | None = None
        self.turn = "X"
        self.last_move: tuple[int, int] | None = None

    def clone(self) -> "UltimateBoard":
        b = UltimateBoard()
        b.cells = [row[:] for row in self.cells]
        b.small_status = self.small_status[:]
        b.meta_status = self.meta_status
        b.next_board = self.next_board
        b.turn = self.turn
        b.last_move = self.last_move
        return b

    @staticmethod
    def winner(cells: list[str]) -> str:
        for a, b, c in META_LINES:
            if cells[a] and cells[a] == cells[b] == cells[c]:
                return cells[a]
        if all(cells):
            return "D"
        return ""

    def legal_moves(self) -> list[tuple[int, int]]:
        if self.meta_status:
            return []

        if self.next_board is not None and self.small_status[self.next_board] == "":
            boards = [self.next_board]
        else:
            boards = [i for i in range(9) if self.small_status[i] == ""]

        return [
            (board, cell)
            for board in boards
            for cell in range(9)
            if not self.cells[board][cell]
        ]

    def play(self, board: int, cell: int) -> bool:
        if (board, cell) not in set(self.legal_moves()):
            return False

        player = self.turn
        self.cells[board][cell] = player

        status = self.winner(self.cells[board])
        if status:
            self.small_status[board] = status

        self.meta_status = self.winner(self.small_status)
        self.last_move = (board, cell)

        # The cell chosen becomes the next board. If that board is already
        # won/drawn, the next player can choose any unfinished small board.
        if not self.meta_status:
            target = cell
            self.next_board = target if self.small_status[target] == "" else None
        else:
            self.next_board = None

        self.turn = "O" if player == "X" else "X"
        return True


# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------

def line_score(line: list[str], me: str, opp: str) -> int:
    m = line.count(me)
    o = line.count(opp)
    e = line.count("")
    if m and o:
        return 0
    if m == 2 and e == 1:
        return 70
    if m == 1 and e == 2:
        return 9
    if o == 2 and e == 1:
        return -85
    if o == 1 and e == 2:
        return -10
    return 0


def local_heuristic(cells: list[str], me: str) -> int:
    opp = "O" if me == "X" else "X"
    score = 0
    for a, b, c in META_LINES:
        score += line_score([cells[a], cells[b], cells[c]], me, opp)
    for i, value in enumerate(cells):
        if value == me:
            score += LOCAL_POSITION_WEIGHT[i]
        elif value == opp:
            score -= LOCAL_POSITION_WEIGHT[i]
    return score


def local_minimax(cells: list[str], ai: str, turn: str, alpha: int, beta: int, depth: int) -> int:
    winner = UltimateBoard.winner(cells)
    if winner:
        if winner == ai:
            return 10000 + depth
        if winner == ("O" if ai == "X" else "X"):
            return -10000 - depth
        return 0

    if depth == 0:
        return local_heuristic(cells, ai)

    moves = [i for i, x in enumerate(cells) if not x]
    if turn == ai:
        best = -math.inf
        for i in moves:
            cells[i] = turn
            value = local_minimax(cells, ai, "O" if turn == "X" else "X",
                                   alpha, beta, depth - 1)
            cells[i] = ""
            best = max(best, value)
            alpha = max(alpha, value)
            if beta <= alpha:
                break
        return int(best)
    else:
        best = math.inf
        for i in moves:
            cells[i] = turn
            value = local_minimax(cells, ai, "O" if turn == "X" else "X",
                                   alpha, beta, depth - 1)
            cells[i] = ""
            best = min(best, value)
            beta = min(beta, value)
            if beta <= alpha:
                break
        return int(best)


def strategic_score(game: UltimateBoard, ai: str) -> int:
    opp = "O" if ai == "X" else "X"
    score = 0

    # Winning a small board is enormously more valuable than a few cells.
    for i, status in enumerate(game.small_status):
        if status == ai:
            score += 850 + LOCAL_POSITION_WEIGHT[i] * 30
        elif status == opp:
            score -= 850 + LOCAL_POSITION_WEIGHT[i] * 30

    # Threats in the meta board.
    for a, b, c in META_LINES:
        line = [game.small_status[a], game.small_status[b], game.small_status[c]]
        score += line_score(line, ai, opp) * 7

    # Evaluate unfinished local boards.
    for i, status in enumerate(game.small_status):
        if status == "":
            score += local_heuristic(game.cells[i], ai) * 2

    # Prefer moves that send the opponent into a useful target board for us,
    # while avoiding giving them an immediate winning opportunity.
    return score


def katrina_state_key(game: UltimateBoard) -> str:
    """Stable local key for a complete Ultimate Tic Tac Toe position."""
    return json.dumps({
        "cells": game.cells,
        "small_status": game.small_status,
        "meta_status": game.meta_status,
        "next_board": game.next_board,
        "turn": game.turn,
    }, separators=(",", ":"), sort_keys=True)


def load_katrina_memory() -> dict:
    try:
        data = json.loads(KATRINA_MEMORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def save_katrina_memory(memory: dict) -> None:
    try:
        KATRINA_MEMORY_FILE.write_text(
            json.dumps(memory, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


KATRINA_MEMORY = load_katrina_memory()


def katrina_remember(state_key, opponent_move, response) -> None:
    KATRINA_MEMORY[state_key] = {
        "opponent_move": [opponent_move[0], opponent_move[1]],
        "response": [response[0], response[1]],
    }
    save_katrina_memory(KATRINA_MEMORY)


AI_MOD_DIR = Path(__file__).resolve().parent / "Mods"
AI_MODS = {}

def reload_ai_mods():
    import importlib.util
    AI_MODS.clear()
    AI_MOD_DIR.mkdir(exist_ok=True)
    for file in sorted(AI_MOD_DIR.glob("*.py")):
        if file.name.startswith("_"): continue
        try:
            spec=importlib.util.spec_from_file_location("utt_mod_"+file.stem,file)
            mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
            fn=getattr(mod,"choose_move",None)
            name=str(getattr(mod,"AI_NAME",file.stem))[:32]
            if callable(fn): AI_MODS[name]=fn
        except Exception:
            continue

def get_all_ai_names():
    return tuple(OFFICIAL_AI_LEVELS)+tuple(sorted(AI_MODS))

def get_ai_move(game, name):
    if name in AI_MODS:
        try:
            move=AI_MODS[name](game.clone())
            if move in game.legal_moves(): return move
        except Exception:
            pass
        legal=game.legal_moves(); return random.choice(legal) if legal else None
    return ai_move(game,name)

reload_ai_mods()

def ai_move(game: UltimateBoard, difficulty: str) -> tuple[int, int]:
    moves = game.legal_moves()
    if not moves:
        raise RuntimeError("AI was asked for a move when no legal moves exist.")

    ai = game.turn
    opp = "O" if ai == "X" else "X"

    # Easy: tactical awareness plus randomness.
    if difficulty == "Easy":
        winning = []
        blocking = []
        for move in moves:
            test = game.clone()
            test.play(*move)
            if test.small_status[move[0]] == ai:
                winning.append(move)

            # Check if the opponent can immediately win the target board.
            block_test = game.clone()
            block_test.play(*move)
            target = block_test.next_board
            if target is not None:
                for c in range(9):
                    if not block_test.cells[target][c]:
                        b2 = block_test.clone()
                        b2.play(target, c)
                        if b2.small_status[target] == opp:
                            blocking.append(move)
                            break

        if winning:
            return random.choice(winning)
        if blocking:
            return random.choice(blocking)
        return random.choice(moves)

    # Medium: score every move using a shallow strategic look-ahead.
    if difficulty == "Medium":
        best_value = -math.inf
        best = []
        for move in moves:
            test = game.clone()
            test.play(*move)
            value = strategic_score(test, ai)
            # Immediate local wins get priority.
            if test.small_status[move[0]] == ai:
                value += 1200
            if test.meta_status == ai:
                value += 100000
            if test.meta_status == opp:
                value -= 100000

            if value > best_value:
                best_value, best = value, [move]
            elif value == best_value:
                best.append(move)
        return random.choice(best)

    # Nightmare: deeper bounded alpha-beta with stronger move ordering.
    # Ultimate Tic-Tac-Toe has a very large game tree, so even Nightmare
    # remains bounded to keep the desktop UI responsive.
    if difficulty == "Nightmare":
        def search_nightmare(position: UltimateBoard, depth: int,
                             alpha: float, beta: float) -> float:
            if position.meta_status:
                if position.meta_status == ai:
                    return 1000000 + depth * 100
                if position.meta_status == opp:
                    return -1000000 - depth * 100
                return 0

            if depth == 0:
                return strategic_score(position, ai)

            legal = position.legal_moves()

            def order(move):
                p = position.clone()
                p.play(*move)
                value = strategic_score(p, ai)
                if p.meta_status == ai:
                    value += 200000
                elif p.meta_status == opp:
                    value -= 200000
                if p.small_status[move[0]] == ai:
                    value += 1800
                if p.small_status[move[0]] == opp:
                    value -= 1400
                if move[1] == 4:
                    value += 45
                return value

            ordered = sorted(legal, key=order, reverse=(position.turn == ai))

            if position.turn == ai:
                value = -math.inf
                for move in ordered:
                    p = position.clone()
                    p.play(*move)
                    value = max(value, search_nightmare(p, depth - 1, alpha, beta))
                    alpha = max(alpha, value)
                    if beta <= alpha:
                        break
                return value
            else:
                value = math.inf
                for move in ordered:
                    p = position.clone()
                    p.play(*move)
                    value = min(value, search_nightmare(p, depth - 1, alpha, beta))
                    beta = min(beta, value)
                    if beta <= alpha:
                        break
                return value

        def nightmare_order(move):
            p = game.clone()
            p.play(*move)
            value = strategic_score(p, ai)
            if p.meta_status == ai:
                value += 200000
            elif p.meta_status == opp:
                value -= 200000
            if p.small_status[move[0]] == ai:
                value += 2500
            elif p.small_status[move[0]] == opp:
                value -= 2200

            # Strong preference for sending the opponent to a board where
            # their options are limited or strategically unfavorable.
            if p.next_board is not None:
                target = p.next_board
                if p.small_status[target] == "":
                    target_score = local_heuristic(p.cells[target], ai)
                    value += target_score * 3

            if move[1] == 4:
                value += 70
            return value

        # Keep the strongest candidates only; depth 3 provides a substantial
        # increase in look-ahead without exploding the game tree.
        candidates = sorted(
            moves, key=nightmare_order, reverse=True
        )[:14]

        best_value = -math.inf
        best_moves = []
        for move in candidates:
            p = game.clone()
            p.play(*move)
            value = search_nightmare(p, 4, -math.inf, math.inf)
            if value > best_value:
                best_value = value
                best_moves = [move]
            elif value == best_value:
                best_moves.append(move)

        return random.choice(best_moves)

    # Oracle: no learning, no memory. Its core concept is exhaustive
    # future calculation: a transposition-cached proof search that prioritizes
    # forced wins, forced blocks, and the long-term meta-board position.
    # Unlike Katrina, Oracle never changes from previous matches.
    if difficulty == "Oracle":
        table = {}

        def oracle_order(position, move):
            child = position.clone()
            child.play(*move)
            value = strategic_score(child, ai)

            if child.meta_status == ai:
                value += 10_000_000
            elif child.meta_status == opp:
                value -= 10_000_000

            if child.small_status[move[0]] == ai:
                value += 12_000
            elif child.small_status[move[0]] == opp:
                value -= 9_000

            # Oracle strongly values controlling the destination board.
            if child.next_board is not None:
                target = child.next_board
                if child.small_status[target] == "":
                    value += local_heuristic(child.cells[target], ai) * 5

            if move[1] == 4:
                value += 250
            elif move[1] in (0, 2, 6, 8):
                value += 90

            return value

        def oracle_search(position, depth, alpha, beta):
            key = (katrina_state_key(position), depth)
            if key in table:
                return table[key]

            if position.meta_status:
                if position.meta_status == ai:
                    return 20_000_000 + depth * 10_000
                if position.meta_status == opp:
                    return -20_000_000 - depth * 10_000
                return 0

            legal = position.legal_moves()
            if not legal or depth == 0:
                value = strategic_score(position, ai)
                table[key] = value
                return value

            ordered = sorted(
                legal,
                key=lambda move: oracle_order(position, move),
                reverse=(position.turn == ai),
            )

            # Keep the most forcing moves at deeper levels. This gives Oracle
            # strong tactical vision without the long pauses of an unrestricted
            # full-game search.
            limit = 12 if depth >= 3 else 18
            ordered = ordered[:limit]

            if position.turn == ai:
                value = -math.inf
                for move in ordered:
                    child = position.clone()
                    child.play(*move)
                    value = max(
                        value,
                        oracle_search(child, depth - 1, alpha, beta),
                    )
                    alpha = max(alpha, value)
                    if beta <= alpha:
                        break
            else:
                value = math.inf
                for move in ordered:
                    child = position.clone()
                    child.play(*move)
                    value = min(
                        value,
                        oracle_search(child, depth - 1, alpha, beta),
                    )
                    beta = min(beta, value)
                    if beta <= alpha:
                        break

            table[key] = value
            return value

        candidates = sorted(
            moves,
            key=lambda move: oracle_order(game, move),
            reverse=True,
        )[:12]

        best_value = -math.inf
        best_moves = []

        # Oracle calculates farther ahead than Nightmare, but unlike Katrina
        # it never stores anything between matches.
        for move in candidates:
            child = game.clone()
            child.play(*move)
            value = oracle_search(child, 4, -math.inf, math.inf)
            if value > best_value:
                best_value = value
                best_moves = [move]
            elif value == best_value:
                best_moves.append(move)

        return best_moves[0] if best_moves else candidates[0]

    # Katrina2: persistent local learning + deeper deterministic search.
    # All memory is stored locally. No APIs, network, accounts, or external
    # services are involved.
    if difficulty == "Katrina2":
        state_key = katrina_state_key(game)

        # If this exact position was seen before, immediately reuse the
        # countermeasure Katrina learned for it.
        learned = KATRINA_MEMORY.get(state_key)
        if isinstance(learned, dict):
            response = learned.get("response")
            if isinstance(response, list) and len(response) == 2:
                remembered = (int(response[0]), int(response[1]))
                if remembered in moves:
                    return remembered

        table = {}

        def search(position, depth, alpha, beta):
            key = (katrina_state_key(position), depth)
            if key in table:
                return table[key]

            if position.meta_status:
                if position.meta_status == ai:
                    return 10_000_000 + depth * 1000
                if position.meta_status == opp:
                    return -10_000_000 - depth * 1000
                return 0

            if depth == 0:
                return strategic_score(position, ai)

            def order(move):
                child = position.clone()
                child.play(*move)
                score = strategic_score(child, ai)

                if child.meta_status == ai:
                    score += 5_000_000
                elif child.meta_status == opp:
                    score -= 5_000_000

                if child.small_status[move[0]] == ai:
                    score += 9000
                elif child.small_status[move[0]] == opp:
                    score -= 8000

                if move[1] == 4:
                    score += 200
                elif move[1] in (0, 2, 6, 8):
                    score += 70

                return score

            ordered = sorted(
                position.legal_moves(),
                key=order,
                reverse=(position.turn == ai),
            )[:16]

            if position.turn == ai:
                value = -math.inf
                for move in ordered:
                    child = position.clone()
                    child.play(*move)
                    value = max(
                        value,
                        search(child, depth - 1, alpha, beta),
                    )
                    alpha = max(alpha, value)
                    if beta <= alpha:
                        break
            else:
                value = math.inf
                for move in ordered:
                    child = position.clone()
                    child.play(*move)
                    value = min(
                        value,
                        search(child, depth - 1, alpha, beta),
                    )
                    beta = min(beta, value)
                    if beta <= alpha:
                        break

            table[key] = value
            return value

        def root_order(move):
            child = game.clone()
            child.play(*move)
            score = strategic_score(child, ai)

            if child.meta_status == ai:
                score += 5_000_000
            elif child.meta_status == opp:
                score -= 5_000_000

            if child.small_status[move[0]] == ai:
                score += 9000

            if move[1] == 4:
                score += 200

            return score

        # Keep Katrina responsive: evaluate fewer root candidates and search
        # three plies. Persistent memory supplies instant answers for repeats.
        candidates = sorted(moves, key=root_order, reverse=True)[:10]

        best_move = candidates[0]
        best_value = -math.inf

        # One ply deeper than Nightmare.
        for move in candidates:
            child = game.clone()
            child.play(*move)
            value = search(child, 3, -math.inf, math.inf)
            if value > best_value:
                best_value = value
                best_move = move

        return best_move

    # Hard: alpha-beta on candidate moves with strategic evaluation.
    # Full Ultimate Tic-Tac-Toe minimax is far too large for a responsive
    # desktop game, so we use a bounded search with a strong evaluator.
    def search(position: UltimateBoard, depth: int, alpha: float, beta: float) -> float:
        if position.meta_status:
            if position.meta_status == ai:
                return 1000000 + depth * 100
            if position.meta_status == opp:
                return -1000000 - depth * 100
            return 0

        if depth == 0:
            return strategic_score(position, ai)

        legal = position.legal_moves()

        # Move ordering: local wins, center, then heuristic.
        def order(move):
            b, c = move
            p = position.clone()
            p.play(b, c)
            value = strategic_score(p, ai)
            if p.small_status[b] == ai:
                value += 1500
            if c == 4:
                value += 40
            return value

        ordered = sorted(legal, key=order, reverse=True)

        if position.turn == ai:
            value = -math.inf
            for move in ordered:
                p = position.clone()
                p.play(*move)
                value = max(value, search(p, depth - 1, alpha, beta))
                alpha = max(alpha, value)
                if beta <= alpha:
                    break
            return value
        else:
            value = math.inf
            for move in ordered:
                p = position.clone()
                p.play(*move)
                value = min(value, search(p, depth - 1, alpha, beta))
                beta = min(beta, value)
                if beta <= alpha:
                    break
            return value

    # Limit hard search to a manageable number of candidate moves.
    def quick_order(move):
        p = game.clone()
        p.play(*move)
        value = strategic_score(p, ai)
        if p.small_status[move[0]] == ai:
            value += 1500
        if p.meta_status == ai:
            value += 100000
        if move[1] == 4:
            value += 30
        return value

    candidates = sorted(moves, key=quick_order, reverse=True)[:12]
    best_value = -math.inf
    best_moves = []
    for move in candidates:
        p = game.clone()
        p.play(*move)
        value = search(p, 2, -math.inf, math.inf)
        if value > best_value:
            best_value = value
            best_moves = [move]
        elif value == best_value:
            best_moves.append(move)

    return random.choice(best_moves)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load_profile() -> Profile:
    try:
        data = json.loads(SAVE_FILE.read_text(encoding="utf-8"))
        return Profile(
            name=str(data.get("name", "Player"))[:24] or "Player",
            points=max(0, int(data.get("points", 100))),
            wins=max(0, int(data.get("wins", 0))),
            losses=max(0, int(data.get("losses", 0))),
            draws=max(0, int(data.get("draws", 0))),
            games=max(0, int(data.get("games", 0))),
            best_streak=max(0, int(data.get("best_streak", 0))),
            current_streak=max(0, int(data.get("current_streak", 0))),
            recent_results=list(data.get("recent_results", []))[-10:],
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return Profile()


def save_profile(profile: Profile) -> None:
    data = {
        "name": profile.name,
        "points": profile.points,
        "wins": profile.wins,
        "losses": profile.losses,
        "draws": profile.draws,
        "games": profile.games,
        "best_streak": profile.best_streak,
        "current_streak": profile.current_streak,
        "recent_results": profile.recent_results[-10:],
    }
    try:
        SAVE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
def _valid_leaderboard_name(name: str) -> bool:
    parts = name.strip().replace(".", "").split()
    return len(parts) == 2 and 2 <= len(parts[0]) <= 20 and len(parts[1]) == 1 and parts[0].isalpha() and parts[1].isalpha()


def _normalize_leaderboard_name(name: str) -> str:
    parts = name.strip().replace(".", "").split()
    return f"{parts[0].capitalize()} {parts[1].upper()}"


def _load_leaderboard_data() -> dict:
    try:
        data = json.loads(LEADERBOARD_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "Nightmare" in data and "Katrina2" in data:
            return data
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass

    # First-run seeded Nightmare history requested for UTT.
    return {
        "Nightmare": [
            {"name": "Caleb M", "beaten": 1},
            {"name": "Malachi K", "beaten": 1},
            {"name": "Caleb H", "beaten": 1},
        ],
        "Katrina2": [],
    }


def _save_leaderboard_data(data: dict) -> None:
    try:
        LEADERBOARD_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def leaderboard_fetch(difficulty: str, limit=50) -> list[dict]:
    data = _load_leaderboard_data()
    rows = data.get(difficulty, [])
    return sorted(rows, key=lambda row: int(row.get("beaten", 0)), reverse=True)[:limit]


def leaderboard_submit(name: str, difficulty: str) -> bool:
    if difficulty not in ("Nightmare", "Katrina2") or not _valid_leaderboard_name(name):
        return False

    name = _normalize_leaderboard_name(name)
    data = _load_leaderboard_data()
    rows = data.setdefault(difficulty, [])

    for row in rows:
        if row.get("name", "").lower() == name.lower():
            row["name"] = name
            row["beaten"] = int(row.get("beaten", 0)) + 1
            _save_leaderboard_data(data)
            return True

    rows.append({"name": name, "beaten": 1})
    _save_leaderboard_data(data)
    return True


def load_ai_rp() -> dict:
    defaults = {name: 0 for name in OFFICIAL_AI_LEVELS}
    try:
        data = json.loads(AI_RP_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for name in OFFICIAL_AI_LEVELS:
                defaults[name] = max(0, int(data.get(name, 0)))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return defaults


def save_ai_rp(data: dict) -> None:
    try:
        AI_RP_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def ai_rank(points: int) -> str:
    current = RANKS[0][1]
    for threshold, name in RANKS:
        if points >= threshold:
            current = name
    return current


def award_ai_rp(winner: str, loser: str) -> int:
    # Only built-in AIs can ever receive RP. Modded/custom AIs are gameplay-only.
    if winner not in OFFICIAL_AI_LEVELS:
        return 0
    gain = AI_RATING.get(loser, {}).get("win", 0)
    if not gain:
        return 0
    AI_RP[winner] = max(0, AI_RP.get(winner, 0) + gain)
    if loser in OFFICIAL_AI_LEVELS:
        AI_RP[loser] = max(0, AI_RP.get(loser, 0) - AI_RATING[loser]["loss"])
    save_ai_rp(AI_RP)
    return gain


def ai_name_list() -> list[str]:
    # Mods may extend this list with AI names. They cannot extend RP logic.
    return list(OFFICIAL_AI_LEVELS)


AI_RP = load_ai_rp()



# GUI
# ---------------------------------------------------------------------------

class UltimateTicTacToeApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.configure(bg=BG)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        initial_w = min(1450, max(1000, sw - 40))
        initial_h = min(900, max(680, sh - 70))
        self.root.geometry(f"{initial_w}x{initial_h}")
        self.root.minsize(900, 620)

        self.profile = load_profile()
        self.game = UltimateBoard()
        self.game_mode = tk.StringVar(value="Player vs AI")
        self.difficulty = tk.StringVar(value="Hard")
        self.ai_x = tk.StringVar(value="Hard")
        self.ai_o = tk.StringVar(value="Nightmare")
        self.ai_queue = tk.IntVar(value=1)
        self.ai_queue_remaining = 0
        self.ai_queue_current = 0
        self.tournament = None
        self.ai_rp = AI_RP
        self._katrina_dirty = False
        self.status_var = tk.StringVar()
        self.info_var = tk.StringVar()

        self.buttons: list[tk.Button] = []
        self.small_frames: list[tk.Frame] = []
        self.game_over = False
        self.ai_busy = False
        self.hover_index = None
        self.current_screen = "home"

        self._build_ui()
        self._bind_shortcuts()
        self.show_home()

    def _build_ui(self):
        # Root containers are switched between Home and Game screens.
        self.home_frame = tk.Frame(self.root, bg=BG)
        self.game_frame = tk.Frame(self.root, bg=BG)

        self._build_home()
        self._build_game()

    def _build_home(self):
        # Responsive home screen: compact enough for 1366x768 laptops while
        # still expanding naturally on larger monitors.
        home = self.home_frame
        home.pack(fill="both", expand=True)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        compact = sh <= 850
        title1 = 26 if compact else 34
        title2 = 22 if compact else 30
        subtitle_font = 9 if compact else 11
        preview_cell = 27 if compact else 42
        preview_gap = 2 if compact else 3
        top_pad = 10 if compact else 28
        preview_bottom = 8 if compact else 20

        tk.Label(
            home, text="ULTIMATE", bg=BG, fg=X_COLOR,
            font=("Segoe UI", title1, "bold")
        ).pack(pady=(top_pad, 0))

        tk.Label(
            home, text="TIC-TAC-TOE", bg=BG, fg=TEXT,
            font=("Segoe UI", title2, "bold")
        ).pack(pady=(0, 2))

        tk.Label(
            home, text="THE 9-BOARD STRATEGY GAME",
            bg=BG, fg=MUTED, font=("Segoe UI", subtitle_font, "bold")
        ).pack(pady=(0, 10 if compact else 25))

        # Decorative preview is deliberately smaller on short screens.
        preview = tk.Frame(
            home, bg=PANEL, highlightbackground=LINE, highlightthickness=2
        )
        preview.pack(pady=(0, preview_bottom))
        for b in range(9):
            cell = tk.Frame(
                preview, width=preview_cell, height=preview_cell,
                bg=CELL_BG, highlightbackground=LINE, highlightthickness=1
            )
            cell.grid(row=b // 3, column=b % 3, padx=preview_gap, pady=preview_gap)
            cell.grid_propagate(False)
            if b in (0, 4, 8):
                tk.Label(
                    cell, text="X" if b != 4 else "O", bg=CELL_BG,
                    fg=X_COLOR if b != 4 else O_COLOR,
                    font=("Segoe UI", 11 if compact else 16, "bold")
                ).place(relx=.5, rely=.5, anchor="center")

        # Settings stay compact and centered.
        settings = tk.Frame(home, bg=BG)
        settings.pack(pady=(0, 7))

        labels = ("GAME MODE", "AI DIFFICULTY")
        for col, label in enumerate(labels):
            tk.Label(
                settings, text=label, bg=BG, fg=MUTED,
                font=("Segoe UI", 8, "bold")
            ).grid(row=0, column=col, padx=6, pady=(0, 2))

        mode_menu = tk.OptionMenu(
            settings, self.game_mode,
            "Player vs AI", "Player vs Player", "AI vs AI"
        )
        self.home_difficulty_menu = tk.OptionMenu(
            settings, self.difficulty, *get_all_ai_names()
        )
        for menu in (mode_menu, self.home_difficulty_menu):
            menu.configure(
                bg=PANEL_2, fg=TEXT, activebackground=ACTIVE,
                activeforeground=TEXT, highlightthickness=0,
                relief="flat", font=("Segoe UI", 9), width=14
            )
            menu["menu"].configure(
                bg=PANEL_2, fg=TEXT, activebackground=ACTIVE
            )
        mode_menu.grid(row=1, column=0, padx=6)
        self.home_difficulty_menu.grid(row=1, column=1, padx=6)

        self.ai_x_menu = tk.OptionMenu(settings, self.ai_x, *get_all_ai_names())
        self.ai_o_menu = tk.OptionMenu(settings, self.ai_o, *get_all_ai_names())
        for menu in (self.ai_x_menu, self.ai_o_menu):
            menu.configure(
                bg=PANEL_2, fg=TEXT, activebackground=ACTIVE,
                activeforeground=TEXT, highlightthickness=0,
                relief="flat", font=("Segoe UI", 9), width=14
            )
            menu["menu"].configure(bg=PANEL_2, fg=TEXT, activebackground=ACTIVE)

        tk.Label(settings, text="AI X", bg=BG, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).grid(row=2, column=0, padx=6, pady=(5, 2))
        tk.Label(settings, text="AI O", bg=BG, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).grid(row=2, column=1, padx=6, pady=(5, 2))
        self.ai_x_menu.grid(row=3, column=0, padx=6)
        self.ai_o_menu.grid(row=3, column=1, padx=6)

        tk.Label(settings, text="AI QUEUE", bg=BG, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).grid(row=4, column=0, padx=6, pady=(5, 2))
        self.ai_queue_spin = tk.Spinbox(
            settings, from_=1, to=25, textvariable=self.ai_queue,
            width=14, bg=PANEL_2, fg=TEXT, buttonbackground=ACTIVE,
            relief="flat", justify="center"
        )
        self.ai_queue_spin.grid(row=5, column=0, padx=6)
        tk.Label(
            settings, text="AI-vs-AI matches back-to-back", bg=BG, fg=MUTED,
            font=("Segoe UI", 8)
        ).grid(row=5, column=1, padx=6)

        def update_home_mode(*_):
            mode = self.game_mode.get()
            self.home_difficulty_menu.configure(
                state="normal" if mode == "Player vs AI" else "disabled"
            )
            ai_state = "normal" if mode == "AI vs AI" else "disabled"
            self.ai_x_menu.configure(state=ai_state)
            self.ai_o_menu.configure(state=ai_state)
            self.ai_queue_spin.configure(state=ai_state)
            if mode == "AI vs AI" and self.ai_x.get() == self.ai_o.get():
                for choice in get_all_ai_names():
                    if choice != self.ai_x.get():
                        self.ai_o.set(choice)
                        break

        self.game_mode.trace_add("write", update_home_mode)
        self.ai_x.trace_add("write", update_home_mode)
        self.ai_o.trace_add("write", update_home_mode)
        update_home_mode()

        # Compact AI ranking strip.
        ai_panel = tk.Frame(home, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        ai_panel.pack(fill="x", padx=24, pady=(3, 7))
        tk.Label(
            ai_panel, text="AI RANKINGS", bg=PANEL, fg=GOLD,
            font=("Segoe UI", 9, "bold")
        ).pack(pady=(4, 1))
        ranking_text = "   ".join(
            f"{name}: {AI_RP.get(name, 0)} RP ({ai_rank(AI_RP.get(name, 0))})"
            for name in OFFICIAL_AI_LEVELS
        )
        tk.Label(
            ai_panel, text=ranking_text, bg=PANEL, fg=TEXT,
            font=("Segoe UI", 7 if compact else 8)
        ).pack(padx=8, pady=(0, 4))

        # All major features get their own button. Three columns keeps the
        # entire feature hub visible on short screens.
        feature_box = tk.LabelFrame(
            home, text="FEATURES", bg=PANEL, fg=TEXT,
            font=("Segoe UI", 9, "bold")
        )
        feature_box.pack(fill="x", padx=24, pady=(2, 5))
        actions = [
            ("PLAY", self.show_game),
            ("PLAYER VS PLAYER", self.start_pvp),
            ("AI VS AI", self.start_aivai),
            ("TOURNAMENT", self.open_tournament),
            ("AI QUEUE", self.start_aivai),
            ("GLOBAL LEADERBOARD", self.show_leaderboard),
            ("IMPORT AI", self.import_ai),
            ("HOW TO PLAY", self.show_rules),
            ("STATS", self.show_stats),
        ]
        for i, (label, command) in enumerate(actions):
            r, c = divmod(i, 3)
            tk.Button(
                feature_box, text=label, command=command,
                bg=PANEL_2, fg=TEXT, activebackground=ACTIVE,
                activeforeground=TEXT, relief="flat", bd=0,
                font=("Segoe UI", 8 if compact else 9, "bold"),
                cursor="hand2", padx=5, pady=5 if compact else 7
            ).grid(row=r, column=c, padx=4, pady=3, sticky="ew")
        for c in range(3):
            feature_box.grid_columnconfigure(c, weight=1)

        tk.Button(
            home, text="EXIT", command=self.root.destroy,
            bg=PANEL_2, fg=TEXT, activebackground=HOVER,
            activeforeground=TEXT, relief="flat", bd=0,
            font=("Segoe UI", 8 if compact else 9, "bold"),
            cursor="hand2", padx=14, pady=3
        ).pack(pady=(2, 2))

        tk.Label(
            home, text="F2  New Game     •     ESC  Exit",
            bg=BG, fg=MUTED, font=("Segoe UI", 7 if compact else 8)
        ).pack(pady=(0, 3))

    def _home_button(self, parent, text, command, primary=False):
        button = tk.Button(
            parent, text=text, command=command,
            bg=ACTIVE if primary else PANEL_2,
            fg=TEXT, activebackground=HOVER,
            activeforeground=TEXT, relief="flat", bd=0,
            font=("Segoe UI", 12, "bold"), cursor="hand2",
            width=18
        )
        button.pack(pady=3, ipady=5)

    def _build_game(self):
        game_screen = self.game_frame

        top = tk.Frame(game_screen, bg=BG)
        top.pack(fill="x", padx=24, pady=(18, 10))

        tk.Button(
            top, text="‹ HOME", command=self.show_home,
            bg=PANEL_2, fg=TEXT, activebackground=ACTIVE,
            activeforeground=TEXT, relief="flat", bd=0,
            font=("Segoe UI", 10, "bold"), cursor="hand2"
        ).pack(side="left", padx=(0, 15), ipadx=8, ipady=5)

        tk.Label(
            top, text="ULTIMATE TIC-TAC-TOE",
            bg=BG, fg=TEXT, font=("Segoe UI", 20, "bold")
        ).pack(side="left")

        self.rank_label = tk.Label(
            top, bg=BG, fg=GOLD, font=("Segoe UI", 12, "bold")
        )
        self.rank_label.pack(side="right", padx=10)

        self.queue_label = tk.Label(top, bg=BG, fg=GOLD, font=("Segoe UI", 10, "bold"), text="Match 0/0")
        self.queue_label.pack(side="right", padx=12)

        main = tk.Frame(game_screen, bg=BG)
        main.pack(fill="both", expand=True, padx=18, pady=6)

        left = tk.Frame(
            main, bg=PANEL, highlightbackground=LINE, highlightthickness=1
        )
        left.pack(side="left", fill="both", expand=True)

        right = tk.Frame(
            main, bg=PANEL, width=285,
            highlightbackground=LINE, highlightthickness=1
        )
        right.pack(side="right", fill="y", padx=(14, 0))
        right.pack_propagate(False)

        # Scrollable sidebar so ranking requirements and future stats can grow
        # without squeezing the board horizontally.
        sidebar_canvas = tk.Canvas(
            right, bg=PANEL, highlightthickness=0, bd=0
        )
        sidebar_scrollbar = tk.Scrollbar(
            right,
            orient="vertical",
            command=sidebar_canvas.yview,
            width=16,
            troughcolor=PANEL_2,
            bg=LINE,
            activebackground=TEXT,
            relief="flat",
            bd=0,
        )
        sidebar_content = tk.Frame(sidebar_canvas, bg=PANEL)

        sidebar_window = sidebar_canvas.create_window(
            (0, 0), window=sidebar_content, anchor="nw"
        )
        sidebar_canvas.configure(yscrollcommand=sidebar_scrollbar.set)

        sidebar_canvas.pack(side="left", fill="both", expand=True)
        sidebar_scrollbar.pack(side="right", fill="y")

        def update_sidebar_scroll(event=None):
            sidebar_canvas.configure(scrollregion=sidebar_canvas.bbox("all"))
            sidebar_canvas.itemconfigure(
                sidebar_window, width=sidebar_canvas.winfo_width()
            )

        sidebar_content.bind("<Configure>", update_sidebar_scroll)
        sidebar_canvas.bind("<Configure>", update_sidebar_scroll)

        def sidebar_wheel(event):
            sidebar_canvas.yview_scroll(
                -1 * int(event.delta / 120), "units"
            )

        sidebar_canvas.bind("<MouseWheel>", sidebar_wheel)
        sidebar_content.bind("<MouseWheel>", sidebar_wheel)

        def bind_sidebar_wheel(widget):
            widget.bind("<MouseWheel>", sidebar_wheel, add="+")
            widget.bind("<Button-4>", sidebar_wheel, add="+")
            widget.bind("<Button-5>", sidebar_wheel, add="+")
            for child in widget.winfo_children():
                bind_sidebar_wheel(child)

        right = sidebar_content

        self.board_canvas = tk.Canvas(left, bg=PANEL, highlightthickness=0)
        self.board_canvas.pack(fill="both", expand=True, padx=10, pady=10)

        self.board_holder = tk.Frame(self.board_canvas, bg=PANEL)
        self.canvas_window = self.board_canvas.create_window(
            0, 0, window=self.board_holder, anchor="center"
        )
        self.board_canvas.bind("<Configure>", self._center_board)

        for b in range(9):
            # Thicker outer grid spacing makes the 3x3 meta-grid obvious.
            outer_pad = 7
            frame = tk.Frame(
                self.board_holder, bg=CELL_BG,
                highlightbackground=LINE, highlightthickness=3
            )
            frame.grid(
                row=b // 3, column=b % 3,
                padx=5, pady=5,
                ipadx=2, ipady=2
            )
            self.small_frames.append(frame)

            for c in range(9):
                idx = b * 9 + c

                # Internal cell grid.
                button = tk.Button(
                    frame,
                    text="",
                    width=3,
                    height=1,
                    font=("Segoe UI", 17, "bold"),
                    bg=CELL_BG,
                    fg=TEXT,
                    activebackground=HOVER,
                    activeforeground=TEXT,
                    relief="solid",
                    bd=1,
                    highlightthickness=0,
                    cursor="hand2",
                    command=lambda board=b, cell=c: self.human_move(board, cell),
                )
                button.grid(
                    row=c // 3, column=c % 3,
                    padx=0, pady=0, sticky="nsew"
                )
                frame.grid_rowconfigure(c // 3, weight=1)
                frame.grid_columnconfigure(c % 3, weight=1)
                button.bind("<Enter>", lambda e, i=idx: self._hover(i, True))
                button.bind("<Leave>", lambda e, i=idx: self._hover(i, False))
                self.buttons.append(button)

        # Sidebar
        tk.Label(
            right, text="MATCH", bg=PANEL, fg=MUTED,
            font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", padx=20, pady=(22, 3))

        self.status_label = tk.Label(
            right, textvariable=self.status_var, bg=PANEL, fg=TEXT,
            font=("Segoe UI", 14, "bold"), wraplength=210, justify="left"
        )
        self.status_label.pack(anchor="w", padx=20, pady=(0, 18))

        self.info_label = tk.Label(
            right, textvariable=self.info_var, bg=PANEL, fg=MUTED,
            font=("Segoe UI", 10), wraplength=210, justify="left"
        )
        self.info_label.pack(anchor="w", padx=20, pady=(0, 18))

        tk.Label(right, text="MATCH SETTINGS", bg=PANEL, fg=MUTED, font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=20)
        self.match_settings_label = tk.Label(right, bg=PANEL_2, fg=TEXT, font=("Segoe UI", 10, "bold"), justify="left", wraplength=210)
        self.match_settings_label.pack(fill="x", padx=20, pady=(5, 18), ipady=8)

        self._sidebar_button(right, "NEW GAME", self.new_game)
        self._sidebar_button(right, "CHANGE NAME", self.change_name)
        self._sidebar_button(right, "RESET STATS", self.reset_stats)

        stats = tk.Frame(right, bg=PANEL_2)
        stats.pack(fill="x", padx=20, pady=(20, 0))

        tk.Label(
            stats, text="RANKING", bg=PANEL_2, fg=GOLD,
            font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", padx=12, pady=(12, 4))

        self.stats_label = tk.Label(
            stats, bg=PANEL_2, fg=TEXT, font=("Consolas", 10),
            justify="left"
        )
        self.stats_label.pack(anchor="w", padx=12, pady=(0, 12))

        requirements = tk.Frame(right, bg=PANEL_2)
        requirements.pack(fill="x", padx=20, pady=(14, 0))

        tk.Label(
            requirements, text="RANK REQUIREMENTS",
            bg=PANEL_2, fg=GOLD,
            font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", padx=12, pady=(12, 6))

        self.rank_requirements_label = tk.Label(
            requirements, bg=PANEL_2, fg=TEXT,
            font=("Consolas", 9), justify="left"
        )
        self.rank_requirements_label.pack(
            anchor="w", padx=12, pady=(0, 12)
        )

        rewards = tk.Frame(right, bg=PANEL_2)
        rewards.pack(fill="x", padx=20, pady=(14, 20))

        tk.Label(
            rewards, text="AI RP REWARDS",
            bg=PANEL_2, fg=GOLD,
            font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", padx=12, pady=(12, 6))

        self.ai_rewards_label = tk.Label(
            rewards, bg=PANEL_2, fg=TEXT,
            font=("Consolas", 9), justify="left"
        )
        self.ai_rewards_label.pack(
            anchor="w", padx=12, pady=(0, 12)
        )

        bottom = tk.Frame(game_screen, bg=BG)
        bottom.pack(fill="x", padx=24, pady=(0, 14))
        tk.Label(
            bottom,
            text="The small board you play in determines where the opponent must play next.",
            bg=BG, fg=MUTED, font=("Segoe UI", 9)
        ).pack(side="left")

        self.root.after_idle(lambda: bind_sidebar_wheel(sidebar_content))

    def start_pvp(self):
        self.game_mode.set("Player vs Player")
        self.show_game()

    def start_aivai(self):
        self.game_mode.set("AI vs AI")
        self.show_game()

    def import_ai(self):
        filename = filedialog.askopenfilename(parent=self.root, title="Import AI Python File", filetypes=[("Python files", "*.py")])
        if not filename: return
        mods = Path(__file__).resolve().parent / "Mods"
        mods.mkdir(exist_ok=True)
        try:
            destination = mods / Path(filename).name
            destination.write_bytes(Path(filename).read_bytes())
            reload_ai_mods()
            for menu, var in ((self.home_difficulty_menu, self.difficulty), (self.ai_x_menu, self.ai_x), (self.ai_o_menu, self.ai_o)):
                menu["menu"].delete(0, "end")
                for name in get_all_ai_names(): menu["menu"].add_command(label=name, command=lambda n=name, v=var: v.set(n))
            messagebox.showinfo("AI Imported", f"Imported {destination.name}. The AI is now available in the difficulty menus.", parent=self.root)
        except OSError as exc:
            messagebox.showerror("Import Failed", str(exc), parent=self.root)

    def open_tournament(self):
        win = tk.Toplevel(self.root); win.title("UTT — Christmas Tree Tournament"); win.configure(bg=BG); win.geometry("1050x760"); win.minsize(850,620)
        tk.Label(win,text="🎄 CHRISTMAS TREE TOURNAMENT",bg=BG,fg=GOLD,font=("Segoe UI",22,"bold")).pack(pady=(16,2))
        tk.Label(win,text="8 → 4 → 2 → 1",bg=BG,fg=TEXT,font=("Segoe UI",13,"bold")).pack(pady=(0,12))
        frame=tk.Frame(win,bg=BG); frame.pack(fill="both",expand=True,padx=15,pady=8)
        slots=[]; names=["Player"] + list(get_all_ai_names())
        for i in range(8):
            card=tk.Frame(frame,bg=PANEL,bd=1,relief="solid"); card.grid(row=i//2,column=i%2,padx=8,pady=8,sticky="nsew")
            tk.Label(card,text=f"ROUND 1 • SLOT {i+1}",bg=PANEL,fg=MUTED,font=("Segoe UI",9,"bold")).pack(pady=(8,3))
            var=tk.StringVar(value="Player"); tk.OptionMenu(card,var,*names).pack(fill="x",padx=12,pady=8); slots.append(var)
        for c in range(2): frame.grid_columnconfigure(c,weight=1)
        def begin():
            self.tournament={"slots": [v.get() for v in slots], "round":1, "index":0, "winners":[]}
            win.destroy(); self.run_tournament_match()
        tk.Button(win,text="START TOURNAMENT",command=begin,bg=GOLD,fg=BG,font=("Segoe UI",11,"bold"),padx=25,pady=8).pack(pady=12)

    def run_tournament_match(self):
        t=self.tournament
        if not t: return
        participants=t["slots"] if t["round"]==1 else t["winners"]
        if t["index"] >= len(participants):
            if len(t["winners"]) == 1:
                winner=t["winners"][0]; self.tournament=None; messagebox.showinfo("Tournament Champion",f"🏆 {winner} won the tournament!",parent=self.root); self.show_home(); return
            t["slots"]=t["winners"]; t["winners"]=[]; t["round"]+=1; t["index"]=0; participants=t["slots"]
        a,b=participants[t["index"]],participants[t["index"]+1]
        if b == "Player" and a != "Player": a,b=b,a
        t["current"]=(a,b)
        t["index"]+=2
        self._tournament_start_pair(a,b)

    def _tournament_start_pair(self,a,b):
        if a=="Player" and b=="Player": self.game_mode.set("Player vs Player")
        elif a=="Player" or b=="Player":
            self.game_mode.set("Player vs AI"); self.difficulty.set(b if a=="Player" else a)
        else:
            self.game_mode.set("AI vs AI"); self.ai_x.set(a); self.ai_o.set(b)
        self.show_game()

    def show_home(self):
        self.current_screen = "home"
        self.game_frame.pack_forget()
        self.home_frame.pack(fill="both", expand=True)

    def show_game(self):
        self.current_screen = "game"
        self.home_frame.pack_forget()
        self.game_frame.pack(fill="both", expand=True)
        self.ai_queue_remaining = max(1, int(self.ai_queue.get()))
        self.ai_queue_current = 1
        self.new_game()

    def show_leaderboard(self):
        if hasattr(self, "_temporary_screen") and self._temporary_screen is not None:
            self._temporary_screen.destroy()

        self.current_screen = "leaderboard"
        self.home_frame.pack_forget()
        screen = tk.Frame(self.root, bg=BG)
        screen.pack(fill="both", expand=True)
        self._temporary_screen = screen

        tk.Label(
            screen, text="GLOBAL LEADERBOARD", bg=BG, fg=GOLD,
            font=("Segoe UI", 30, "bold")
        ).pack(pady=(35, 5))
        tk.Label(
            screen, text="Human victories • first name + last initial",
            bg=BG, fg=MUTED, font=("Segoe UI", 11)
        ).pack(pady=(0, 15))

        notebook = ttk.Notebook(screen)
        notebook.pack(fill="both", expand=True, padx=70, pady=10)

        for difficulty in ("Nightmare", "Katrina2"):
            tab = tk.Frame(notebook, bg=PANEL)
            notebook.add(tab, text=difficulty)
            rows = leaderboard_fetch(difficulty, 100)

            tk.Label(
                tab, text=f"{difficulty} beaten", bg=PANEL, fg=TEXT,
                font=("Segoe UI", 16, "bold")
            ).pack(pady=(20, 12))

            header = tk.Frame(tab, bg=PANEL_2)
            header.pack(fill="x", padx=30)
            for col, label in enumerate(("RANK", "NAME", "TIMES BEATEN")):
                tk.Label(
                    header, text=label, bg=PANEL_2, fg=TEXT,
                    font=("Segoe UI", 10, "bold"), width=(10, 24, 18)[col]
                ).grid(row=0, column=col, padx=8, pady=8)

            if not rows:
                tk.Label(
                    tab, text="Nobody has beaten Katrina yet.",
                    bg=PANEL, fg=MUTED, font=("Segoe UI", 12)
                ).pack(pady=40)
            else:
                for rank, row in enumerate(rows, 1):
                    line = tk.Frame(tab, bg=PANEL)
                    line.pack(fill="x", padx=30)
                    for col, value in enumerate((
                        str(rank), row.get("name", "Player"), str(row.get("beaten", 0))
                    )):
                        tk.Label(
                            line, text=value, bg=PANEL, fg=TEXT,
                            font=("Segoe UI", 11),
                            width=(10, 24, 18)[col]
                        ).grid(row=0, column=col, padx=8, pady=6)

        self._home_button(screen, "‹ BACK", self.show_home)

    def show_rules(self):
        if hasattr(self, "_temporary_screen") and self._temporary_screen is not None:
            self._temporary_screen.destroy()
        self.current_screen = "rules"
        self.home_frame.pack_forget()

        rules = tk.Frame(self.root, bg=BG)
        rules.pack(fill="both", expand=True)
        self._temporary_screen = rules

        tk.Label(
            rules, text="HOW TO PLAY", bg=BG, fg=TEXT,
            font=("Segoe UI", 30, "bold")
        ).pack(pady=(55, 25))

        text = (
            "ULTIMATE TIC-TAC-TOE\n\n"
            "The game has 9 small Tic-Tac-Toe boards arranged in a 3×3 grid.\n\n"
            "1. Your first move can be anywhere.\n"
            "2. The small square you choose determines the small board your "
            "opponent must play in next.\n"
            "3. If that destination board is already won or drawn, the opponent "
            "may choose any unfinished board.\n"
            "4. Win 3 small boards in a row to win the entire match.\n\n"
            "GAME MODES\n"
            "Player vs AI: choose Easy, Medium, Hard, Nightmare, Oracle, or Katrina2 from the home screen.\n"
            "Player vs Player: two local players share the same keyboard/mouse.\n"
            "AI vs AI: choose two different AI levels and watch them play automatically.\n"
            "Katrina2: persistent-learning final AI tier with local countermeasure memory.\n\n"
            "RANKING\n"
            "Only Player vs AI matches affect ranking points and ranked statistics.\n"
            "Your ranking and match statistics are saved automatically."
        )

        tk.Label(
            rules, text=text, bg=PANEL, fg=TEXT,
            font=("Segoe UI", 12), justify="left",
            padx=35, pady=30, wraplength=700
        ).pack(padx=30)

        tk.Button(
            rules, text="BACK TO HOME", command=lambda: self._close_info_screen(rules),
            bg=PANEL_2, fg=TEXT, activebackground=ACTIVE,
            activeforeground=TEXT, relief="flat", bd=0,
            font=("Segoe UI", 11, "bold"), cursor="hand2"
        ).pack(pady=30, ipadx=15, ipady=8)

    def show_stats(self):
        self.current_screen = "stats"
        self.home_frame.pack_forget()

        stats_screen = tk.Frame(self.root, bg=BG)
        stats_screen.pack(fill="both", expand=True)

        tk.Label(
            stats_screen, text="YOUR STATS", bg=BG, fg=TEXT,
            font=("Segoe UI", 30, "bold")
        ).pack(pady=(55, 25))

        card = tk.Frame(
            stats_screen, bg=PANEL,
            highlightbackground=LINE, highlightthickness=1
        )
        card.pack(padx=30, ipadx=45, ipady=30)

        tk.Label(
            card, text=self.profile.name, bg=PANEL, fg=GOLD,
            font=("Segoe UI", 20, "bold")
        ).pack(pady=(10, 15))

        stats_text = (
            f"RANK\n{self.profile.rank}\n\n"
            f"RANKING POINTS\n{self.profile.points} RP\n\n"
            f"WINS        {self.profile.wins}\n"
            f"LOSSES      {self.profile.losses}\n"
            f"DRAWS       {self.profile.draws}\n"
            f"TOTAL GAMES {self.profile.games}\n\n"
            f"CURRENT STREAK  {self.profile.current_streak}\n"
            f"BEST STREAK     {self.profile.best_streak}\n\n"
            f"LAST 10  {''.join(self.profile.recent_results) or '—'}"
        )

        tk.Label(
            card, text=stats_text, bg=PANEL, fg=TEXT,
            font=("Consolas", 13), justify="center"
        ).pack()

        tk.Button(
            stats_screen, text="BACK TO HOME",
            command=lambda: self._close_info_screen(stats_screen),
            bg=PANEL_2, fg=TEXT, activebackground=ACTIVE,
            activeforeground=TEXT, relief="flat", bd=0,
            font=("Segoe UI", 11, "bold"), cursor="hand2"
        ).pack(pady=30, ipadx=15, ipady=8)

        self._temporary_screen = stats_screen

    def _close_info_screen(self, screen):
        screen.destroy()
        self._temporary_screen = None
        self.show_home()

    def _sidebar_button(self, parent, text, command):
        button = tk.Button(
            parent, text=text, command=command,
            bg=PANEL_2, fg=TEXT, activebackground=ACTIVE,
            activeforeground=TEXT, relief="flat", bd=0,
            font=("Segoe UI", 10, "bold"), cursor="hand2"
        )
        button.pack(fill="x", padx=20, pady=4, ipady=7)

    def _bind_shortcuts(self):
        self.root.bind("<F2>", lambda e: self.new_game() if self.current_screen == "game" else None)
        self.root.bind("<Escape>", lambda e: self.show_home() if self.current_screen != "home" else self.root.destroy())

    def _center_board(self, event=None):
        self.board_canvas.coords(
            self.canvas_window,
            self.board_canvas.winfo_width() / 2,
            self.board_canvas.winfo_height() / 2,
        )

    def _hover(self, index: int, entering: bool):
        if self.game_over or self.ai_busy or self.game_mode.get() == "AI vs AI":
            return
        if entering:
            self.hover_index = index
        elif self.hover_index == index:
            self.hover_index = None
        self.render()

    def change_name(self):
        name = simpledialog.askstring(
            "Player Name", "Enter your player name:",
            initialvalue=self.profile.name, parent=self.root
        )
        if name is not None:
            name = name.strip()[:24]
            if name:
                self.profile.name = name
                save_profile(self.profile)
                self.render()

    def reset_stats(self):
        if messagebox.askyesno(
            "Reset Stats",
            "Reset ranking points, wins, losses, draws and streaks?"
        ):
            self.profile = Profile(name=self.profile.name)
            save_profile(self.profile)
            self.new_game()

    def _teach_katrina(self, position: UltimateBoard, move: tuple[int, int]) -> None:
        # Learn the response to every move in every match. The pending state is
        # intentionally independent of the selected AI, so Katrina2 learns from
        # PvP, AI-vs-AI, and games where she never participates.
        state = katrina_state_key(position)
        pending = getattr(self, "_katrina_pending", None)
        if pending:
            old_state, old_move = pending
            entry = KATRINA_MEMORY.setdefault(old_state, {})
            entry["opponent_move"] = [old_move[0], old_move[1]]
            entry["response"] = [move[0], move[1]]
            self._katrina_dirty = True
        self._katrina_pending = (state, move)
        self._katrina_dirty = True

    def _save_katrina_learning(self) -> None:
        if getattr(self, "_katrina_dirty", False):
            save_katrina_memory(KATRINA_MEMORY)
            self._katrina_dirty = False

    def new_game(self):
        self._katrina_pending = None
        self.game = UltimateBoard()
        self.game_over = False
        self.ai_busy = False

        if self.game_mode.get() == "Player vs Player":
            self.status_var.set("Player X's turn")
            self.info_var.set(
                "Player X goes first. The move determines the board Player O must play on."
            )
        elif self.game_mode.get() == "AI vs AI":
            if self.ai_x.get() == self.ai_o.get():
                # Defensive guard even if the UI was bypassed.
                choices = [*get_all_ai_names()]
                for choice in choices:
                    if choice != self.ai_x.get():
                        self.ai_o.set(choice)
                        break
            self.status_var.set(f"{self.ai_x.get()} X vs {self.ai_o.get()} O")
            self.info_var.set("AI vs AI is running automatically.")
            self.ai_busy = True
            self.root.after(120, self.do_ai_vs_ai_move)
        elif self.game.turn == "X":
            self.status_var.set("Your turn — X")
            target = "any unfinished board" if self.game.next_board is None else f"Board {self.game.next_board + 1}"
            self.info_var.set(f"You must play on: {target}.")
        else:
            self.status_var.set("Your turn — X")
            self.info_var.set(
                f"You may play anywhere on the first move. After that, "
                f"your move determines the board the {self.difficulty.get()} AI "
                f"must play on."
            )

        self.render()

    def human_move(self, board: int, cell: int):
        if self.game_over or self.ai_busy:
            return

        if (
            self.game_mode.get() == "Player vs AI"
            and self.game.turn != "X"
        ):
            return

        if (board, cell) not in self.game.legal_moves():
            return

        # Every match teaches Katrina. Store the move before applying it;
        # Katrina can use the state/move pair later without doing an expensive
        # search during every opponent move.
        self._teach_katrina(self.game, (board, cell))

        self.game.play(board, cell)
        self.after_move()

        if (
            not self.game_over
            and self.game_mode.get() == "Player vs AI"
            and self.game.turn == "O"
        ):
            self.ai_busy = True
            self.status_var.set(
                f"AI is thinking ({self.difficulty.get()})…"
            )
            self.render()
            self.root.after(120, self.do_ai_move)

    def do_ai_move(self):
        if self.game_over:
            self.ai_busy = False
            return

        try:
            selected_ai = self.difficulty.get()
            move = get_ai_move(self.game, selected_ai)
        except Exception as exc:
            self.ai_busy = False
            messagebox.showerror("AI Error", f"The AI could not choose a move:\n{exc}")
            return

        if move not in self.game.legal_moves():
            # Defensive fallback: never allow an AI bug to make an illegal move.
            legal = self.game.legal_moves()
            if not legal:
                self.ai_busy = False
                self.after_move()
                return
            move = random.choice(legal)

        self.game.play(*move)
        if hasattr(self.game, "_katrina_observed_move"):
            delattr(self.game, "_katrina_observed_move")
        self.ai_busy = False
        self.after_move()

    def do_ai_vs_ai_move(self):
        if self.game_over or self.game_mode.get() != "AI vs AI":
            self.ai_busy = False
            return

        current_ai = self.ai_x.get() if self.game.turn == "X" else self.ai_o.get()
        moving_player = self.game.turn

        # Katrina learns from every AI-vs-AI match, whether or not she is playing.
        try:
            move = get_ai_move(self.game, current_ai)
        except Exception as exc:
            self.ai_busy = False
            messagebox.showerror("AI vs AI Error", f"The AI could not choose a move:\n{exc}", parent=self.root)
            return

        legal = self.game.legal_moves()
        if move not in legal:
            move = random.choice(legal) if legal else None
        if move is not None:
            self._teach_katrina(self.game, move)
        if move is None:
            self.after_move()
            return

        self.game.play(*move)
        self.status_var.set(f"{self.ai_x.get()} X vs {self.ai_o.get()} O")
        self.info_var.set(f"{current_ai} ({moving_player}) just moved.")
        self.after_move()

        if not self.game_over:
            self.ai_busy = True
            self.root.after(40, self.do_ai_vs_ai_move)

    def after_move(self):
        if self.game.meta_status:
            self.finish_game(self.game.meta_status)
            return

        if not self.game.legal_moves():
            self.finish_game("D")
            return

        target = "any unfinished board" if self.game.next_board is None else f"Board {self.game.next_board + 1}"
        if self.game_mode.get() == "Player vs Player":
            player = self.game.turn
            self.status_var.set(f"Player {player}'s turn")
            self.info_var.set(f"Player {player} must play on: {target}.")
        elif self.game_mode.get() == "AI vs AI":
            current_ai = self.ai_x.get() if self.game.turn == "X" else self.ai_o.get()
            self.status_var.set(f"{self.ai_x.get()} X vs {self.ai_o.get()} O")
            self.info_var.set(f"{current_ai} is choosing the next move.")
        elif self.game.turn == "X":
            self.status_var.set("Your turn — X")
            self.info_var.set(f"You must play on: {target}.")
        else:
            self.status_var.set("AI's turn — O")
            self.info_var.set(f"The {self.difficulty.get()} AI controls O.")

        self.render()

    def finish_game(self, result: str):
        self.game_over = True

        if self.game_mode.get() == "AI vs AI":
            self._save_katrina_learning()
            winner = None if result == "D" else (self.ai_x.get() if result == "X" else self.ai_o.get())
            loser = None if winner is None else (self.ai_o.get() if result == "X" else self.ai_x.get())

            gained = award_ai_rp(winner, loser) if winner else 0

            # Continue the requested AI queue without giving the human RP.
            if self.ai_queue_remaining > 1:
                self.ai_queue_remaining -= 1
                self.ai_queue_current += 1
                self.ai_busy = True
                self.root.after(80, self.new_game)
                return

            self.ai_queue_remaining = 0
            self.ai_busy = False
            self.render()
            if result == "D":
                message = f"{self.ai_x.get()} vs {self.ai_o.get()} drew.\nNo player RP."
            else:
                message = (
                    f"{winner} won! +{gained} AI RP\n"
                    f"{winner}: {AI_RP.get(winner, 0)} AI RP • {ai_rank(AI_RP.get(winner, 0))}\n"
                    "No player RP from AI vs AI."
                )
            self.root.after(100, lambda: messagebox.showinfo("AI vs AI Complete", message, parent=self.root))
            return

        if self.game_mode.get() == "Player vs Player":
            self._save_katrina_learning()
            message = (
                "Player vs Player ended in a draw.\nNo RP change."
                if result == "D"
                else f"Player {result} won!\nNo RP change in local PvP."
            )
            self.render()
            self.root.after(80, lambda: messagebox.showinfo("Match Complete", message, parent=self.root))
            return

        if self.tournament is not None:
            winner = "Player" if result == "X" else ("AI" if result == "O" else None)
            if winner is not None:
                self.tournament["winners"].append(self.tournament["current"][0] if result == "X" else self.tournament["current"][1])
            else:
                self.tournament["winners"].append(self.tournament["current"][0])
            self.ai_busy = False
            self.render()
            self.root.after(150, self.run_tournament_match)
            return

        # Player-vs-AI is the only mode allowed to award player RP.
        ai_level = self.difficulty.get()
        if ai_level not in OFFICIAL_AI_LEVELS:
            self._save_katrina_learning()
            self.render()
            return

        rating = AI_RATING[ai_level]
        if result == "X":
            gained = rating["win"]
            self.profile.points += gained
            self.profile.wins += 1
            self.profile.games += 1
            self.profile.current_streak += 1
            self.profile.best_streak = max(self.profile.best_streak, self.profile.current_streak)
            self.profile.recent_results.append("W")
            message = f"You won against {ai_level}! +{gained} RP\nRank: {self.profile.rank}"

            if ai_level in ("Nightmare", "Katrina2"):
                while True:
                    player_name = simpledialog.askstring(
                        "Leaderboard Entry",
                        f"You defeated {ai_level}!\n\nEnter First Name + Last Initial (example: Caleb M):",
                        initialvalue="",
                        parent=self.root,
                    )
                    if player_name is None:
                        player_name = "Player X"
                    if _valid_leaderboard_name(player_name):
                        leaderboard_submit(player_name, ai_level)
                        break
                    messagebox.showwarning(
                        "Invalid Name",
                        "Use your first name and last initial, such as: Caleb M",
                        parent=self.root,
                    )
        elif result == "O":
            lost = rating["loss"]
            self.profile.points = max(0, self.profile.points - lost)
            self.profile.losses += 1
            self.profile.games += 1
            self.profile.current_streak = 0
            self.profile.recent_results.append("L")
            message = f"{ai_level} AI won. -{lost} RP\nRank: {self.profile.rank}"
        else:
            self.profile.points += 5
            self.profile.draws += 1
            self.profile.games += 1
            self.profile.current_streak = 0
            self.profile.recent_results.append("D")
            message = f"Draw. +5 RP\nRank: {self.profile.rank}"

        self.profile.recent_results = self.profile.recent_results[-10:]
        self._save_katrina_learning()
        save_profile(self.profile)
        self.render()
        self.root.after(80, lambda: messagebox.showinfo("Match Complete", message, parent=self.root))

    def render(self):
        if hasattr(self, "queue_label"):
            total=max(1,int(self.ai_queue.get())); current=max(1,int(getattr(self,"ai_queue_current",1)))
            self.queue_label.configure(text=f"Match {current}/{total}" if self.game_mode.get()=="AI vs AI" else "")
        legal = set(self.game.legal_moves())
        allowed_boards = {
            b for b, _ in legal
        }

        for b in range(9):
            frame = self.small_frames[b]
            status = self.game.small_status[b]

            if status == "X":
                frame.configure(bg=X_COLOR, highlightbackground=X_COLOR)
            elif status == "O":
                frame.configure(bg=O_COLOR, highlightbackground=O_COLOR)
            elif self.game.next_board == b and not self.game.meta_status:
                frame.configure(bg=ACTIVE, highlightbackground=GOLD)
            elif b in allowed_boards and not self.game.meta_status:
                frame.configure(bg=CELL_BG, highlightbackground=LINE)
            else:
                frame.configure(bg=CELL_BG, highlightbackground=LINE)

            for c in range(9):
                idx = b * 9 + c
                button = self.buttons[idx]
                value = self.game.cells[b][c]

                fg = TEXT
                if value == "X":
                    fg = X_COLOR
                elif value == "O":
                    fg = O_COLOR

                bg = CELL_BG
                if (b, c) in legal and not value and not self.game_over:
                    bg = HOVER if self.hover_index == idx else CELL_BG
                elif status == "X":
                    bg = "#245f78"
                elif status == "O":
                    bg = "#7a3045"

                button.configure(text=value, fg=fg, bg=bg)

                if self.game_over or self.ai_busy or (b, c) not in legal:
                    button.configure(cursor="arrow")
                else:
                    button.configure(cursor="hand2")

        self.rank_label.configure(
            text=f"{self.profile.name}  •  {self.profile.rank}  •  {self.profile.points} RP"
        )
        if self.game_mode.get() == "Player vs Player":
            self.match_settings_label.configure(
                text="PLAYER VS PLAYER\n\nNo AI • Local 2-player"
            )
        elif self.game_mode.get() == "AI vs AI":
            self.match_settings_label.configure(
                text=(
                    f"AI VS AI\n\nX: {self.ai_x.get()}\n"
                    f"O: {self.ai_o.get()}\n\nSame AI: NOT ALLOWED"
                )
            )
        elif self.game_mode.get() == "AI vs AI":
            self.match_settings_label.configure(
                text=(
                    f"AI VS AI\n\nX: {self.ai_x.get()}\n"
                    f"O: {self.ai_o.get()}\n\nQueue: {max(1, self.ai_queue.get())}"
                )
            )
        else:
            self.match_settings_label.configure(
                text=f"PLAYER VS AI\n\nDifficulty: {self.difficulty.get()}"
            )

        self.stats_label.configure(
            text=(
                f"RP       {self.profile.points}\n"
                f"Rank     {self.profile.rank}\n"
                f"Wins     {self.profile.wins}\n"
                f"Losses   {self.profile.losses}\n"
                f"Draws    {self.profile.draws}\n"
                f"Games    {self.profile.games}\n"
                f"Streak   {self.profile.current_streak}\n"
                f"Best     {self.profile.best_streak}\n\n"
                f"Last 10  {''.join(self.profile.recent_results) or '—'}"
            )
        )

        rank_lines = []
        for index, (threshold, name) in enumerate(RANKS):
            if index + 1 < len(RANKS):
                next_threshold = RANKS[index + 1][0]
                rank_lines.append(
                    f"{name:<11} {threshold:>4}–{next_threshold - 1} RP"
                )
            else:
                rank_lines.append(f"{name:<11} {threshold:>4}+ RP")

        self.rank_requirements_label.configure(
            text="\n".join(rank_lines)
        )

        self.ai_rewards_label.configure(
            text=(
                f"Easy       +{AI_RATING['Easy']['win']:>3} / "
                f"-{AI_RATING['Easy']['loss']:>2}\n"
                f"Medium     +{AI_RATING['Medium']['win']:>3} / "
                f"-{AI_RATING['Medium']['loss']:>2}\n"
                f"Hard       +{AI_RATING['Hard']['win']:>3} / "
                f"-{AI_RATING['Hard']['loss']:>2}\n"
                f"Nightmare  +{AI_RATING['Nightmare']['win']:>3} / "
                f"-{AI_RATING['Nightmare']['loss']:>2}\n"
                f"Katrina    +{AI_RATING['Katrina2']['win']:>3} / "
                f"-{AI_RATING['Katrina2']['loss']:>2}\n\n"
                f"Format: Win / Loss"
            )
        )


# ---------------------------------------------------------------------------
# Self-tests
# ---------------------------------------------------------------------------

def run_self_tests():
    # Basic local winner/draw detection.
    assert UltimateBoard.winner(["X", "X", "X", "", "", "", "", "", ""]) == "X"
    assert UltimateBoard.winner(["O", "", "", "O", "", "", "O", "", ""]) == "O"
    assert UltimateBoard.winner(["X", "O", "X", "X", "O", "O", "O", "X", "X"]) == "D"
    assert UltimateBoard.winner(["X", "O", "", "", "", "", "", "", ""]) == ""

    # Katrina memory round-trip.
    kt = UltimateBoard()
    kt.play(0, 0)
    kt_key = katrina_state_key(kt)
    kt_move = kt.legal_moves()[0]
    KATRINA_MEMORY[kt_key] = {
        "opponent_move": [0, 0],
        "response": [kt_move[0], kt_move[1]],
    }
    assert tuple(KATRINA_MEMORY[kt_key]["response"]) in kt.legal_moves()
    KATRINA_MEMORY.pop(kt_key, None)

    # AI-vs-AI configuration must use different AI levels.
    ai_levels = get_all_ai_names()
    assert len(ai_levels) == len(set(ai_levels))

    # First move can be anywhere.
    game = UltimateBoard()
    assert len(game.legal_moves()) == 81
    assert game.play(4, 7)
    assert game.next_board == 7
    assert all(b == 7 for b, _ in game.legal_moves())

    # If target board is finished, next player can choose elsewhere.
    game2 = UltimateBoard()
    game2.small_status[7] = "X"
    game2.turn = "O"
    game2.next_board = 7
    assert len(game2.legal_moves()) == 72

    # Illegal moves must not modify the game.
    # With a finished target board, any unfinished board is legal.
    assert game2.play(0, 0)

    # Verify forced-board rejection separately.
    forced = UltimateBoard()
    forced.next_board = 7
    before = [row[:] for row in forced.cells]
    assert not forced.play(0, 0)
    assert forced.cells == before

    # AI must always return a legal move on fresh and forced positions.
    for difficulty in get_all_ai_names():
        test_game = UltimateBoard()
        move = ai_move(test_game, difficulty)
        assert move in test_game.legal_moves()

    # AI should take an immediate small-board win when available.
    test_game = UltimateBoard()
    test_game.turn = "O"
    test_game.cells[0] = ["O", "O", "", "", "X", "", "", "", ""]
    test_game.next_board = 0
    move = ai_move(test_game, "Hard")
    assert move == (0, 2), f"Expected immediate win, got {move}"

    # Profile serialization is handled by functions above; rank thresholds.
    p = Profile(points=1000)
    assert p.rank == "Diamond"

    return True


def main():
    run_self_tests()
    root = tk.Tk()
    app = UltimateTicTacToeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
