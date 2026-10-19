"""Lua transaction bridge: one call = one generated self-contained Lua script run by Script.RunScript.

The script is lua/lib.lua + `local REQ = <request literal>` + a dispatcher. It writes `<id>.json`
then `<id>.done` (the marker is written last, so a present marker means the JSON is complete).
Script.RunScript returns before the Lua runs, so Python waits on the marker.
A script is one undo step in Dorico; a read-only script adds none.

Depends on: logtail, rc, windows.
"""
import asyncio
import json
import pathlib
import subprocess
import time
import uuid

from .logtail import LOG
from .rc import HOME, RemoteControl

RUN_DIR = HOME / "run"  # no spaces: the path goes into a command string unescaped
LIB = pathlib.Path(__file__).with_name("lua") / "lib.lua"


class LuaError(RuntimeError):
    pass


class StillRunning(LuaError):
    """The script has not finished: Dorico is blocked (dialog) or very slow. It may still change the score, so
    nothing may be read back or undone against it."""


HARD_LIMIT = 600.0  # one fixed ceiling for a genuinely hung Dorico; dialogs are caught much earlier


def lua_literal(v) -> str:
    """Python value -> Lua literal (dicts become tables keyed by string, lists 1-based arrays)."""
    if v is None:
        return "nil"
    if v is True or v is False:
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return '"' + "".join(c if 32 <= ord(c) < 127 and c not in '"\\' else "".join(f"\\{b:03d}" for b in c.encode()) for c in v) + '"'
    if isinstance(v, (list, tuple)):
        return "{" + ",".join(lua_literal(x) for x in v) + "}"
    if isinstance(v, dict):
        return "{" + ",".join(f"[{lua_literal(str(k))}]={lua_literal(x)}" for k, x in v.items()) + "}"
    raise TypeError(f"cannot pass {type(v).__name__} to Lua")


async def _wait_finished(script: str, offset: int, deadline: float):
    needle = f"notifyPostCommandExecute: Script.RunScript?ScriptPath={script}".encode()
    def seen() -> bool:
        try:
            with open(LOG, "rb") as f:
                f.seek(offset)
                return needle in f.read()
        except FileNotFoundError:
            return True
    while time.monotonic() < deadline:
        if await asyncio.to_thread(seen):
            return
        await asyncio.sleep(0.01)
    raise LuaError(f"{script}: Dorico did not finish the script command in time")


def _dialogs() -> list[dict]:
    from .windows import dialogs
    try:
        return dialogs()
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError):  # no swiftc / no permission: best effort
        return []


class Bridge:
    def __init__(self, rc: RemoteControl):
        self.rc = rc
        self._lock = asyncio.Lock()

    async def run(self, op: str, timeout: float = 20.0, extra_lua: str = "", **req):
        """Run lib op `op` with request fields `req`; return its result or raise LuaError."""
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        rid = uuid.uuid4().hex
        script, out, done = (RUN_DIR / f"{rid}{ext}" for ext in (".lua", ".json", ".done"))
        req["op"] = op
        script.write_text(
            f"local REQ = {lua_literal(req)}\n"
            f"local OUT, DONE = {lua_literal(str(out))}, {lua_literal(str(done))}\n"
            + LIB.read_text() + "\n" + extra_lua + "\nreturn RUN()\n")
        async with self._lock:
            running = False
            try:
                log0 = LOG.stat().st_size if LOG.exists() else 0
                await self.rc.command(f"Script.RunScript?ScriptPath={script}")
                running = True
                t0 = time.monotonic()
                # Never give up on a running script: Dorico interleaves Remote Control commands with the script's
                # own doCommand calls, so a read or Edit.Undo sent now would land in the middle of it (an undo
                # once landed between two NoteInput.Pitch commands, and the script kept typing).
                check = t0 + timeout
                while not done.exists():
                    now = time.monotonic()
                    if now > check:
                        if d := _dialogs():
                            raise StillRunning(f"op {op!r}: Dorico shows a dialog ({d[0]['w']}x{d[0]['h']} '{d[0]['name']}') "
                                               "and the edit has not finished; answer it with list_dialogs + dialog_click (or in Dorico)")
                        if now - t0 > HARD_LIMIT:
                            raise StillRunning(f"op {op!r}: Dorico has not finished after {now - t0:.0f}s")
                        check = now + 5
                    await asyncio.sleep(0.02)
                running = False
                payload = json.loads(out.read_text())
                # The marker is written inside the script; Dorico is still executing RunScript until it logs
                # notifyPostCommandExecute. Commands sent before that (e.g. Edit.Undo) get kCommandNotAllowed.
                await _wait_finished(str(script), log0, time.monotonic() + timeout)
            finally:
                # a script still running writes its markers later; leave them rather than race it
                for p in () if running else (script, out, done):
                    p.unlink(missing_ok=True)
        if not payload.get("ok"):
            raise LuaError(f"op {op!r} failed in Dorico: {payload.get('error')}")
        return payload.get("result")


if __name__ == "__main__":
    import tempfile

    class SlowDorico:  # writes the result 0.5 s after RunScript, well past the 0.1 s timeout
        def __init__(self):
            self.sent = []

        async def command(self, c):
            self.sent.append(c)
            script = pathlib.Path(c.split("ScriptPath=", 1)[1])
            out, done = (script.with_suffix(x) for x in (".json", ".done"))
            asyncio.get_running_loop().call_later(0.5, lambda: (out.write_text('{"ok": true, "result": 42}'), done.write_text("1")))

    async def main():
        global RUN_DIR, _wait_finished
        RUN_DIR = pathlib.Path(tempfile.mkdtemp())

        async def finished(*a):
            return None
        _wait_finished = finished
        rc = SlowDorico()
        assert await Bridge(rc).run("tx", timeout=0.1) == 42
        assert len(rc.sent) == 1 and not list(RUN_DIR.iterdir()), (rc.sent, list(RUN_DIR.iterdir()))
    asyncio.run(main())
    print("bridge self-check ok: a slow script is waited for, nothing else is sent meanwhile")
