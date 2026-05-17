#!/usr/bin/env python3
"""快速测试：1局游戏 + 生产评测报告"""
import sys, os, json, time, traceback
sys.path.insert(0, '/home/ubuntu/ai-werewolf')

from backend.game.gm import GameMaster
from backend.game.models import GameConfig

os.environ["NO_PROXY"] = "*"
for k in list(os.environ):
    if 'proxy' in k.lower():
        del os.environ[k]

print("Starting game...", flush=True)
config = GameConfig(time_limit_enabled=False)
gm = GameMaster(config)
gm.init_game()

alive = [(p.id, p.role.value) for p in gm.state.players]
print(f"Roles: {alive}", flush=True)

import asyncio
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
try:
    loop.run_until_complete(gm.run_game())
except Exception as e:
    traceback.print_exc()
finally:
    loop.close()

print(f"\nWinner: {gm.state.winner}", flush=True)
print(f"Rounds: {gm.state.round}", flush=True)
print(f"Deaths: {gm.state.elimination_history}", flush=True)
print("DONE", flush=True)
