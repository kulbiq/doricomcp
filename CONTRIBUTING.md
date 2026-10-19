# Contributing

Thanks for helping.
The project talks to a live Dorico, so the rules below keep the score of whoever runs it safe.

## Ground rules

- Use only Dorico's own interfaces: Remote Control (WebSocket) and the Lua scripting model run through `Script.RunScript`.
  No reading or patching the Dorico process, no editing `.dorico` files.
- Every write is one Lua transaction (one undo step), read back and verified; a failed check undoes it.
  New write tools go through `Session.transact` with a `verify` function.
- Never run the confirmation harness on a real score: it closes the open project without saving.
- A Dorico behaviour you rely on must be measured, not assumed; add it to "Measured Dorico behaviour" in the README.

## Layout and dependencies

Each module states what it depends on in its docstring.
A module imports only modules above it in this list:

1. `model` (events, dump parsing, bar map), `catalog` (data in `doricomcp/data/`, command validation), `logtail` (change log), `rc` (Remote Control client)
2. `analysis` (voice leading, pure Python), `windows` (screenshots, dialogs)
3. `bridge` (Lua transactions; `lua/lib.lua` is the Lua side), `probe` (sealed-value readers)
4. `session` (one live session: twin, caches, verified transactions, undo accounting)
5. `reads` (composer views), then `ops/common`, `ops/dynamics`, `ops/markings`, `ops/notes` (write operations)
6. `server` (the MCP tools)
7. `fixture`, `confirm` (throwaway fixture and live harness)

`tests/offline.py` checks this order (`ORDER`), so an import against it fails CI.

## Adding a tool

1. Put the operation in the matching `doricomcp/ops/` module (or `reads.py` for a read).
2. Expose it in `server.py` with `@mcp.tool()` and `@capability("<name>")`; the first sentence of the docstring is what the README table shows.
3. Add a live test to `doricomcp/confirm.py` (`TESTS`) that writes on the fixture and reads the result back.
4. Run the checks below, then `uv run python scripts/readme_table.py` to refresh the README table.

## Checks

```sh
uvx ruff check                    # lint
uv run python tests/offline.py   # self-checks and layer check, no Dorico needed
uv run python -m doricomcp.confirm   # live harness: needs Dorico with no real project open
```

`uv run python -m doricomcp.confirm <name>` runs only the tests whose name contains `<name>`.
The harness needs the Xcode Command Line Tools: before it touches Dorico it checks the open windows with a small Swift helper, so it never closes a real project.
The harness opens `fixtures/throwaway.dorico` (restored from `throwaway.pristine.dorico`), writes `doricomcp/data/confirmed.json` and closes the fixture without saving.

## Style

- Comments say why, not what; keep them short.
- Never use an em dash in docs or messages.
- Long Markdown: one sentence per line.
