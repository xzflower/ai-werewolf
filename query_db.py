#!/usr/bin/env python3
"""AI 狼人杀 — 数据库查询工具。

用法：
    python query_db.py                      # 最近 10 局概览
    python query_db.py --id 3               # 查看第 3 局详情
    python query_db.py --stats              # 统计摘要
    python query_db.py --watch 3            # 回放第 3 局事件流
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.db import count_games, get_game, list_games, stats

ROLE_ICON = {
    "werewolf": "🐺",
    "seer": "🔮",
    "witch": "🧪",
    "hunter": "🏹",
    "guard": "🛡️",
    "villager": "👤",
}


def show_list(limit: int) -> None:
    games = list_games(limit=limit)
    if not games:
        print("📭 数据库中暂无游戏记录。")
        return

    print(f"{'ID':>3} {'时间':<20} {'胜方':<10} {'轮数':>4}  角色分配")
    print("-" * 75)
    for g in games:
        roles_str = ", ".join(
            f"{ROLE_ICON.get(r['role'], '?')}{r['role'][:3]}"
            for r in g["roles"]
        )
        winner_icon = "🐺" if g["winner"] == "werewolf" else "👼"
        print(
            f"{g['id']:>3} {g['start_time'][:19]:<20} "
            f"{winner_icon}{g['winner']:<8} {g['total_rounds']:>4}  "
            f"{roles_str[:55]}..."
        )


def show_detail(game_id: int) -> None:
    g = get_game(game_id)
    if g is None:
        print(f"❌ 未找到第 {game_id} 局")
        return

    winner_icon = "🐺" if g["winner"] == "werewolf" else "👼"
    print(f"━━━ 第 {game_id} 局 ━━━")
    print(f"  时间:  {g['start_time']} → {g['end_time']}")
    print(f"  胜方:  {winner_icon} {g['winner']}")
    print(f"  轮数:  {g['total_rounds']}")
    print()

    roles = g.get("roles", [])
    print(f"  角色分配 ({len(roles)} 人):")
    wolves = [r for r in roles if r["role"] == "werewolf"]
    seers = [r for r in roles if r["role"] == "seer"]
    witchs = [r for r in roles if r["role"] == "witch"]
    others = [r for r in roles if r["role"] not in ("werewolf", "seer", "witch")]
    fmt_role = lambda r: f'{r["name"]}(ID:{r["id"]})'
    print(f"    🐺 狼人: {', '.join(fmt_role(r) for r in wolves)}")
    print(f"    🔮 预言家: {', '.join(fmt_role(r) for r in seers)}")
    print(f"    🧪 女巫: {', '.join(fmt_role(r) for r in witchs)}")
    print(f"    其他: {', '.join(fmt_role(r) for r in others)}")

    elim = g.get("elimination_history", [])
    if elim:
        print(f"\n  死亡时间线:")
        cause_icons = {"werewolf_kill": "🐺", "vote": "🗳️", "poison": "☠️", "hunter_shot": "🏹"}
        for e in elim:
            icon = cause_icons.get(e.get("cause", ""), "💀")
            print(f"    第{e['round']}轮 {icon} ID:{e['player_id']} ({e.get('cause','?')})")

    # 事件统计
    events = g.get("events", [])
    if events:
        type_counts: dict[str, int] = {}
        for ev in events:
            key = ev.get("type", "?")
            type_counts[key] = type_counts.get(key, 0) + 1
        print(f"\n  事件统计 ({len(events)} 条):")
        for k, v in sorted(type_counts.items(), key=lambda x: -x[1]):
            print(f"    {k}: {v} 次")


def show_watch(game_id: int) -> None:
    """回放事件流（简化版）。"""
    g = get_game(game_id)
    if g is None:
        print(f"❌ 未找到第 {game_id} 局")
        return

    events = g.get("events", [])
    print(f"━━━ 第 {game_id} 局 事件回放（{len(events)} 条）━━━\n")

    for ev in events:
        t = ev.get("type", "?")
        d = ev.get("data", {})

        if t == "phase_change":
            print(f"\n── {d.get('phase', '?')} ──")
        elif t == "speech":
            print(f"  🗣️  {d.get('player_name','?')}: {d.get('content','')[:120]}...")
        elif t == "discussion":
            print(f"  💬  {d.get('player_name','?')}: {d.get('content','')[:120]}...")
        elif t == "elimination":
            role_icon = ROLE_ICON.get(d.get("role", ""), "?")
            print(f"  💀  {d.get('player_name','?')} ({role_icon}{d.get('role','?')}) 被 {d.get('cause','?')}")
        elif t == "night_result":
            deaths = d.get("deaths", [])
            if deaths:
                for death in deaths:
                    print(f"  🌙  {death.get('player_name','?')} 死亡 ({death.get('cause','?')})")
            else:
                print(f"  🌙 平安夜")
        elif t == "vote_result":
            print(f"  🗳️ 投票结果: {d.get('tally', {})}")
        elif t == "seer_result":
            camp_cn = "狼人" if d.get("camp") == "werewolf" else "好人"
            print(f"  🔮 预言家查验 {d.get('target_name','?')} → {camp_cn}")
        elif t == "game_over":
            winner_icon = "🐺" if d.get("winner") == "werewolf" else "👼"
            print(f"\n  🏆 游戏结束! 胜方: {winner_icon} {d.get('winner','?')}")
        elif t == "game_start":
            print(f"  🎮 游戏开始")
        elif t == "hunter_shot":
            print(f"  🏹 猎人 {d.get('player_name','?')} 开枪!")


def show_stats() -> None:
    s = stats()
    if s["total_games"] == 0:
        print("📭 数据库中暂无游戏记录。")
        return

    wolf_rate = s["wolf_wins"] / s["total_games"] * 100
    villager_rate = s["villager_wins"] / s["total_games"] * 100

    print(f"━━━ AI 狼人杀 统计总览 ━━━")
    print(f"  总局数:      {s['total_games']}")
    print(f"  好人胜率:    {s['villager_wins']}/{s['total_games']} ({villager_rate:.1f}%)")
    print(f"  狼人胜率:    {s['wolf_wins']}/{s['total_games']} ({wolf_rate:.1f}%)")
    print(f"  平均轮数:    {s['avg_rounds']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI 狼人杀数据库查询")
    parser.add_argument("--id", type=int, help="查看指定局详情")
    parser.add_argument("--stats", action="store_true", help="统计摘要")
    parser.add_argument("--watch", type=int, help="回放指定局事件流")
    parser.add_argument("--limit", type=int, default=10, help="列表条数 (默认: 10)")
    args = parser.parse_args()

    if args.stats:
        show_stats()
    elif args.watch:
        show_watch(args.watch)
    elif args.id:
        show_detail(args.id)
    else:
        show_list(args.limit)


if __name__ == "__main__":
    main()
