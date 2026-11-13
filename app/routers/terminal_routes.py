import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from .. import auth, terminal

router = APIRouter()
api = APIRouter(prefix="/api/terminal", dependencies=[Depends(auth.require_csrf)])


@api.get("/sessions")
def sessions():
    return terminal.registry.list()


@api.delete("/sessions/{sid}")
def kill_session(sid: str):
    if not terminal.registry.kill(sid):
        raise HTTPException(404, "No such terminal session")
    return {"ok": True}


@router.websocket("/ws/terminal")
async def ws_terminal(ws: WebSocket, session: str = "", cols: int = 80, rows: int = 24):
    if not auth.ws_authorized(ws):
        await ws.close(code=4401)
        return
    await ws.accept()
    loop = asyncio.get_running_loop()
    sess = terminal.registry.get(session) if session else None
    reattached = sess is not None
    if sess is None:
        try:
            sess = terminal.registry.create(loop, cols, rows)
        except terminal.TerminalError as exc:
            await ws.send_json({"type": "error", "message": str(exc)})
            await ws.close()
            return
    else:
        sess.resize(cols, rows)
    queue, snapshot = sess.subscribe()
    await ws.send_json({"type": "session", "id": sess.id, "reattached": reattached})
    if snapshot:
        await ws.send_bytes(snapshot)

    async def sender():
        while True:
            data = await queue.get()
            if data is None:
                await ws.send_json({"type": "exit"})
                return
            await ws.send_bytes(data)

    async def receiver():
        while True:
            try:
                msg = json.loads(await ws.receive_text())
            except (json.JSONDecodeError, KeyError):
                continue
            kind = msg.get("type")
            if kind == "input" and isinstance(msg.get("data"), str):
                sess.write(msg["data"].encode("utf-8"))
            elif kind == "resize":
                sess.resize(msg.get("cols", 80), msg.get("rows", 24))

    tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        for t in tasks:
            t.cancel()
        sess.unsubscribe(queue)  # the shell itself keeps running
        try:
            await ws.close()
        except Exception:
            pass
