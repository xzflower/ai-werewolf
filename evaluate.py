#!/usr/bin/env python3
"""AI Werewolf 批量评测框架

Usage:
    python evaluate.py --games 3          # 跑 3 局
    python evaluate.py --games 3 --json   # 同时输出 JSON 原始数据
    python evaluate.py --games 5 --verbose  # 每局详细日志
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

# 确保能 import backend 模块
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from backend.game.gm import GameMaster
from backend.game.models import Camp, GameConfig, Phase, Role


# ══════════════════════════════════════════════
# 单局游戏 collector
# ══════════════════════════════════════════════


class GameCollector:
    """收集单局游戏的所有数据。"""

    def __init__(self, gm: GameMaster):
        self.gm = gm
        self.state = gm.state
        self.role_map: dict[int, str] = {}  # player_id -> role_name
        self.death_timeline: list[dict] = []  # 按轮次的死亡事件
        self.vote_records: list[dict] = []  # 每轮投票记录
        self.wolf_kills: list[dict] = []  # 狼人击杀记录
        self.seer_checks: list[dict] = []  # 预言家查验记录
        self.witch_actions: list[dict] = []  # 女巫行动记录
        self.guard_actions: list[dict] = []  # 守卫行动记录
        self.hunter_shots: list[dict] = []  # 猎人开枪记录
        self.speech_count: int = 0
        self.total_llm_calls: int = 0

    def collect(self):
        """游戏结束后收集所有数据。"""
        # 角色分配
        for p in self.state.players:
            self.role_map[p.id] = p.role.value

        # 从 elimination_history 构建死亡时间线
        for entry in self.state.elimination_history:
            pid = entry.get("player_id")
            cause = entry.get("cause", "unknown")
            rnd = entry.get("round", 0)
            role = self.role_map.get(pid, "unknown")
            self.death_timeline.append({
                "round": rnd,
                "player_id": pid,
                "cause": cause,
                "role": role,
            })

        # 从事件队列收集各阶段数据
        for event in self.gm.event_queue:
            self._process_event(event)

        # 从 state.night_actions 采集狼人击杀数据（去重：每轮每目标只记一次）
        wolf_ids = {pid for pid, r in self.role_map.items() if r == "werewolf"}
        seen_kills: set[tuple[int, int]] = set()
        for na in self.state.night_actions:
            role = self.role_map.get(na.player_id, "")
            if na.action_type == "kill" and na.player_id in wolf_ids and na.target_id is not None:
                key = (na.round, na.target_id)
                if key in seen_kills:
                    continue
                seen_kills.add(key)
                target_role = self.role_map.get(na.target_id, "unknown")
                died = any(
                    d["player_id"] == na.target_id and d["round"] == na.round
                    for d in self.death_timeline
                )
                self.wolf_kills.append({
                    "round": na.round,
                    "target": na.target_id,
                    "target_role": target_role,
                    "died": died,
                })
            elif role == "witch":
                self.witch_actions.append({
                    "round": na.round,
                    "action": na.action_type,
                    "target": na.target_id,
                })
            elif role == "guard" and na.action_type == "protect":
                self.guard_actions.append({
                    "round": na.round,
                    "target": na.target_id,
                })

        # 从 elimination_history 补充完整死亡时间线
        # (elimination_history 已有轮次信息，但可能缺少某些 action 细节)

    def _process_event(self, event: dict):
        etype = event.get("type", "")
        data = event.get("data", {})

        if etype == "vote_result":
            votes = data.get("votes", {})
            tally = data.get("tally", {})
            self.vote_records.append({
                "round": self.state.round,
                "votes": votes,
                "tally": tally,
            })
        elif etype == "night_action":
            self.total_llm_calls += 1
            pid = data.get("player_id")
            action_type = data.get("action_type", "")
            target_id = data.get("target_id")
            role = self.role_map.get(pid, "")
            if role == "werewolf" and action_type == "kill":
                target_role = self.role_map.get(target_id, "unknown")
                self.wolf_kills.append({
                    "round": data.get("round", 0),
                    "killer": pid,
                    "target": target_id,
                    "target_role": target_role,
                })
            elif role == "witch":
                self.witch_actions.append({
                    "round": data.get("round", 0),
                    "action": action_type,
                    "target": target_id,
                })
            elif role == "guard" and action_type == "protect":
                self.guard_actions.append({
                    "round": data.get("round", 0),
                    "target": target_id,
                })
        elif etype == "seer_result":
            self.seer_checks.append({
                "round": data.get("round", self.state.round),
                "target_id": data.get("target_id"),
                "camp": data.get("camp"),
            })
        elif etype == "elimination" and data.get("cause") == "hunter_shot":
            self.hunter_shots.append({
                "round": self.state.round,
                "target_id": data.get("player_id"),
                "target_role": self.role_map.get(data.get("player_id"), "unknown"),
            })
        elif etype == "speech":
            self.speech_count += 1


# ══════════════════════════════════════════════
# 单局评测指标
# ══════════════════════════════════════════════


def analyze_game(gm: GameMaster, collector: GameCollector) -> dict:
    """分析单局游戏并返回 metrics。"""
    state = gm.state
    total_players = len(state.players)
    alive_final = len(state.alive_players)

    # 死亡时间线（带角色名）
    deaths_by_round = defaultdict(list)
    for d in collector.death_timeline:
        deaths_by_round[d["round"]].append(d)

    # 投票分析
    total_votes_cast = 0
    correct_votes = 0  # 好人投给狼人
    for vrec in collector.vote_records:
        votes = vrec.get("votes", {})
        wolf_ids = {pid for pid, r in collector.role_map.items() if r == "werewolf"}
        for voter, target in votes.items():
            if collector.role_map.get(voter) != "werewolf" and target in wolf_ids:
                correct_votes += 1
        total_votes_cast += len(votes)

    vote_accuracy = correct_votes / total_votes_cast if total_votes_cast else 0

    # 预言家分析
    seer_correct = 0
    seer_total = len(collector.seer_checks)
    for check in collector.seer_checks:
        target_id = check.get("target_id")
        camp = check.get("camp")
        if target_id is not None:
            actual_camp = collector.role_map.get(target_id, "")
            expected = "werewolf" if actual_camp == "werewolf" else "villager"
            if camp == expected:
                seer_correct += 1

    seer_accuracy = seer_correct / seer_total if seer_total > 0 else None

    # 狼人击杀分析
    wolf_kill_specials = 0
    wolf_kill_total = len(collector.wolf_kills)
    for kill in collector.wolf_kills:
        if kill["target_role"] != "villager" and kill["target_role"] != "werewolf":
            wolf_kill_specials += 1

    # 狼人存活轮数
    wolf_survival_rounds = []
    for pid, role in collector.role_map.items():
        if role == "werewolf":
            death_round = None
            for d in collector.death_timeline:
                if d["player_id"] == pid:
                    death_round = d["round"]
                    break
            wolf_survival_rounds.append(death_round or state.round)

    avg_wolf_survival = statistics.mean(wolf_survival_rounds) if wolf_survival_rounds else 0

    # 女巫分析
    witch_saved = any(a.get("action") == "save" for a in collector.witch_actions)
    witch_poisoned = any(a.get("action") == "poison" for a in collector.witch_actions)

    # 狼人获胜时的投票表现（狼人是否成功伪装）
    wolves_voted_out = [d for d in collector.death_timeline if d["role"] == "werewolf" and d["cause"] == "vote"]

    return {
        "winner": state.winner.value if state.winner else "unknown",
        "total_rounds": state.round,
        "total_players": total_players,
        "survivors": alive_final,
        "vote_accuracy": round(vote_accuracy, 3),
        "total_votes": total_votes_cast,
        "correct_votes": correct_votes,
        "seer_accuracy": round(seer_accuracy, 3) if seer_accuracy is not None else None,
        "seer_correct": seer_correct,
        "seer_checks": seer_total,
        "seer_checks_list": collector.seer_checks,
        "wolf_kill_specials": wolf_kill_specials,
        "wolf_kill_total": wolf_kill_total,
        "wolf_survival_rounds": wolf_survival_rounds,
        "avg_wolf_survival": round(avg_wolf_survival, 1),
        "witch_used_save": witch_saved,
        "witch_used_poison": witch_poisoned,
        "wolves_voted_out": len(wolves_voted_out),
        "death_timeline": collector.death_timeline,
        "wolf_kills": collector.wolf_kills,
        "seer_checks": collector.seer_checks,
        "vote_records": collector.vote_records,
    }


# ══════════════════════════════════════════════
# 报告格式化
# ══════════════════════════════════════════════


def format_game_report(idx: int, metrics: dict) -> str:
    """格式化单局报告。"""
    lines = []
    lines.append(f"{'─' * 50}")
    lines.append(f"  第 {idx + 1} 局")
    lines.append(f"{'─' * 50}")
    lines.append(f"  获胜方:       {'🐺 狼人' if metrics['winner'] == 'werewolf' else '👼 好人'}")
    lines.append(f"  游戏轮数:     {metrics['total_rounds']} 轮")
    lines.append(f"  最终存活:     {metrics['survivors']}/{metrics['total_players']} 人")

    # 死亡时间线
    if metrics["death_timeline"]:
        lines.append(f"\n  死亡时间线:")
        for d in metrics["death_timeline"]:
            cause_icon = {"werewolf_kill": "🐺", "vote": "🗳", "poison": "☠️", "hunter_shot": "🏹"}
            icon = cause_icon.get(d["cause"], "💀")
            lines.append(f"    第{d['round']}轮 {icon} 玩家{d['player_id']}({d['role']}) - {d['cause']}")

    # 投票
    lines.append(f"\n  投票:")
    lines.append(f"    好人投票命中率: {metrics['vote_accuracy']:.1%} ({metrics['correct_votes']}/{metrics['total_votes']})")
    lines.append(f"    狼人被投出:     {metrics['wolves_voted_out']} 人")

    # 狼人
    lines.append(f"\n  狼人:")
    lines.append(f"    平均存活:       {metrics['avg_wolf_survival']:.1f} 轮")
    lines.append(f"    击杀神职数:     {metrics['wolf_kill_specials']}/{metrics['wolf_kill_total']} (含未遂)")
    actual_kills = [k for k in metrics.get("wolf_kills", []) if k.get("died")]
    if actual_kills:
        lines.append(f"    实际击杀:")
        for k in actual_kills:
            lines.append(f"      第{k['round']}轮 击杀 玩家{k['target']}({k['target_role']})")

    # 预言家
    lines.append(f"\n  预言家:")
    if metrics["seer_accuracy"] is not None:
        lines.append(f"    查验准确率:     {metrics['seer_accuracy']:.0%} ({metrics['seer_correct']}/{metrics['seer_checks']})")
    else:
        lines.append(f"    查验次数:       {metrics['seer_checks']}")
    checks_list = metrics.get("seer_checks_list", [])
    if checks_list:
        for ch in checks_list:
            icon = "🐺" if ch.get("camp") == "werewolf" else "👼"
            camp_cn = "狼人" if ch.get("camp") == "werewolf" else "好人"
            lines.append(f"      第{ch.get('round','?')}轮 查 玩家{ch['target_id']} → {icon}{camp_cn}")

    # 女巫
    lines.append(f"\n  女巫:")
    lines.append(f"    解药: {'✅ 已用' if metrics['witch_used_save'] else '❌ 未用'}")
    lines.append(f"    毒药: {'✅ 已用' if metrics['witch_used_poison'] else '❌ 未用'}")

    lines.append("")
    return "\n".join(lines)


def format_summary(all_metrics: list[dict], total_time: float) -> str:
    """格式化聚合摘要。"""
    n = len(all_metrics)
    if n == 0:
        return "⚠️  没有成功的游戏记录。"

    wolf_wins = sum(1 for m in all_metrics if m["winner"] == "werewolf")
    villager_wins = sum(1 for m in all_metrics if m["winner"] == "villager")
    rounds = [m["total_rounds"] for m in all_metrics]
    vote_accs = [m["vote_accuracy"] for m in all_metrics]
    wolf_survivals = [m["avg_wolf_survival"] for m in all_metrics]
    wolf_kill_rates = [
        m["wolf_kill_specials"] / m["wolf_kill_total"] if m["wolf_kill_total"] > 0 else 0
        for m in all_metrics
    ]
    seer_accs = [m["seer_accuracy"] for m in all_metrics if m["seer_accuracy"] is not None]

    separator = "=" * 54
    lines = [
        f"\n{separator}",
        f"            AI 狼人杀 — 批量评测报告",
        f"{separator}",
        f"",
        f"  📊 执行概要",
        f"  {'─' * 40}",
        f"  总局数:        {n}",
        f"  总耗时:        {total_time:.1f} 秒",
        f"  平均每局:      {total_time / n:.1f} 秒",
        f"",
        f"  🏆 胜负统计",
        f"  {'─' * 40}",
        f"  好人胜率:      {villager_wins}/{n} ({villager_wins / n:.1%})",
        f"  狼人胜率:      {wolf_wins}/{n} ({wolf_wins / n:.1%})",
        f"",
        f"  📈 关键指标 (均值 ± 标准差)",
        f"  {'─' * 40}",
        f"  游戏轮数:      {statistics.mean(rounds):.1f} ± {statistics.stdev(rounds):.1f}" if n > 1 else f"  游戏轮数:      {statistics.mean(rounds):.1f}",
        f"  好人投票命中:  {statistics.mean(vote_accs):.1%}" if vote_accs else "  好人投票命中:  N/A",
        f"  狼人平均存活:  {statistics.mean(wolf_survivals):.1f} 轮",
        f"  狼人击杀神职:  {statistics.mean(wolf_kill_rates):.0%}" if wolf_kill_rates else "  狼人击杀神职:  N/A",
    ]
    if seer_accs:
        stdev_str = f" ± {statistics.stdev(seer_accs):.1%}" if len(seer_accs) > 1 else ""
        lines.append(f"  预言家准确率:  {statistics.mean(seer_accs):.0%}{stdev_str}")

    lines.append(f"")
    return "\n".join(lines)


# ══════════════════════════════════════════════
# 单局执行器（带重试和超时）
# ══════════════════════════════════════════════


async def run_single_game(game_idx: int, verbose: bool = False) -> dict | None:
    """运行单局游戏并返回 metrics。"""
    if verbose:
        print(f"\n▶ 第 {game_idx + 1} 局开始...", flush=True)

    try:
        config = GameConfig(time_limit_enabled=False)
        gm = GameMaster(config)
        gm.init_game()

        if verbose:
            roles = [(p.id, p.role.display_name()) for p in gm.state.players]
            role_str = ', '.join(f'{pid}={r}' for pid, r in roles[:6])
            print(f"  角色分配: {role_str} ..." if len(roles) > 6 else f"  角色分配: {role_str}", flush=True)

        collector = GameCollector(gm)

        try:
            await asyncio.wait_for(gm.run_game(), timeout=600)
        except asyncio.TimeoutError:
            print(f"  ⚠️  第 {game_idx + 1} 局超时 (600s)", flush=True)
            gm.state.game_over = True
            if gm.state.winner is None:
                alive_wolves = [p for p in gm.state.alive_players if p.camp == Camp.WEREWOLF]
                if not alive_wolves:
                    gm.state.winner = Camp.VILLAGER
                elif not [p for p in gm.state.alive_players if p.camp == Camp.VILLAGER]:
                    gm.state.winner = Camp.WEREWOLF

        collector.collect()
        metrics = analyze_game(gm, collector)

        if verbose:
            print(format_game_report(game_idx, metrics), flush=True)

        return metrics

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"  ❌ 第 {game_idx + 1} 局失败: {e}", flush=True)
        return None


# ══════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════


async def main():
    parser = argparse.ArgumentParser(description="AI Werewolf 批量评测")
    parser.add_argument("--games", "-g", type=int, default=5, help="评测局数 (默认: 5)")
    parser.add_argument("--json", action="store_true", help="同时输出 JSON 原始数据")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示每局详细日志")
    args = parser.parse_args()

    n_games = args.games
    print(f"\n🧪 准备评测 {n_games} 局... (每局最多 300 秒)\n")

    start_time = time.time()
    all_metrics = []

    for i in range(n_games):
        result = await run_single_game(i, verbose=args.verbose)
        if result is not None:
            all_metrics.append(result)
        else:
            print(f"  ⚠️  第 {i + 1} 局跳过 (记录为空)")

    total_time = time.time() - start_time

    # 输出摘要
    print(format_summary(all_metrics, total_time))

    # JSON 输出
    if args.json:
        json_path = Path(f"eval_report_{int(time.time())}.json")
        with open(json_path, "w") as f:
            json.dump({
                "meta": {
                    "total_games": n_games,
                    "successful_games": len(all_metrics),
                    "total_time_seconds": round(total_time, 1),
                },
                "games": all_metrics,
                "aggregate": {
                    "total_games": n_games,
                    "successful_games": len(all_metrics),
                }
            }, f, ensure_ascii=False, indent=2)
        print(f"\n📁 原始数据已保存: {json_path}")

    # 返回退出码
    success_rate = len(all_metrics) / n_games if n_games > 0 else 0
    if success_rate < 0.5:
        print(f"\n⚠️  成功率 {success_rate:.0%} 偏低，建议检查 API 或网络状况")
        sys.exit(1)
    else:
        print(f"\n✅ 评测完成！成功率 {success_rate:.0%}")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
