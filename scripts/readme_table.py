"""Regenerate the README tool table from the MCP tools and the live confirmation matrix.

    uv run python scripts/readme_table.py          # rewrite README.md between the tools markers
    uv run python scripts/readme_table.py --check  # fail if README.md is out of date (CI)
"""
import asyncio
import pathlib
import re
import sys

from doricomcp import catalog
from doricomcp.server import mcp

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
START, END = "<!-- tools:start -->", "<!-- tools:end -->"
STATUS = {"confirmed": "confirmed live", "read-only": "read-only", "failed": "failing", None: "experimental"}


def first_sentence(doc: str) -> str:
    text = re.sub(r"\s*\[[A-Z-]+:[^]]*\]", "", " ".join(doc.split()))  # the status note; it has its own column
    text = re.split(r"(?<!e\.g)(?<!i\.e)(?<!incl)(?<!etc)\.\s+", text)[0].rstrip(".")
    if len(text) > 140:
        text = text[:140].rsplit(" ", 1)[0].rstrip(",;:(") + " ..."
    return text.replace("|", "\\|") + ("" if text.endswith("...") else ".")


def table() -> str:
    src = (ROOT / "doricomcp" / "server.py").read_text()
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    confirmed = catalog.confirmed()
    out, section = [], None
    for m in re.finditer(r'^# =+ (.+)$|^@capability\("(\w+)".*\n(?:@.*\n)*async def (\w+)', src, re.M):
        if m.group(1):
            section = m.group(1)
            if section == "resources":
                break
            out += ["", f"**{section[0].upper()}{section[1:]}**", "", "| Tool | What it does | Status |", "|---|---|---|"]
        elif m.group(3) in tools:
            status = STATUS.get(confirmed.get(m.group(2), {}).get("status"))
            out.append(f"| `{m.group(3)}` | {first_sentence(tools[m.group(3)].description or '')} | {status} |")
    return "\n".join(out).strip()


def main():
    text = README.read_text()
    a, b = text.index(START) + len(START), text.index(END)
    new = text[:a] + "\n" + table() + "\n" + text[b:]
    if "--check" in sys.argv:
        if new != text:
            sys.exit("README tool table is out of date: run uv run python scripts/readme_table.py")
        return
    README.write_text(new)


if __name__ == "__main__":
    main()
