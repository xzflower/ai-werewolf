from __future__ import annotations

import random
from typing import Optional

from backend.game.models import Camp, Player, Role

ROLE_CAMPS: dict[Role, Camp] = {
    Role.WEREWOLF: Camp.WEREWOLF,
    Role.SEER: Camp.VILLAGER,
    Role.WITCH: Camp.VILLAGER,
    Role.HUNTER: Camp.VILLAGER,
    Role.GUARD: Camp.VILLAGER,
    Role.VILLAGER: Camp.VILLAGER,
}

ROLE_COUNTS_12PLAYER: dict[Role, int] = {
    Role.WEREWOLF: 3,
    Role.SEER: 1,
    Role.WITCH: 1,
    Role.HUNTER: 1,
    Role.GUARD: 1,
    Role.VILLAGER: 5,
}

ROLE_DESCRIPTIONS: dict[Role, str] = {
    Role.WEREWOLF: (
        "你是狼人。每晚你可以选择一名玩家进行击杀。"
        "白天你需要伪装身份，融入好人阵营，避免被投票出局。"
    ),
    Role.SEER: (
        "你是预言家。每晚你可以查验一名玩家的身份，"
        "得知其是否为狼人。利用你的信息引导好人阵营取得胜利。"
    ),
    Role.WITCH: (
        "你是女巫。你拥有一瓶解药和一瓶毒药。"
        "解药可以救活当晚被狼人杀害的玩家，毒药可以毒杀一名玩家。"
        "每瓶药整场游戏只能使用一次。"
    ),
    Role.HUNTER: (
        "你是猎人。当你被投票出局或被狼人杀害时，"
        "你可以开枪带走一名玩家。你的最后一击至关重要。"
    ),
    Role.GUARD: (
        "你是守卫。每晚你可以选择守护一名玩家，"
        "被守护的玩家当晚不会被狼人杀害。"
        "你不能连续两晚守护同一名玩家。"
    ),
    Role.VILLAGER: (
        "你是普通村民。你没有特殊技能，"
        "但你的投票权至关重要。仔细倾听发言，"
        "分析谁是狼人，用投票将狼人驱逐出局。"
    ),
}


def generate_role_assignment() -> list[tuple[Role, str]]:
    roles: list[Role] = []
    for role, count in ROLE_COUNTS_12PLAYER.items():
        roles.extend([role] * count)
    random.shuffle(roles)

    assignment: list[tuple[Role, str]] = []
    for i, role in enumerate(roles, start=1):
        name = f"玩家{i}"
        assignment.append((role, name))

    return assignment


def create_players() -> list[Player]:
    assignment = generate_role_assignment()
    players: list[Player] = []
    for seat, (role, name) in enumerate(assignment, start=1):
        player = Player(
            id=seat,
            name=name,
            role=role,
            camp=ROLE_CAMPS[role],
            seat=seat,
        )
        players.append(player)
    return players
