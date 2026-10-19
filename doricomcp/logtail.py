"""Change detection from Dorico's application.log (there is no score-content-changed push).

Every executed command is logged as `notifyPostCommandExecute: <command>`. Anything that is not
known read-only (navigation, selection, view, our own read scripts) counts as a possible score change.

Depends on: nothing else in the package.
"""
import os
import pathlib
import re

LOG = pathlib.Path(os.environ.get("DORICOMCP_LOG", pathlib.Path.home() / "Library/Application Support/Steinberg/Dorico 6/application.log"))
EXEC = re.compile(r"notifyPostCommandExecute: (\S+)")
READ_ONLY = ("EventEdit.Select", "Edit.Select", "Edit.GoTo", "Window.", "View.", "Play.", "File.AutoSave",
             "EventEdit.Navigate", "UI.", "Edit.Copy", "Script.RunScript")


class LogTail:
    def __init__(self):
        self.offset = self._size()

    @staticmethod
    def _size() -> int:
        try:
            return LOG.stat().st_size
        except FileNotFoundError:
            return 0

    def skip(self):
        """Forget everything logged so far (after our own probes/writes)."""
        self.offset = self._size()

    def changes(self) -> list[str]:
        """Commands logged since the last call that may have changed the score."""
        size = self._size()
        if size < self.offset:  # log rotated (Dorico restarted)
            self.offset = 0
        if size == self.offset:
            return []
        with open(LOG, "rb") as f:
            f.seek(self.offset)
            text = f.read(size - self.offset).decode("utf-8", "replace")
        self.offset = size
        cmds = [m.group(1) for m in EXEC.finditer(text)]
        # Script.RunScript is read-only only when it is ours and read-only; writes call skip() themselves.
        # A RunScript from elsewhere (a user script) is treated as a change.
        return [c for c in cmds if not c.startswith(READ_ONLY) or (c.startswith("Script.RunScript") and "/.doricomcp/run/" not in c)]
