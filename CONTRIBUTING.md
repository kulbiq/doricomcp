# Contributing

Thanks for helping.
The project talks to a live Dorico, so the rules below keep the score of whoever runs it safe.

## Ground rules

- Use only Dorico's own interfaces: Remote Control (WebSocket) and the Lua scripting model run through `Script.RunScript`.
  No reading or patching the Dorico process, no editing `.dorico` files.
- Every write is one Lua transaction (one undo step), read back and verified; a failed check undoes it.
  New write tools go through `Session.transact` with a `verify` function.
- Never run the confirmation harness on a real score: it closes the open project without saving.
- A Dorico behaviour you rely on must be measured, not assumed; add it to [docs/dorico-behaviour.md](docs/dorico-behaviour.md).
  Measure it against a control (a baseline where the effect is absent) and check the effect itself (a quarter-tone sticks to a note), not only the event that should cause it.

## Running from a clone

```sh
git clone https://github.com/mka142/doricomcp && cd doricomcp && uv sync
git config core.hooksPath .githooks   # runs lint and the offline checks before each commit
```

Claude Code picks up the bundled `.mcp.json` when started in the clone.
For Claude Desktop, use `"command": "uv", "args": ["run", "--directory", "/path/to/doricomcp", "doricomcp"]` (with the full path to `uv`).
`lua/lib.lua` is read fresh on every call, so Lua changes need no restart; Python changes need the server restarted.

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

```
server.py          MCP tools (the only module the client sees)
  reads.py         composer views: music per voice (full, compact, grid), markings, context at a point
  ops/             write operations: common -> dynamics -> markings, common -> notes
  analysis.py      voice-leading check (pure Python on read_music data)
    session.py     one live session: twin assembly, caches, verified transactions, undo accounting
      probe.py     sealed-value readers (time signatures, dynamic levels, keys), cached
      bridge.py    Lua transaction bridge; lua/lib.lua is the Lua side (read fresh on every call)
      windows.py   screenshots and dialog detection (macOS)
        rc.py      Remote Control WebSocket client
        logtail.py change detection from Dorico's application.log
        catalog.py command, enum, property and library data (doricomcp/data/), command validation
        model.py   typed events, dump parsing, bar map, key and staff logic
fixture.py, confirm.py   throwaway-fixture lifecycle and the live harness (never on a real score)
```

`doricomcp/data/` holds Dorico's command list and property schemas (from Remote Control), enum and property names, and the confirmation matrix.
The first ones are generated from a live Dorico by tooling outside this repo: record a measured extra in `catalog.py`, not in the JSON.
`confirmed.json` is written by the harness, which then regenerates the README tool table from it.

## Adding a tool

1. Put the operation in the matching `doricomcp/ops/` module (or `reads.py` for a read).
2. Expose it in `server.py` with `@mcp.tool()` and `@capability("<name>")`; the first sentence of the docstring is what the README table shows.
3. Add a live test to `doricomcp/confirm.py` (`TESTS`) that writes on the fixture and reads the result back.
   A test sets up everything it reads, so `confirm <name>` passes alone; `confirm --each` checks that for every test.
4. Run the checks below; the harness refreshes the README tool table.

## Checks

```sh
uvx ruff check                    # lint
uvx pyright@1.1.414               # types (the checker behind VS Code's Pylance)
uv run python tests/offline.py   # self-checks and layer check, no Dorico needed
uv run python -m doricomcp.confirm   # live harness: needs Dorico with no real project open
```

`uv run python -m doricomcp.confirm <name>` runs only the tests whose name contains `<name>`; `--each` resets the fixture before every test (slow; run it before a release).
The harness needs the Xcode Command Line Tools: before it touches Dorico it checks the open windows with a small Swift helper, so it never closes a real project.
The harness opens `fixtures/throwaway.dorico` (restored from `throwaway.pristine.dorico`), writes `doricomcp/data/confirmed.json` and closes the fixture without saving.

## Releasing

1. Set the same version in `pyproject.toml`, `manifest.json` and `server.json` (both places); `tests/offline.py` checks they agree.
2. Push a tag `vX.Y.Z`.
   `.github/workflows/release.yml` then publishes to PyPI, attaches `doricomcp.mcpb` (the Claude Desktop extension) to a GitHub release, and updates the MCP registry entry.

`scripts/build_mcpb.sh` builds the extension locally into `dist/`.
PyPI's JSON and `uvx doricomcp@X.Y.Z` see a new version only about half a minute after the workflow finishes.

## Style

- Comments say why, not what; keep them short.
- Never use an em dash in docs or messages.
- Long Markdown: one sentence per line.
