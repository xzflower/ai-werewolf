from __future__ import annotations

import random
from collections import Counter
from typing import Optional

from backend.db import save_game
from backend.game.models import (
    Camp,
    GameConfig,
    GameState,
    NightAction,
    Phase,
    Player,
    Role,
    Speech,
    Vote,
)
from backend.game.roles import ROLE_CAMPS, create_players
from backend.agent.base import AgentBase
from backend.llm.client import LLMClient


class GameMaster:
    """Orchestrates the full AI Werewolf game loop."""

    def __init__(self, config: GameConfig | None = None):
        self.state = GameState(config=config or GameConfig())
        self.agents: dict[int, AgentBase] = {}
        self.llm = LLMClient()
        self.event_queue: list[dict] = []

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def init_game(self) -> None:
        players = create_players()
        self.state.players = players

        for player in players:
            self.agents[player.id] = AgentBase(
                player_id=player.id,
                name=player.name,
                role=player.role,
                camp=player.camp,
                llm=self.llm,
            )

        for player in players:
            self.broadcast(
                "game_init",
                {
                    "player_id": player.id,
                    "player_name": player.name,
                    "role": player.role.value,
                    "camp": player.camp.value,
                },
            )

    # ------------------------------------------------------------------
    # Main game loop
    # ------------------------------------------------------------------

    async def run_game(self) -> None:
        self.broadcast("game_start", {"message": "游戏开始"})

        while not self.state.game_over:
            self.state.round += 1
            self.state.day_count = self.state.round

            # --- Night phases ---
            await self.run_night_werewolf()
            await self.run_night_seer()
            await self.run_night_witch()
            await self.run_night_guard()

            self.process_night_results()

            if await self.check_game_over():
                break

            # --- Day phases ---
            self.state.phase = Phase.DAY_SPEECH
            await self.run_day_speech()

            self.state.phase = Phase.DAY_DISCUSSION
            await self.run_day_discussion()

            self.state.phase = Phase.DAY_VOTE
            await self.run_day_vote()

            await self.run_day_elimination()

            if await self.check_game_over():
                break

            # Reset per-night state
            self.state.night_kill_target = None
            self.state.night_saved = False
            self.state.night_poison_target = None

        # ── 游戏结束：持久化到数据库 ──
        try:
            roles_data = [
                {"id": p.id, "name": p.name, "role": p.role.value, "camp": p.camp.value}
                for p in self.state.players
            ]
            save_game(
                winner=self.state.winner.value if self.state.winner else "unknown",
                total_rounds=self.state.round,
                roles=roles_data,
                elimination_history=self.state.elimination_history,
                events=self.event_queue,
            )
        except Exception:
            import traceback
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Night phases
    # ------------------------------------------------------------------

    async def run_night_werewolf(self) -> None:
        self._sync_alive_players()
        self.state.phase = Phase.NIGHT_WEREWOLF
        self.broadcast("phase_change", {"phase": self.state.phase.value})

        alive_wolves = self.get_alive_wolves()
        if not alive_wolves:
            return

        # Notify wolves of teammates
        wolf_ids = [w.id for w in alive_wolves]
        for wolf in alive_wolves:
            agent = self.agents[wolf.id]
            teammates = [wid for wid in wolf_ids if wid != wolf.id]
            agent.memory.set_private_info({'wolf_teammates': teammates})

        # Wolf private discussion (one round each)
        chat_history: list[dict] = []
        for wolf in alive_wolves:
            agent = self.agents[wolf.id]
            visible_state = self._game_state_summary_for(agent)
            msg = agent.wolf_chat(
                self._build_wolf_discussion_prompt(visible_state),
                chat_history,
            )
            chat_history.append({"player_id": wolf.id, "content": msg})

        # Each wolf submits kill target
        kill_votes: list[int] = []
        for wolf in alive_wolves:
            agent = self.agents[wolf.id]
            action = agent.night_action(self._game_state_summary_for(agent))
            if action and action.target_id is not None:
                kill_votes.append(action.target_id)
                action.round = self.state.round
                self.state.night_actions.append(action)

        # Majority vote / random tie-break
        if kill_votes:
            counts = Counter(kill_votes)
            max_count = counts.most_common(1)[0][1]
            top_targets = [t for t, c in counts.items() if c == max_count]
            self.state.night_kill_target = random.choice(top_targets)

    async def run_night_seer(self) -> None:
        self._sync_alive_players()
        self.state.phase = Phase.NIGHT_SEER
        self.broadcast("phase_change", {"phase": self.state.phase.value})

        seer = self._find_alive_role(Role.SEER)
        if seer is None:
            return

        agent = self.agents[seer.id]
        action = agent.night_action(self._game_state_summary_for(agent))
        if action is None or action.target_id is None:
            return

        target = self.state.get_player(action.target_id)
        if target is None:
            return

        target_camp = target.camp.value
        result = {"target_id": action.target_id, "target_name": target.name, "camp": target_camp}
        info = agent.memory.get_private_info()
        info[f"check_round_{self.state.round}"] = result
        info.setdefault("seer_checks", []).append(result)
        agent.memory.set_private_info(info)

        self.broadcast(
            "seer_result",
            {"player_id": seer.id, "target_id": action.target_id, "target_name": target.name, "camp": target_camp, "round": self.state.round},
        )
        action.round = self.state.round
        self.state.night_actions.append(action)

    async def run_night_witch(self) -> None:
        self._sync_alive_players()
        self.state.phase = Phase.NIGHT_WITCH
        self.broadcast("phase_change", {"phase": self.state.phase.value})

        witch = self._find_alive_role(Role.WITCH)
        if witch is None:
            return

        agent = self.agents[witch.id]

        # Tell witch who was killed
        context = self._game_state_summary_for(agent)
        if self.state.night_kill_target is not None:
            killed_player = self.state.get_player(self.state.night_kill_target)
            context += f"\n今晚被狼人杀害的玩家: {killed_player.name if killed_player else '未知'} (ID: {self.state.night_kill_target})"
        else:
            context += "\n今晚没有人被狼人杀害。"

        if not self.state.witch_save_used:
            context += "\n你还有解药可以使用。"
        if not self.state.witch_poison_used:
            context += "\n你还有毒药可以使用。"

        action = agent.night_action(context)
        if action is None:
            return

        if action.action_type == "save" and not self.state.witch_save_used:
            self.state.night_saved = True
            self.state.witch_save_used = True
        elif action.action_type == "poison" and action.target_id is not None and not self.state.witch_poison_used:
            self.state.night_poison_target = action.target_id
            self.state.witch_poison_used = True

        action.round = self.state.round
        self.state.night_actions.append(action)

    async def run_night_guard(self) -> None:
        self._sync_alive_players()
        self.state.phase = Phase.NIGHT_GUARD
        self.broadcast("phase_change", {"phase": self.state.phase.value})

        guard = self._find_alive_role(Role.GUARD)
        if guard is None:
            return

        agent = self.agents[guard.id]
        context = self._game_state_summary_for(agent)
        if self.state.guard_last_target is not None:
            last = self.state.get_player(self.state.guard_last_target)
            context += f"\n上一晚你守护的玩家: {last.name if last else '未知'}，今晚不能再守护同一人。"

        action = agent.night_action(context)
        if action is None or action.target_id is None:
            return

        if action.target_id == self.state.guard_last_target:
            return  # Cannot guard same person twice in a row

        self.state.guard_target = action.target_id
        action.round = self.state.round
        self.state.night_actions.append(action)

    # ------------------------------------------------------------------
    # Day phases
    # ------------------------------------------------------------------

    async def run_day_speech(self) -> None:
        self._sync_alive_players()
        self.state.phase = Phase.DAY_SPEECH
        self.broadcast("phase_change", {"phase": self.state.phase.value})

        alive = self.state.alive_players

        # Determine speech order
        if self.state.round == 1:
            order = [p.id for p in random.sample(alive, len(alive))]
        else:
            last_eliminated = self._last_eliminated_id()
            if last_eliminated is not None:
                alive_ids = [p.id for p in alive]
                if last_eliminated in alive_ids:
                    idx = alive_ids.index(last_eliminated)
                    order = alive_ids[idx:] + alive_ids[:idx]
                else:
                    order = [p.id for p in random.sample(alive, len(alive))]
            else:
                order = [p.id for p in random.sample(alive, len(alive))]

        self.state.speech_order = order

        for player_id in order:
            player = self.state.get_player(player_id)
            if player is None or not player.alive:
                continue

            agent = self.agents[player_id]
            speech_content = agent.speak()

            self.state.speeches.append(
                Speech(
                    player_id=player_id,
                    content=speech_content,
                    round=self.state.round,
                    is_public=True,
                )
            )

            inner = agent.memory.get_private_info().get('last_inner_monologue', '')
            self.broadcast(
                "speech",
                {
                    "player_id": player_id,
                    "player_name": player.name,
                    "content": speech_content,
                    "inner_monologue": inner,
                    "round": self.state.round,
                },
            )

    async def run_day_discussion(self) -> None:
        """白天自由讨论环节——每人回应其他人的发言。"""
        self._sync_alive_players()
        self.state.phase = Phase.DAY_DISCUSSION
        self.broadcast("phase_change", {"phase": self.state.phase.value})

        alive = self.state.alive_players
        if not alive:
            return

        # 收集本轮公开发言记录
        round_speeches = [s for s in self.state.speeches if s.round == self.state.round and s.is_public]
        if not round_speeches:
            return

        speech_lines = []
        for s in round_speeches:
            pname = self.state.get_player(s.player_id)
            label = pname.name if pname else f"玩家{s.player_id}"
            speech_lines.append(f"{label}: {s.content}")
        speech_history = "\n".join(speech_lines)

        # 每人依次回应（随机选一半存活玩家以控制时间）
        discuss_order = random.sample(alive, min(len(alive), max(len(alive) // 2, 4)))
        for player in discuss_order:
            agent = self.agents[player.id]
            # 设置当前轮次
            agent.memory.set_private_info({"current_round": self.state.round})
            discuss_content = agent.discuss(speech_history)

            self.state.speeches.append(
                Speech(
                    player_id=player.id,
                    content=discuss_content,
                    round=self.state.round,
                    is_public=True,
                )
            )

            self.broadcast(
                "discussion",
                {
                    "player_id": player.id,
                    "player_name": player.name,
                    "content": discuss_content,
                    "round": self.state.round,
                },
            )

    async def run_day_vote(self) -> None:
        self._sync_alive_players()
        self.state.phase = Phase.DAY_VOTE
        self.broadcast("phase_change", {"phase": self.state.phase.value})

        current_votes: dict[int, int] = {}
        alive = self.state.alive_players

        for player in alive:
            agent = self.agents[player.id]
            target_id = agent.vote(current_votes)
            current_votes[player.id] = target_id
            self.state.votes.append(Vote(voter_id=player.id, target_id=target_id))

        # Tally
        tallied = Counter(current_votes.values())
        self.broadcast("vote_result", {"votes": current_votes, "tally": dict(tally=tallied)})

        max_count = tallied.most_common(1)[0][1]
        top_targets = [t for t, c in tallied.items() if c == max_count]

        if len(top_targets) == 1:
            self._elimination_target = top_targets[0]
        else:
            # Tie: re-vote once, else no elimination
            self._sync_alive_players()
            revote_results: dict[int, int] = {}
            for player in alive:
                agent = self.agents[player.id]
                target_id = agent.vote(current_votes)
                revote_results[player.id] = target_id

            revote_tally = Counter(revote_results.values())
            max_count2 = revote_tally.most_common(1)[0][1]
            top2 = [t for t, c in revote_tally.items() if c == max_count2]
            self._elimination_target = top2[0] if len(top2) == 1 else None

    async def run_day_elimination(self) -> None:
        target_id = getattr(self, "_elimination_target", None)
        if target_id is None:
            self.broadcast("elimination", {"message": "平票，无人出局"})
            return

        player = self.state.get_player(target_id)
        if player is None:
            return

        player.alive = False
        player.revealed = True

        self.state.elimination_history.append(
            {"round": self.state.round, "player_id": target_id, "cause": "vote"}
        )

        self.broadcast(
            "elimination",
            {
                "player_id": target_id,
                "player_name": player.name,
                "role": player.role.value,
                "cause": "vote",
            },
        )

        # Hunter revenge (not poisoned)
        if player.role == Role.HUNTER:
            await self._trigger_hunter_shot(player)

    # ------------------------------------------------------------------
    # Night result processing
    # ------------------------------------------------------------------

    def process_night_results(self) -> None:
        deaths: list[dict] = []
        saved = False

        # Check wolf kill
        kill_target_id = self.state.night_kill_target
        if kill_target_id is not None:
            guarded = self.state.guard_target == kill_target_id
            witch_saved = self.state.night_saved
            # 同守同救 rule: guard + witch save on same target = death
            double_save = guarded and witch_saved

            if guarded and not witch_saved:
                saved = True
            elif witch_saved and not guarded:
                saved = True
            elif double_save:
                saved = False  # Dies due to 同守同救
            else:
                saved = False

            if not saved:
                killed = self.state.get_player(kill_target_id)
                if killed:
                    killed.alive = False
                    killed.revealed = True
                    deaths.append(
                        {"player_id": kill_target_id, "player_name": killed.name, "role": killed.role.value, "cause": "werewolf_kill"}
                    )
                    self.state.elimination_history.append(
                        {"round": self.state.round, "player_id": kill_target_id, "cause": "werewolf_kill"}
                    )

        # Check witch poison
        poison_id = self.state.night_poison_target
        poisoned_player = None
        if poison_id is not None:
            poisoned = self.state.get_player(poison_id)
            if poisoned and poisoned.alive:
                poisoned.alive = False
                poisoned.revealed = True
                poisoned_player = poisoned
                deaths.append(
                    {"player_id": poison_id, "player_name": poisoned.name, "role": poisoned.role.value, "cause": "poison"}
                )
                self.state.elimination_history.append(
                    {"round": self.state.round, "player_id": poison_id, "cause": "poison"}
                )

        # Update guard last target
        if self.state.guard_target is not None:
            self.state.guard_last_target = self.state.guard_target
        self.state.guard_target = None

        self.broadcast("night_result", {"deaths": deaths, "round": self.state.round})

        # Hunter killed by werewolf (not poison) triggers revenge
        for death in deaths:
            if death["cause"] == "werewolf_kill":
                killed = self.state.get_player(death["player_id"])
                if killed and killed.role == Role.HUNTER:
                    # Need to run async hunter shot – handled via a sync wrapper
                    # stored for the caller to trigger after this sync method
                    self._pending_hunter_shots = getattr(self, "_pending_hunter_shots", [])
                    self._pending_hunter_shots.append(killed)

    async def _fire_pending_hunter_shots(self) -> None:
        shots = getattr(self, "_pending_hunter_shots", [])
        for hunter in shots:
            await self._trigger_hunter_shot(hunter)
        self._pending_hunter_shots = []

    # ------------------------------------------------------------------
    # Game over check
    # ------------------------------------------------------------------

    async def check_game_over(self) -> bool:
        # Fire any pending hunter shots first
        await self._fire_pending_hunter_shots()

        wolves = self.get_alive_wolves()
        specials = self.get_alive_special_roles()
        villagers = [p for p in self.state.alive_players if p.camp == Camp.VILLAGER and p.role == Role.VILLAGER]

        if not wolves:
            self.state.game_over = True
            self.state.winner = Camp.VILLAGER
            self.broadcast("game_over", {"winner": Camp.VILLAGER.value, "reason": "所有狼人已出局"})
            return True

        all_villagers_dead = len(villagers) == 0 and len(specials) == 0
        all_specials_dead = len(specials) == 0
        # Wolves win if all special roles dead (even if regular villagers alive)
        if all_specials_dead or all_villagers_dead:
            self.state.game_over = True
            self.state.winner = Camp.WEREWOLF
            self.broadcast("game_over", {"winner": Camp.WEREWOLF.value, "reason": "好人阵营全部出局"})
            return True

        return False

    # ------------------------------------------------------------------
    # Hunter revenge
    # ------------------------------------------------------------------

    async def _trigger_hunter_shot(self, hunter: Player) -> None:
        self.state.phase = Phase.HUNTER_SHOT
        self.broadcast("hunter_shot", {"player_id": hunter.id, "player_name": hunter.name})

        agent = self.agents[hunter.id]
        context = self._game_state_summary_for(agent)
        context += f"\n你是猎人 {hunter.name}，你已死亡。请选择一名玩家开枪带走。"

        action = agent.night_action(context)
        if action is None or action.target_id is None:
            return

        target = self.state.get_player(action.target_id)
        if target and target.alive:
            target.alive = False
            target.revealed = True
            self.state.elimination_history.append(
                {"round": self.state.round, "player_id": target.id, "cause": "hunter_shot"}
            )
            self.broadcast(
                "elimination",
                {
                    "player_id": target.id,
                    "player_name": target.name,
                    "role": target.role.value,
                    "cause": "hunter_shot",
                },
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_alive_wolves(self) -> list[Player]:
        return [p for p in self.state.alive_players if p.role == Role.WEREWOLF]

    def get_alive_special_roles(self) -> list[Player]:
        return [p for p in self.state.alive_players if p.camp == Camp.VILLAGER and p.role != Role.VILLAGER]

    def broadcast(self, event_type: str, data: dict) -> None:
        self.event_queue.append({"type": event_type, "data": data})

    def get_events(self) -> list[dict]:
        events = list(self.event_queue)
        self.event_queue.clear()
        return events

    def _find_alive_role(self, role: Role) -> Optional[Player]:
        for p in self.state.alive_players:
            if p.role == role:
                return p
        return None

    def _last_eliminated_id(self) -> Optional[int]:
        if not self.state.elimination_history:
            return None
        last = self.state.elimination_history[-1]
        return last.get("player_id")

    def _sync_alive_players(self) -> None:
        alive_ids = {p.id for p in self.state.alive_players}
        for agent in self.agents.values():
            agent.memory.set_alive_players(alive_ids)

    def _game_state_summary_for(self, agent: AgentBase) -> str:
        alive = [f"{p.name}(ID:{p.id})" for p in self.state.alive_players]
        summary = f"当前回合: 第{self.state.round}天\n"
        summary += f"存活玩家: {', '.join(alive)}\n"
        summary += agent.memory.get_state_summary()
        return summary

    def _build_wolf_discussion_prompt(self, state_summary: str) -> str:
        return (
            f"{state_summary}\n"
            "现在是狼人讨论时间。请和你的狼队友讨论今晚要杀谁。"
        )
