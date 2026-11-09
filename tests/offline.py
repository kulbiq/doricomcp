"""Everything that can be checked without Dorico: each module's self-check, the import layering, and that the
README tool table is current. Run: uv run python tests/offline.py"""
import ast
import json
import pathlib
import subprocess
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "doricomcp"
# a module may import only modules listed before it (CONTRIBUTING.md, "Layout and dependencies")
ORDER = ["model", "catalog", "logtail", "rc", "analysis", "windows", "bridge", "probe", "session", "reads",
         "ops.common", "ops.dynamics", "ops.markings", "ops.notes", "ops", "server", "fixture", "confirm"]
SELF_CHECKS = [["-m", "doricomcp.model"], ["-m", "doricomcp.rc"], ["-m", "doricomcp.analysis"], ["-m", "doricomcp.ops"],
               ["-m", "doricomcp.server", "selfcheck"], ["scripts/readme_table.py", "--check"]]


def module_name(path: pathlib.Path) -> str:
    rel = path.relative_to(PKG).with_suffix("")
    parts = [p for p in rel.parts if p not in ("__init__", "__main__")]
    return ".".join(parts)


def imports(path: pathlib.Path) -> set[str]:
    """Package-internal modules imported by a file (relative imports, resolved to dotted names)."""
    here = module_name(path).split(".")
    pkg = here if path.stem in ("__init__", "__main__") else here[:-1]
    out = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.level:
            base = pkg[:len(pkg) - (node.level - 1)] if node.level > 1 else pkg
            target = ".".join([*base, *(node.module.split(".") if node.module else [])])
            names = [target] if node.module else [".".join([*base, a.name]) for a in node.names]
            out.update(n for n in names if n)
    return out


def check_layers() -> list[str]:
    errors = []
    for path in sorted(PKG.rglob("*.py")):
        me = module_name(path)
        if not me or path.name == "__main__.py":  # the empty package root; self-checks may use anything
            continue
        rank = ORDER.index(me) if me in ORDER else None
        if rank is None:
            errors.append(f"{me}: not in tests/offline.py ORDER")
            continue
        for dep in imports(path):
            if dep == me or dep.startswith(me + "."):  # a package importing its own submodules
                continue
            if dep not in ORDER or ORDER.index(dep) >= rank:
                errors.append(f"{me} imports {dep}, which is not below it")
    return errors


def check_versions() -> list[str]:
    """The PyPI package, the Claude Desktop bundle and the MCP registry entry must publish the same version."""
    want = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    server = json.loads((ROOT / "server.json").read_text())
    found = {"manifest.json": json.loads((ROOT / "manifest.json").read_text())["version"], "server.json": server["version"],
             "server.json packages": server["packages"][0]["version"]}
    errors = [f"{k} has version {v}, pyproject.toml has {want}" for k, v in found.items() if v != want]
    if f"mcp-name: {server['name']}" not in (ROOT / "README.md").read_text():
        errors.append(f"README.md lacks 'mcp-name: {server['name']}' (the MCP registry checks it on PyPI)")
    return errors


def main():
    failed = check_layers() + check_versions()
    for e in failed:
        print("check:", e)
    for args in SELF_CHECKS:
        r = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True, check=False)
        print(("ok  " if r.returncode == 0 else "FAIL"), " ".join(args), (r.stdout + r.stderr).strip().splitlines()[-1:])
        if r.returncode:
            failed.append(" ".join(args))
            print(r.stdout + r.stderr)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
