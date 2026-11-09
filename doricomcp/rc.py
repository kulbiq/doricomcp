"""Dorico Remote Control WebSocket client (ws://127.0.0.1:4560).

One connection, one background reader. Requests are serialised by a lock because Dorico's
replies carry no request id: a `command` is answered by the next `response` message, a `get*`
request by its named list message. Pushes (`status`, `selectionchanged`, `propertieslist`, ...)
are kept as the latest copy per message name.

Depends on: nothing else in the package.
"""
import asyncio
import json
import os
import pathlib

import websockets

URL = os.environ.get("DORICOMCP_RC_URL", "ws://127.0.0.1:4560")
HOME = pathlib.Path(os.environ.get("DORICOMCP_HOME", pathlib.Path.home() / ".doricomcp"))
TOKEN_FILE = HOME / "session_token"
CLIENT = "doricomcp"  # the name Dorico shows in its approval prompt; a new name asks again

# get* message -> the message name Dorico answers with
REPLY = {
    "getappinfo": "appinfo", "getcommands": "commandlist", "getflows": "flowslist",
    "getlayouts": "layoutslist", "getlibrarycollections": "librarycollectionslist",
    "getlibraryentities": "libraryentitieslist", "getoptions": "optionslist",
    "getplaybacktechniques": "playbacktechniqueslist", "getproperties": "propertieslist",
    "getstatus": "status",
}


class RCError(RuntimeError):
    pass


class RemoteControl:
    def __init__(self):
        self.ws = None
        self.latest: dict[str, dict] = {}  # last push per message name
        self._lock = asyncio.Lock()
        self._waiters: list[tuple[str, asyncio.Future]] = []
        self._reader = None

    async def connect(self):
        if self.ws is not None:
            return
        try:
            await self._handshake()
        except websockets.ConnectionClosed as e:
            # a token issued to another client name (or revoked in Dorico): drop it and ask Dorico again
            if "TokenMismatch" not in str(e) or not TOKEN_FILE.exists():
                raise
            TOKEN_FILE.unlink()
            await self._handshake()

    async def _handshake(self):
        try:
            ws = await websockets.connect(URL, max_size=None)
        except OSError as e:
            raise RCError(f"Dorico is not reachable at {URL}: start Dorico and turn on Remote Control in its "
                          f"Preferences ({e.strerror or e})") from e
        hello = {"message": "connect", "clientName": CLIENT, "handshakeVersion": "1.0",
                 "clientoptions": {"sendPropertiesListOnSelectionChange": True}}
        if TOKEN_FILE.exists():
            hello["sessionToken"] = TOKEN_FILE.read_text().strip()
        await ws.send(json.dumps(hello))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("message") == "sessiontoken":
                HOME.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - once per approval
                TOKEN_FILE.write_text(msg["sessionToken"])
                await ws.send(json.dumps({"message": "acceptsessiontoken", "sessionToken": msg["sessionToken"]}))
            elif msg.get("message") == "response":
                if msg.get("code") != "kConnected":
                    await ws.close()
                    raise RCError(f"handshake failed: {msg}")
                break
        self.ws = ws
        self._reader = asyncio.create_task(self._read())

    async def _read(self):
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                name = msg.get("message")
                # Dorico pushes only the changed status fields (no hasSelection, ...); getstatus answers with all of them
                partial = name == "status" and "hasScore" not in msg
                if name == "status":
                    msg = {**self.latest.get("status", {}), **msg}
                self.latest[name] = msg
                for i, (want, fut) in enumerate(self._waiters):
                    if want == name and not partial and not fut.done():
                        fut.set_result(msg)
                        del self._waiters[i]
                        break
        except websockets.ConnectionClosed:
            pass  # Dorico quit or restarted; pending waiters fail below, next request reconnects
        finally:
            self.ws = None
            for _, fut in self._waiters:
                if not fut.done():
                    fut.set_exception(RCError("Remote Control connection closed"))
            self._waiters.clear()

    async def request(self, payload: dict, timeout: float = 15.0) -> dict:
        """Send one message and return its reply (`response` for commands, the named list otherwise)."""
        await self.connect()
        want = REPLY.get(payload["message"], "response")
        async with self._lock:
            fut = asyncio.get_running_loop().create_future()
            self._waiters.append((want, fut))
            await self.ws.send(json.dumps(payload))
            try:
                return await asyncio.wait_for(fut, timeout)
            except TimeoutError:
                self._waiters = [w for w in self._waiters if w[1] is not fut]
                raise RCError(f"no {want!r} reply to {payload['message']} within {timeout}s") from None

    async def command(self, command: str, timeout: float = 30.0) -> dict:
        """Run a Dorico command string. Returns the `response` ({code, detail}); raises unless kOK."""
        r = await self.request({"message": "command", "command": command}, timeout)
        if r.get("code") != "kOK":
            raise RCError(f"{command}: {r.get('code')} {r.get('detail', '')}".strip())
        return r

    async def undo(self, count: int = 1):
        """Edit.Undo `count` times. After a Lua script Dorico's command-enabled state is stale and the first
        Edit.Undo is refused (kCommandNotAllowed); any non-undoable command refreshes it.
        Re-selecting the current window mode is invisible and adds no undo step (verified by element counts)."""
        mode = (await self.status()).get("windowMode") or "kWriteMode"
        await self.command(f"Window.SwitchMode?WindowMode={mode}")
        for _ in range(count):
            await self.command("Edit.Undo")

    async def redo(self, count: int = 1):
        mode = (await self.status()).get("windowMode") or "kWriteMode"
        await self.command(f"Window.SwitchMode?WindowMode={mode}")
        for _ in range(count):
            await self.command("Edit.Redo")

    async def status(self) -> dict:
        return await self.request({"message": "getstatus"})

    async def close(self):
        if self.ws is not None:
            await self.ws.close()
        if self._reader:
            await asyncio.gather(self._reader, return_exceptions=True)


def _self_check():
    """A pushed partial status must not answer getstatus, and must be merged into the full one."""
    class FakeWS:
        def __init__(self, msgs):
            self.msgs = [json.dumps(m) for m in msgs]

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self.msgs:
                raise StopAsyncIteration
            await asyncio.sleep(0)
            return self.msgs.pop(0)

    async def run():
        rc = RemoteControl()
        rc.latest["status"] = {"message": "status", "hasScore": True, "hasSelection": False, "selectedEventType": ""}
        fut = asyncio.get_running_loop().create_future()
        rc._waiters.append(("status", fut))
        rc.ws = FakeWS([{"message": "status", "selectedEventType": "kNoteEvent"},
                        {"message": "status", "hasScore": True, "hasSelection": True, "selectedEventType": "kNoteEvent"}])
        await rc._read()
        assert fut.result()["hasSelection"] is True, fut.result()
        rc.latest["status"] = {"message": "status", "hasScore": True, "hasSelection": True, "zoomPercent": 100}
        rc.ws = FakeWS([{"message": "status", "zoomPercent": 200}])
        await rc._read()
        assert rc.latest["status"] == {"message": "status", "hasScore": True, "hasSelection": True, "zoomPercent": 200}

    asyncio.run(run())
    print("rc self-check ok")


if __name__ == "__main__":
    _self_check()
