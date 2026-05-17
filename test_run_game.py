#!/usr/bin/env python3
"""快速对称测试：跑完整 run_game() 看是否卡住"""
import sys, os
sys.path.insert(0, '/home/ubuntu/ai-werewolf')
os.environ['NO_PROXY'] = '*'
for k in list(os.environ):
    if 'proxy' in k.lower() or 'PROXY' in k:
        del os.environ[k]

import asyncio
from backend.game.gm import GameMaster
from backend.game.models import GameConfig

async def run():
    print("Creating GM...", flush=True)
    gm = GameMaster(GameConfig(time_limit_enabled=False))
    gm.init_game()
    
    for p in gm.state.players:
        print(f"  P{p.id}: {p.role.value}", flush=True)
    
    print("\nStarting run_game()...", flush=True)
    await asyncio.wait_for(gm.run_game(), timeout=300)
    print(f"\nWinner: {gm.state.winner}", flush=True)
    print(f"Rounds: {gm.state.round}", flush=True)
    print("DONE", flush=True)

asyncio.run(run())
