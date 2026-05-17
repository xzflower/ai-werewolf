from __future__ import annotations

import json
import re
from pathlib import Path

from backend.agent.memory import AgentMemory
from backend.game.models import (
    BeliefEntry,
    Camp,
    NightAction,
    Phase,
    ReflectionOutput,
    Role,
    Speech,
)
from backend.llm.client import LLMClient

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_REFLECT_SECTIONS = ["局势分析", "策略", "内心独白", "决定"]


class AgentBase:
    def __init__(
        self,
        player_id: int,
        name: str,
        role: Role,
        camp: Camp,
        llm: LLMClient,
    ) -> None:
        self.player_id = player_id
        self.name = name
        self.role = role
        self.camp = camp
        self.llm = llm
        self.memory = AgentMemory()

    # ── System prompt ────────────────────────────────────────────────────

    @staticmethod
    def _load_role_prompt(role: Role) -> str:
        role_file = role.value + ".txt"
        path = _PROMPTS_DIR / role_file
        return path.read_text(encoding="utf-8")

    def build_system_prompt(self) -> str:
        template = self._load_role_prompt(self.role)
        # Remove {game_context} and {memory_state} placeholders — those
        # are filled dynamically by reflect() at runtime.
        prompt = template.replace("{game_context}", "").replace("{memory_state}", "")
        return (
            f"{prompt}\n"
            f"你的玩家编号是{self.player_id}，名字是{self.name}。\n"
            "请始终以你的角色身份思考和发言。"
        )

    # ── Reflect ──────────────────────────────────────────────────────────

    def reflect(self) -> ReflectionOutput:
        # Build the prompt with live game context and memory injected.
        template = self._load_role_prompt(self.role)
        game_context = self.memory.get_state_summary()
        memory_state = self.memory.summarize_private_info()
        filled = template.format(
            game_context=game_context,
            memory_state=memory_state,
        )
        system_prompt = (
            f"{filled}\n"
            f"你的玩家编号是{self.player_id}，名字是{self.name}。\n"
            "请始终以你的角色身份思考和发言。"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "请分析当前局势并做出决策。"
                    "严格按照以下格式输出（每个标题独占一行）：\n"
                    "局势分析：...\n策略：...\n内心独白：...\n决定：...\n"
                ),
            },
        ]
        raw = self.llm.chat(messages, temperature=0.9)

        values: dict[str, str] = {}
        for key in _REFLECT_SECTIONS:
            pattern = rf"{re.escape(key)}[：:]\s*(.*?)(?={_next_boundary(key)})"
            match = re.search(pattern, raw, re.DOTALL)
            values[key] = match.group(1).strip() if match else ""

        # Update belief state by asking the LLM to output player judgments.
        self._update_beliefs_from_reflection(values.get("局势分析", ""))

        return ReflectionOutput(
            analysis=values.get("局势分析", ""),
            strategy=values.get("策略", ""),
            inner_monologue=values.get("内心独白", ""),
            decision=values.get("决定", ""),
        )

    def _update_beliefs_from_reflection(self, analysis: str) -> None:
        """Parse the analysis section for player mentions and update beliefs."""
        alive = sorted(self.memory.alive_player_ids)
        if not alive or not analysis:
            return
        alive_str = "、".join(str(p) for p in alive)
        belief_messages = [
            {"role": "system", "content": self.build_system_prompt()},
            {
                "role": "user",
                "content": (
                    f"以下是你对局势的分析：\n{analysis}\n\n"
                    f"存活玩家编号：{alive_str}\n"
                    "请根据以上分析，对每个存活玩家给出你的判断。\n"
                    "严格按以下格式输出，每行一个玩家，不要输出其他内容：\n"
                    "玩家编号|猜测身份|置信度(0-100)|理由\n"
                    "示例：3|狼人|80|发言时回避了关键问题"
                ),
            },
        ]
        raw = self.llm.chat(belief_messages, temperature=0.5)
        for line in raw.strip().splitlines():
            parts = line.strip().split("|")
            if len(parts) >= 4:
                try:
                    pid = int(parts[0].strip())
                    confidence = float(parts[2].strip()) / 100.0
                except (ValueError, IndexError):
                    continue
                self.memory.update_belief(
                    BeliefEntry(
                        player_id=pid,
                        guessed_role=parts[1].strip(),
                        confidence=confidence,
                        reason=parts[3].strip(),
                    )
                )

    # ── Speak ────────────────────────────────────────────────────────────

    def speak(self) -> str:
        reflection = self.reflect()
        # Store inner monologue as private info in memory.
        self.memory.set_private_info({
            **self.memory.get_private_info(),
            "inner_monologue": reflection.inner_monologue,
        })
        self.memory.add_speech(
            Speech(
                player_id=self.player_id,
                content=reflection.inner_monologue,
                round=0,
                is_public=False,
                is_inner_monologue=True,
            )
        )
        self.memory.add_speech(
            Speech(
                player_id=self.player_id,
                content=reflection.decision,
                round=0,
                is_public=True,
                is_inner_monologue=False,
            )
        )
        return reflection.decision

    # ── Discuss ──────────────────────────────────────────────────────────

    def discuss(self, speech_history: str) -> str:
        """参与白天自由讨论，回应其他玩家的发言。"""
        belief_summary = self.memory.summarize_beliefs()
        alive = ", ".join(str(pid) for pid in sorted(self.memory.alive_player_ids))
        messages = [
            {"role": "system", "content": self.build_system_prompt()},
            {
                "role": "user",
                "content": (
                    f"当前轮次：第{self.memory.get_private_info().get('current_round', '?')}轮\n"
                    f"存活玩家：{alive}\n\n"
                    f"以下是本轮所有人的公开发言：\n{speech_history}\n\n"
                    f"你的身份判断：\n{belief_summary}\n\n"
                    f"现在轮到你对别人的发言做出回应。你可以：\n"
                    f"1. 质疑某人发言中的矛盾\n"
                    f"2. 为自己辩护（如果有人怀疑你）\n"
                    f"3. 支持你认为的好人\n"
                    f"4. 追问更多的信息\n\n"
                    f"你是玩家{self.player_id}（{self.role.display_name()}），请发言。\n"
                    "直接输出你的发言内容，不要加额外的格式。"
                ),
            },
        ]
        result = self.llm.chat(messages, temperature=0.8)
        self.memory.add_speech(
            Speech(
                player_id=self.player_id,
                content=result,
                round=0,
                is_public=True,
                is_inner_monologue=False,
            )
        )
        return result

    # ── Vote ─────────────────────────────────────────────────────────────

    def vote(self, current_votes: dict[int, int]) -> int:
        vote_info = "\n".join(
            f"玩家{voter}投给了玩家{target}"
            for voter, target in current_votes.items()
        )
        if not vote_info:
            vote_info = "暂无其他人的投票信息。"
        alive = ", ".join(str(pid) for pid in sorted(self.memory.alive_player_ids))
        belief_summary = self.memory.summarize_beliefs()
        messages = [
            {"role": "system", "content": self.build_system_prompt()},
            {
                "role": "user",
                "content": (
                    f"当前游戏状态：\n{self.memory.get_state_summary()}\n\n"
                    f"存活玩家：{alive}\n"
                    f"当前投票情况：\n{vote_info}\n\n"
                    f"你的身份判断：\n{belief_summary}\n\n"
                    f"你是玩家{self.player_id}（{self.role.display_name()}），请决定投票放逐谁。\n"
                    '只输出一个JSON对象，格式：{"vote_target": <玩家编号>, "reason": "<理由>"}\n'
                    "不要输出任何其他内容。"
                ),
            },
        ]
        raw = self.llm.chat(messages, temperature=0.7)
        parsed = _parse_json_response(raw)
        if parsed is not None and isinstance(parsed.get("vote_target"), (int, float)):
            return int(parsed["vote_target"])
        numbers = re.findall(r"\d+", raw)
        if numbers:
            return int(numbers[0])
        return min(self.memory.alive_player_ids) if self.memory.alive_player_ids else 0

    # ── Night action ─────────────────────────────────────────────────────

    def night_action(self, game_state_summary: str) -> NightAction | None:
        alive = ", ".join(str(pid) for pid in sorted(self.memory.alive_player_ids))
        if self.role == Role.WEREWOLF:
            return self._wolf_night_action(alive, game_state_summary)
        if self.role == Role.SEER:
            return self._seer_night_action(alive, game_state_summary)
        if self.role == Role.WITCH:
            return self._witch_night_action(alive, game_state_summary)
        if self.role == Role.GUARD:
            return self._guard_night_action(alive, game_state_summary)
        return None

    def _wolf_night_action(
        self, alive: str, game_state_summary: str
    ) -> NightAction:
        messages = [
            {"role": "system", "content": self.build_system_prompt()},
            {
                "role": "user",
                "content": (
                    f"游戏状态：\n{game_state_summary}\n\n"
                    f"存活玩家：{alive}\n\n"
                    "你是狼人，请选择今晚要击杀的目标。\n"
                    '只输出一个JSON对象，格式：{"action": "kill", "target": <玩家编号>, "reason": "<理由>"}\n'
                    "不要输出任何其他内容。"
                ),
            },
        ]
        raw = self.llm.chat(messages, temperature=0.7)
        parsed = _parse_json_response(raw)
        if parsed is not None and isinstance(parsed.get("target"), (int, float)):
            target = int(parsed["target"])
        else:
            numbers = re.findall(r"\d+", raw)
            target = int(numbers[0]) if numbers else 0
        return NightAction(
            player_id=self.player_id, action_type="kill", target_id=target
        )

    def _seer_night_action(
        self, alive: str, game_state_summary: str
    ) -> NightAction:
        messages = [
            {"role": "system", "content": self.build_system_prompt()},
            {
                "role": "user",
                "content": (
                    f"游戏状态：\n{game_state_summary}\n\n"
                    f"存活玩家：{alive}\n\n"
                    "你是预言家，请选择今晚要查验的目标。\n"
                    '只输出一个JSON对象，格式：{"action": "investigate", "target": <玩家编号>}\n'
                    "不要输出任何其他内容。"
                ),
            },
        ]
        raw = self.llm.chat(messages, temperature=0.7)
        parsed = _parse_json_response(raw)
        if parsed is not None and isinstance(parsed.get("target"), (int, float)):
            target = int(parsed["target"])
        else:
            numbers = re.findall(r"\d+", raw)
            target = int(numbers[0]) if numbers else 0
        return NightAction(
            player_id=self.player_id, action_type="investigate", target_id=target
        )

    def _witch_night_action(
        self, alive: str, game_state_summary: str
    ) -> NightAction:
        messages = [
            {"role": "system", "content": self.build_system_prompt()},
            {
                "role": "user",
                "content": (
                    f"游戏状态：\n{game_state_summary}\n\n"
                    f"存活玩家：{alive}\n\n"
                    "你是女巫。请决定是否使用解药或毒药。\n"
                    '只输出一个JSON对象，格式：{"action": "save"|"poison"|"skip", "target": <玩家编号或null>}\n'
                    "  - 使用解药救人：{\"action\": \"save\", \"target\": null}\n"
                    "  - 使用毒药：{\"action\": \"poison\", \"target\": <玩家编号>}\n"
                    "  - 不使用：{\"action\": \"skip\", \"target\": null}\n"
                    "不要输出任何其他内容。"
                ),
            },
        ]
        raw = self.llm.chat(messages, temperature=0.7)
        parsed = _parse_json_response(raw)
        if parsed is not None and isinstance(parsed.get("action"), str):
            action = parsed["action"].lower()
            target = parsed.get("target")
            if action == "save":
                return NightAction(
                    player_id=self.player_id, action_type="save"
                )
            if action == "poison":
                t = int(target) if isinstance(target, (int, float)) else None
                return NightAction(
                    player_id=self.player_id,
                    action_type="poison",
                    target_id=t,
                )
            return NightAction(
                player_id=self.player_id, action_type="skip"
            )
        # Fallback: parse free text
        text = raw.strip().lower()
        if "save" in text:
            return NightAction(
                player_id=self.player_id, action_type="save"
            )
        if "poison" in text:
            numbers = re.findall(r"\d+", text)
            target = int(numbers[0]) if numbers else None
            return NightAction(
                player_id=self.player_id,
                action_type="poison",
                target_id=target,
            )
        return NightAction(
            player_id=self.player_id, action_type="skip"
        )

    def _guard_night_action(
        self, alive: str, game_state_summary: str
    ) -> NightAction:
        messages = [
            {"role": "system", "content": self.build_system_prompt()},
            {
                "role": "user",
                "content": (
                    f"游戏状态：\n{game_state_summary}\n\n"
                    f"存活玩家：{alive}\n\n"
                    "你是守卫，请选择今晚要保护的玩家。\n"
                    '只输出一个JSON对象，格式：{"action": "guard", "target": <玩家编号>}\n'
                    "不要输出任何其他内容。"
                ),
            },
        ]
        raw = self.llm.chat(messages, temperature=0.7)
        parsed = _parse_json_response(raw)
        if parsed is not None and isinstance(parsed.get("target"), (int, float)):
            target = int(parsed["target"])
        else:
            numbers = re.findall(r"\d+", raw)
            target = int(numbers[0]) if numbers else 0
        return NightAction(
            player_id=self.player_id, action_type="protect", target_id=target
        )

    # ── Wolf chat ────────────────────────────────────────────────────────

    def wolf_chat(self, message: str, history: list[dict]) -> str:
        chat_history = "\n".join(
            f"玩家{h['player_id']}：{h['content']}" for h in history
        )
        if not chat_history:
            chat_history = "暂无之前的讨论。"
        messages = [
            {"role": "system", "content": self.build_system_prompt()},
            {
                "role": "user",
                "content": (
                    "这是狼人队友间的私密讨论频道。\n"
                    f"之前的讨论：\n{chat_history}\n\n"
                    f"最新消息：{message}\n\n"
                    "请作为狼人队友回复，商议策略。直接输出你的回复内容。"
                ),
            },
        ]
        return self.llm.chat(messages, temperature=0.9)

    # ── Phase change ─────────────────────────────────────────────────────

    def on_phase_change(self, phase: Phase) -> None:
        self.memory.set_private_info({"current_phase": phase.value})


# ── Helper ───────────────────────────────────────────────────────────────


def _next_boundary(current_key: str) -> str:
    idx = _REFLECT_SECTIONS.index(current_key)
    if idx + 1 < len(_REFLECT_SECTIONS):
        return rf"(?:{_REFLECT_SECTIONS[idx + 1]}[：:]|$)"
    return r"$"


def _parse_json_response(raw: str) -> dict | None:
    """Extract and parse a JSON object from an LLM response.

    Handles cases where the LLM wraps JSON in markdown code fences or
    surrounds it with extra text.
    """
    # Try to find a JSON block inside code fences first.
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    else:
        # Fallback: find the first balanced {…} in the response.
        brace_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", raw, re.DOTALL)
        text = brace_match.group(0) if brace_match else None

    if text is None:
        return None

    try:
        result = json.loads(text)
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None
