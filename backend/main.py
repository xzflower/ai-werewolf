from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.game.gm import GameMaster
from backend.game.models import GameConfig

app = FastAPI(title="AI Werewolf")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

active_games: dict[str, dict[str, Any]] = {}


class StartRequest(BaseModel):
    config: GameConfig | None = None


class StartResponse(BaseModel):
    game_id: str


@app.post("/api/game/start", response_model=StartResponse)
async def start_game(body: StartRequest | None = None):
    game_id = uuid.uuid4().hex
    config = body.config if body and body.config else GameConfig()
    gm = GameMaster(config=config)
    gm.init_game()

    active_games[game_id] = {"gm": gm, "clients": set()}

    # Push the game_init events that init_game() already broadcast
    _flush_events(game_id)

    asyncio.create_task(_run_and_cleanup(game_id))
    return StartResponse(game_id=game_id)


@app.get("/api/game/state")
def get_state(game_id: str):
    entry = active_games.get(game_id)
    if entry is None:
        return {"error": "game not found"}
    gs = entry["gm"].state
    return {
        "phase": gs.phase.value,
        "round": gs.round,
        "day_count": gs.day_count,
        "alive_players": [
            {"id": p.id, "name": p.name, "alive": p.alive, "seat": p.seat}
            for p in gs.players
        ],
        "game_over": gs.game_over,
        "winner": gs.winner.value if gs.winner else None,
    }


@app.websocket("/ws/{game_id}")
async def ws_endpoint(websocket: WebSocket, game_id: str):
    entry = active_games.get(game_id)
    if entry is None:
        await websocket.close(code=4004, reason="game not found")
        return

    await websocket.accept()
    clients: set[WebSocket] = entry["clients"]
    clients.add(websocket)
    try:
        # Keep connection alive; client only listens
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(websocket)


async def _run_and_cleanup(game_id: str) -> None:
    entry = active_games.get(game_id)
    if entry is None:
        return

    gm: GameMaster = entry["gm"]

    broadcaster_task = asyncio.create_task(_broadcaster(game_id))

    with suppress(Exception):
        await gm.run_game()

    # Drain remaining events after game ends
    await asyncio.sleep(0.5)
    _flush_events(game_id)

    broadcaster_task.cancel()
    with suppress(asyncio.CancelledError):
        await broadcaster_task


async def _broadcaster(game_id: str) -> None:
    entry = active_games.get(game_id)
    if entry is None:
        return

    gm: GameMaster = entry["gm"]
    clients: set[WebSocket] = entry["clients"]

    while True:
        events = gm.get_events()
        if events:
            disconnected = []
            for ws in clients:
                for event in events:
                    try:
                        await ws.send_json(event)
                    except Exception:
                        disconnected.append(ws)
            for ws in disconnected:
                clients.discard(ws)
        await asyncio.sleep(0.1)


def _flush_events(game_id: str) -> None:
    entry = active_games.get(game_id)
    if entry is None:
        return
    gm: GameMaster = entry["gm"]
    clients: set[WebSocket] = entry["clients"]
    for event in gm.get_events():
        for ws in list(clients):
            with suppress(Exception):
                asyncio.get_event_loop().run_until_complete(ws.send_json(event))
