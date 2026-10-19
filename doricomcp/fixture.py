"""Throwaway-fixture lifecycle, all through Dorico's own interfaces.

Measured:
- `File.CloseProject?OpenScoreID=<status.activeOpenScoreID>&Save=false` closes a *modified* score with no save prompt; the file on
  disk is untouched. `File.Open?File=<path>` has it back in ~2 s. So `reset()` discards every edit,
  including undo/redo history, which is a stronger revert than inverse edits.
- When Dorico is not running: `open -a "Dorico 6" <file>` has the score ready in ~6 s; AppleScript quit
  terminates cleanly on an unmodified score (osascript prints a spurious "User cancelled (-128)").
fixtures/throwaway.pristine.dorico is never opened; it restores throwaway.dorico if that ever gets saved.

Depends on: rc, windows.
"""
import asyncio
import pathlib
import shutil
import subprocess

from .rc import RCError, RemoteControl

ROOT = pathlib.Path(__file__).resolve().parent.parent / "fixtures"
FIXTURE, PRISTINE = ROOT / "throwaway.dorico", ROOT / "throwaway.pristine.dorico"
APP = "Dorico 6"


def running() -> bool:
    return subprocess.run(["pgrep", "-x", APP], capture_output=True, check=False).returncode == 0


async def _run(*cmd: str, check: bool = False) -> str:
    p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await p.communicate()
    if check and p.returncode:
        raise RuntimeError(f"{cmd[0]} failed: {err.decode().strip()}")
    return out.decode()


async def _wait_score(rc: RemoteControl, want: bool, timeout: float):
    for _ in range(int(timeout * 4)):
        try:
            if bool((await rc.status()).get("hasScore")) == want:
                return
        except (OSError, RCError, TimeoutError):  # port not up yet while Dorico launches
            await rc.close()
            rc.ws = None
        await asyncio.sleep(0.25)
    raise RuntimeError(f"hasScore did not become {want} within {timeout}s")


async def launch(path: pathlib.Path = FIXTURE, timeout: float = 120):
    await _run("open", "-a", APP, str(path), check=True)
    rc = RemoteControl()
    try:
        await _wait_score(rc, True, timeout)
    finally:
        await rc.close()


async def quit_dorico(timeout: float = 30):
    await _run("osascript", "-e", f'tell application "{APP}" to quit')
    for _ in range(int(timeout * 4)):
        if not running():
            return
        await asyncio.sleep(0.25)
    raise RuntimeError(f"{APP} still running after {timeout}s (save prompt or dialog open?)")


async def force_restart(path: pathlib.Path = FIXTURE):
    """Dorico hung or crashed: kill its exact PID(s) (never a pattern kill) and relaunch on `path`."""
    ensure_fixture_active()
    pids = (await _run("pgrep", "-x", APP)).split()
    for pid in pids:
        await _run("kill", "-9", pid)
    for _ in range(40):
        if not running():
            break
        await asyncio.sleep(0.25)
    if path == FIXTURE:
        _restore_file()
    await launch(path, timeout=60)


def ensure_fixture_active(no_score: bool = False):
    """Refuse to touch Dorico unless the open score is the throwaway fixture, or Dorico is not running, or it has
    no score open at all (no_score, from Remote Control status): reset() closes the project without saving,
    force_restart() kills Dorico."""
    if not running():
        return
    from .windows import windows
    # fail-safe: every titled score window ("<flow> in <project>", on-screen or not, stale ones included)
    # must belong to the fixture; the window list can lag, so any other project blocks
    names = sorted({w["name"] for w in windows() if " in " in w["name"]})
    if no_score and not names:
        return
    if not names or not all(n.endswith(f" in {FIXTURE.stem}") for n in names):
        raise RuntimeError(f"refusing: the open score is {names or 'unknown'}, not the {FIXTURE.stem} fixture; "
                           "close real projects first (this would discard unsaved work)")


def _restore_file():
    if not FIXTURE.exists() or FIXTURE.read_bytes() != PRISTINE.read_bytes():
        shutil.copyfile(PRISTINE, FIXTURE)


async def reset(rc: RemoteControl | None = None):
    """Discard everything done to the fixture since it was opened and reopen it."""
    if not running():
        ensure_fixture_active()
        _restore_file()
        return await launch()
    own = rc is None
    rc = rc or RemoteControl()
    try:
        st = await rc.status()
        ensure_fixture_active(no_score=not st.get("hasScore"))
        old = st.get("activeOpenScoreID")
        if st.get("hasScore"):
            # the id grows with every open; a stale id makes CloseProject a silent kOK no-op
            await rc.command(f"File.CloseProject?OpenScoreID={old}&Save=false")
            await _wait_score(rc, False, 30)
        _restore_file()  # only while closed: overwriting an open score triggers File.WasModifiedOnDisk
        await rc.command(f"File.Open?File={FIXTURE}")
        await _wait_score(rc, True, 60)
        new = (await rc.status()).get("activeOpenScoreID")
        if new == old:
            raise RuntimeError(f"fixture was not reopened (OpenScoreID still {old})")
    finally:
        if own:
            await rc.close()


if __name__ == "__main__":
    asyncio.run(reset())
