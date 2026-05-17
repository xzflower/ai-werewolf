"""快速测试游戏引擎 - 独立调用各阶段"""
import sys
sys.path.insert(0, '/home/ubuntu/ai-werewolf')
import asyncio

from backend.game.gm import GameMaster
from backend.game.models import GameConfig, Phase

async def test():
    config = GameConfig(time_limit_enabled=False)
    gm = GameMaster(config)
    gm.init_game()

    print("角色分配:")
    for p in gm.state.players:
        suffix = " 🐺" if p.role.name == "WEREWOLF" else ""
        print(f"  玩家{p.id:2d}: {p.role.display_name()}{suffix}")
    print()

    # 跑第一夜
    print("=" * 40)
    print("🌙 第一夜")
    print("=" * 40)
    await gm.run_night_werewolf()
    await gm.run_night_seer()
    await gm.run_night_witch()
    await gm.run_night_guard()
    gm.process_night_results()

    print("\n📢 夜晚事件:")
    for e in gm.get_events():
        t = e.get("type", "")
        d = e.get("data", {})
        if t == "phase_change":
            pass  # skip phase changes for brevity
        elif t == "wolf_chat":
            print(f"  🐺 狼{d.get('player_id')}: {d.get('content','')[:60]}")
        elif t == "night_action":
            print(f"  ⚔️  玩家{d['player_id']}: {d.get('action_type')}")
        elif t == "night_result":
            deaths = d.get("deaths", [])
            if deaths:
                for death in deaths:
                    print(f"  💀 {death.get('player_name')} ({death.get('role')}) - {death.get('cause')}")
            else:
                print(f"  🌙 平安夜")
        elif t == "seer_result":
            print(f"  🔮 预言家查: 玩家{d['target_id']} -> {d['camp']}")

    # 白天 - 发言
    print("\n" + "=" * 40)
    print("☀️ 白天发言")
    print("=" * 40)
    await gm.run_day_speech()

    for e in gm.get_events():
        t = e.get("type", "")
        d = e.get("data", {})
        if t == "speech":
            pid = d.get("player_id", "")
            content = d.get("content", "")
            im = d.get("inner_monologue", "")
            print(f"\n  🗣 玩家{pid}: {content[:120]}")
            if im:
                print(f"  💭 内心: {im[:100]}")

    # 投票
    print("\n" + "=" * 40)
    print("🗳 投票放逐")
    print("=" * 40)
    await gm.run_day_vote()
    await gm.run_day_elimination()

    for e in gm.get_events():
        t = e.get("type", "")
        d = e.get("data", {})
        if t == "vote_result":
            print(f"  📊 投票: {d.get('votes', {})}")
        elif t == "elimination":
            pid = d.get("player_id")
            role = d.get("role", "")
            print(f"  ⚰️  放逐: 玩家{pid} ({role})")

    # 存活状态
    print("\n" + "=" * 40)
    print(f"📊 存活玩家: {len(gm.state.alive_players)}人")
    for p in gm.state.alive_players:
        print(f"  玩家{p.id}: {p.role.display_name()}")

    print("\n" + "=" * 40)
    print("🏁 测试完成")
    print("=" * 40)

asyncio.run(test())
