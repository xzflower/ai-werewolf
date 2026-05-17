"""SQLite 数据库 — 游戏记录持久化。

用法：
    from backend.db import save_game, list_games, get_game

设计原则：
    - 零外部依赖（Python 自带 sqlite3）
    - 每局存一行的 JSON 事件日志，不做范式化
    - 查询通过 sqlite3 命令行或本模块提供的方法
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

_DB_PATH = Path(__file__).resolve().parent / "werewolf.db"


# ── 初始化 ────────────────────────────────────────────────────────────────


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """创建表结构（幂等）。"""
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS games (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time      TEXT    NOT NULL,
                end_time        TEXT    NOT NULL,
                winner          TEXT    NOT NULL,
                total_rounds    INTEGER NOT NULL,
                config_json     TEXT,
                roles_json      TEXT    NOT NULL,
                elimination_history_json TEXT,
                events_json     TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_games_winner
                ON games(winner);

            CREATE INDEX IF NOT EXISTS idx_games_start
                ON games(start_time);

            CREATE TABLE IF NOT EXISTS experience (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id     INTEGER NOT NULL REFERENCES games(id),
                role        TEXT    NOT NULL,
                round       INTEGER NOT NULL,
                situation   TEXT    NOT NULL,
                action      TEXT    NOT NULL,
                outcome     TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_experience_role
                ON experience(role);
        """)


# ── 写入 ──────────────────────────────────────────────────────────────────


def save_game(
    winner: str,
    total_rounds: int,
    roles: list[dict],
    elimination_history: list[dict],
    events: list[dict],
    config: dict | None = None,
    start_time: str | None = None,
) -> int:
    """保存一局游戏记录，返回 game_id。"""
    init_db()

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with _get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO games
                (start_time, end_time, winner, total_rounds,
                 config_json, roles_json, elimination_history_json, events_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                start_time or now,
                now,
                winner,
                total_rounds,
                json.dumps(config, ensure_ascii=False) if config else None,
                json.dumps(roles, ensure_ascii=False),
                json.dumps(elimination_history, ensure_ascii=False),
                json.dumps(events, ensure_ascii=False),
            ),
        )
        return cur.lastrowid  # type: ignore[return-value]


# ── 查询 ──────────────────────────────────────────────────────────────────


def list_games(limit: int = 20, offset: int = 0) -> list[dict]:
    """列出最近的游戏记录（不含事件详情）。"""
    init_db()
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, start_time, end_time, winner, total_rounds,
                   roles_json
            FROM games
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["roles"] = json.loads(d.pop("roles_json"))
        result.append(d)
    return result


def get_game(game_id: int) -> Optional[dict]:
    """获取单局游戏完整数据（含事件）。"""
    init_db()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM games WHERE id = ?", (game_id,)
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    for key in ("roles_json", "events_json", "elimination_history_json", "config_json"):
        if d.get(key):
            d[key.replace("_json", "")] = json.loads(d.pop(key))
        else:
            d.pop(key, None)
    return d


def count_games(winner: str | None = None) -> int:
    """统计游戏数量，可按胜方过滤。"""
    init_db()
    with _get_conn() as conn:
        if winner:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM games WHERE winner = ?", (winner,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM games").fetchone()
    return row["cnt"]


def stats() -> dict:
    """简要统计。"""
    init_db()
    with _get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        wolf = conn.execute(
            "SELECT COUNT(*) FROM games WHERE winner='werewolf'"
        ).fetchone()[0]
        villager = conn.execute(
            "SELECT COUNT(*) FROM games WHERE winner='villager'"
        ).fetchone()[0]
        avg_rounds = conn.execute(
            "SELECT AVG(total_rounds) FROM games"
        ).fetchone()[0]
    return {
        "total_games": total,
        "wolf_wins": wolf,
        "villager_wins": villager,
        "avg_rounds": round(avg_rounds, 1) if avg_rounds else 0,
    }


# ── 初始化（模块导入即建表） ────────────────────────────────────────────

init_db()
