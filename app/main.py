"""API + WebSocket + dashboard web.

Ejecutar:  python -m app.main     (abre http://127.0.0.1:8000)
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Dict, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .brokers.base import BrokerError
from .config import ROOT, load_settings
from .orchestrator import LIVE_CONFIRMATION, TradingSystem

settings = load_settings()
system = TradingSystem(settings)
clients: Set[WebSocket] = set()


async def broadcaster() -> None:
    while True:
        if clients:
            payload = json.dumps(system.snapshot(), default=str)
            for ws in list(clients):
                try:
                    await ws.send_text(payload)
                except Exception:
                    clients.discard(ws)
        await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(_: FastAPI):
    tasks = [asyncio.create_task(system.scheduler_loop()), asyncio.create_task(broadcaster())]
    yield
    for t in tasks:
        t.cancel()
    if system.positions:
        await system.stop("Apagado del servidor", manual=False)


app = FastAPI(title="Investments – Multi-Agent Trading", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")


@app.get("/")
async def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/state")
async def state():
    return JSONResponse(json.loads(json.dumps(system.snapshot(full_curve=True), default=str)))


@app.post("/api/control/{action}")
async def control(action: str):
    actions = {"start": system.start, "pause": system.pause, "resume": system.resume,
               "stop": system.stop, "kill": system.kill, "reset": system.reset}
    if action not in actions:
        raise HTTPException(404, "Acción desconocida")
    await actions[action]()
    return {"ok": True, "state": system.state.value, "reason": system.state_reason}


@app.get("/api/brokers")
async def brokers():
    rec = system.broker_analyst.recommend()
    rec["live_confirmation_phrase"] = LIVE_CONFIRMATION
    rec["live_allowed_by_env"] = settings.live_allowed_by_env
    rec["current"] = {"broker": system.broker.name, "live": system.broker.is_live, "feed": system.feed.name}
    return rec


class ConnectReq(BaseModel):
    broker: str
    credentials: Dict[str, str] = {}
    confirmation: str = ""


@app.post("/api/brokers/connect")
async def connect(req: ConnectReq):
    try:
        return await system.connect_broker(req.broker, req.credentials, req.confirmation)
    except BrokerError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # errores de red/credenciales
        raise HTTPException(400, f"No se pudo conectar: {e}")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        clients.discard(ws)


def run() -> None:
    import uvicorn
    uvicorn.run("app.main:app", host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")),
                log_level="info")


if __name__ == "__main__":
    run()
