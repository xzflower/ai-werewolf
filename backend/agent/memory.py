from __future__ import annotations

from backend.game.models import BeliefEntry, Speech


class AgentMemory:
    """Per-agent memory store for a Werewolf game agent."""

    def __init__(self) -> None:
        self.belief_state: dict[int, BeliefEntry] = {}
        self.speech_history: list[Speech] = []
        self.private_info: dict = {}
        self.alive_player_ids: set[int] = set()

    # ── Beliefs ──────────────────────────────────────────────────────

    def update_belief(self, entry: BeliefEntry) -> None:
        self.belief_state[entry.player_id] = entry

    def get_belief(self, player_id: int) -> BeliefEntry | None:
        return self.belief_state.get(player_id)

    def summarize_beliefs(self) -> str:
        if not self.belief_state:
            return "暂无对任何玩家的判断。"
        lines: list[str] = []
        for pid, b in sorted(self.belief_state.items()):
            role = b.guessed_role or "未知"
            lines.append(
                f"玩家{pid}：可能身份={role}，置信度={b.confidence:.0%}，"
                f"理由={b.reason or '无'}"
            )
        return "\n".join(lines)

    # ── Speech history ───────────────────────────────────────────────

    def add_speech(self, speech: Speech) -> None:
        self.speech_history.append(speech)

    def get_public_history(self) -> list[Speech]:
        return [s for s in self.speech_history if s.is_public]

    def summarize_public_history(self) -> str:
        public = self.get_public_history()
        if not public:
            return "暂无公开发言记录。"
        lines: list[str] = []
        for s in public:
            lines.append(f"[第{s.round}轮] 玩家{s.player_id}：{s.content}")
        return "\n".join(lines)

    # ── Private info ─────────────────────────────────────────────────

    def set_private_info(self, info: dict) -> None:
        self.private_info.update(info)

    def reset_private_info(self, info: dict) -> None:
        self.private_info = info

    def get_private_info(self) -> dict:
        return self.private_info

    def summarize_private_info(self) -> str:
        if not self.private_info:
            return "暂无私密信息。"
        parts: list[str] = []
        for key, value in self.private_info.items():
            parts.append(f"{key}：{value}")
        return "\n".join(parts)

    # ── Alive players ────────────────────────────────────────────────

    def set_alive_players(self, player_ids: set[int]) -> None:
        self.alive_player_ids = set(player_ids)

    # ── Condensed history (anti-long-context-loss) ────────────────────

    def get_condensed_history(self, max_entries: int = 20) -> str:
        """生成精简版历史，避免长对话失忆。
        短历史返回全部，长历史将早期按轮次汇总、保留近期详细内容。"""
        public = self.get_public_history()
        if not public:
            return "暂无发言记录。"

        if len(public) <= max_entries:
            lines = [f"[第{s.round}轮] 玩家{s.player_id}：{s.content}" for s in public]
            return "\n".join(lines)

        # 长历史: 按轮次分组, 早期轮次只给摘要
        from collections import defaultdict
        by_round: dict[int, list[str]] = defaultdict(list)
        for s in public:
            by_round[s.round].append(f"玩家{s.player_id}：{s.content}")

        sorted_rounds = sorted(by_round.keys())
        recent_rounds = sorted_rounds[-(max_entries // 4):]  # 最近几轮保留详细

        lines = []
        for rnd in sorted_rounds:
            if rnd in recent_rounds:
                lines.append(f"--- 第{rnd}轮 ---")
                lines.extend(by_round[rnd])
            else:
                # 早期轮次仅摘要
                suspicions = [s for s in by_round[rnd] if "怀疑" in s or "狼" in s]
                if suspicions:
                    lines.append(f"[第{rnd}轮摘要] {'; '.join(suspicions[:3])}")
                else:
                    lines.append(f"[第{rnd}轮摘要] {len(by_round[rnd])}条发言，无明显疑点")

        return "\n".join(lines)

    def summarize_key_events(self, elimination_history: list | None = None) -> str:
        """生成关键事件摘要"""
        events = []

        # 死亡/放逐信息
        if elimination_history:
            for entry in elimination_history:
                pid = entry.get("player_id", "?")
                cause = entry.get("cause", "unknown")
                events.append(f"玩家{pid} 因 {cause} 出局")

        # 私密信息中的关键发现
        seer_checks = self.private_info.get("seer_checks", [])
        for check in seer_checks:
            tid = check.get("target_id", "?")
            camp = check.get("camp", "?")
            events.append(f"预言家查验: 玩家{tid} 为 {camp}")

        wolf_teammates = self.private_info.get("wolf_teammates", [])
        if wolf_teammates:
            events.append(f"狼人队友: {wolf_teammates}")

        if not events:
            return "暂无关键事件。"

        return "\n".join(events)

    def get_state_summary(self) -> str:
        sections = [
            "【存活玩家】",
            (
                ", ".join(str(pid) for pid in sorted(self.alive_player_ids))
                if self.alive_player_ids
                else "无"
            ),
            "",
            "【身份判断】",
            self.summarize_beliefs(),
            "",
            "【公开发言记录】",
            self.summarize_public_history(),
            "",
            "【私密信息】",
            self.summarize_private_info(),
        ]
        return "\n".join(sections)
