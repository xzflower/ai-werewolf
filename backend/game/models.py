from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Role(Enum):
    WEREWOLF = "werewolf"
    SEER = "seer"
    WITCH = "witch"
    HUNTER = "hunter"
    GUARD = "guard"
    VILLAGER = "villager"

    def display_name(self) -> str:
        names = {
            Role.WEREWOLF: "狼人",
            Role.SEER: "预言家",
            Role.WITCH: "女巫",
            Role.HUNTER: "猎人",
            Role.GUARD: "守卫",
            Role.VILLAGER: "村民",
        }
        return names[self]


class Camp(Enum):
    WEREWOLF = "werewolf"
    VILLAGER = "villager"

    def display_name(self) -> str:
        names = {
            Camp.WEREWOLF: "狼人阵营",
            Camp.VILLAGER: "好人阵营",
        }
        return names[self]


class Phase(Enum):
    NIGHT_WEREWOLF = "night_werewolf"
    NIGHT_SEER = "night_seer"
    NIGHT_WITCH = "night_witch"
    NIGHT_HUNTER = "night_hunter"
    NIGHT_GUARD = "night_guard"
    DAY_ANNOUNCE = "day_announce"
    DAY_SPEECH = "day_speech"
    DAY_DISCUSSION = "day_discussion"
    DAY_VOTE = "day_vote"
    VOTE_RESULT = "vote_result"
    HUNTER_SHOT = "hunter_shot"
    GAME_OVER = "game_over"

    def display_name(self) -> str:
        names = {
            Phase.NIGHT_WEREWOLF: "狼人行动",
            Phase.NIGHT_SEER: "预言家行动",
            Phase.NIGHT_WITCH: "女巫行动",
            Phase.NIGHT_HUNTER: "猎人行动",
            Phase.NIGHT_GUARD: "守卫行动",
            Phase.DAY_ANNOUNCE: "天亮公告",
            Phase.DAY_SPEECH: "白天发言",
            Phase.DAY_DISCUSSION: "白天讨论",
            Phase.DAY_VOTE: "白天投票",
            Phase.VOTE_RESULT: "投票结果",
            Phase.HUNTER_SHOT: "猎人开枪",
            Phase.GAME_OVER: "游戏结束",
        }
        return names[self]


@dataclass
class Player:
    id: int
    name: str
    role: Role
    camp: Camp
    alive: bool = True
    seat: int = 0
    revealed: bool = False


@dataclass
class Speech:
    player_id: int
    content: str
    round: int
    is_public: bool = True
    is_inner_monologue: bool = False


@dataclass
class Vote:
    voter_id: int
    target_id: int


@dataclass
class NightAction:
    player_id: int
    action_type: str
    target_id: Optional[int] = None
    round: int = 0


@dataclass
class BeliefEntry:
    player_id: int
    guessed_role: Optional[str] = None
    confidence: float = 0.0
    reason: str = ""


@dataclass
class ReflectionOutput:
    analysis: str
    strategy: str
    inner_monologue: str
    decision: str


@dataclass
class GameConfig:
    time_limit_enabled: bool = False
    speech_timeout: int = 30
    vote_timeout: int = 20
    night_timeout: int = 15
    experience_pool_enabled: bool = False


@dataclass
class GameState:
    phase: Phase = Phase.NIGHT_WEREWOLF
    round: int = 0
    day_count: int = 0
    players: list[Player] = field(default_factory=list)
    speeches: list[Speech] = field(default_factory=list)
    votes: list[Vote] = field(default_factory=list)
    night_actions: list[NightAction] = field(default_factory=list)
    elimination_history: list[dict] = field(default_factory=list)
    night_kill_target: Optional[int] = None
    night_saved: bool = False
    night_poison_target: Optional[int] = None
    guard_target: Optional[int] = None
    guard_last_target: Optional[int] = None
    witch_save_used: bool = False
    witch_poison_used: bool = False
    hunter_activated: bool = False
    game_over: bool = False
    winner: Optional[Camp] = None
    speech_order: list[int] = field(default_factory=list)
    current_speaker_index: int = 0
    config: GameConfig = field(default_factory=GameConfig)

    @property
    def alive_players(self) -> list[Player]:
        return [p for p in self.players if p.alive]

    @property
    def werewolf_count(self) -> int:
        return len([p for p in self.alive_players if p.role == Role.WEREWOLF])

    @property
    def villager_count(self) -> int:
        return len([p for p in self.alive_players if p.role != Role.WEREWOLF])

    def get_player(self, player_id: int) -> Optional[Player]:
        for p in self.players:
            if p.id == player_id:
                return p
        return None
