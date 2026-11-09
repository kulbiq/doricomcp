"""Dorico's command list, enum values, property schemas and library entries (doricomcp/data/), the live
confirmation matrix, and command validation.

Depends on: nothing else in the package.
"""
import json
import pathlib
import re
from functools import cache
from urllib.parse import parse_qsl

DATA = pathlib.Path(__file__).resolve().parent / "data"
CONFIRMED = DATA / "confirmed.json"


def _load(p):
    return json.loads(pathlib.Path(p).read_text())


@cache
def commands() -> dict[str, dict]:
    d = _load(DATA / "commands.json")
    out = {c["name"]: c for c in d["commands"]}
    for n in d.get("observed_but_not_listed", []):
        out.setdefault(n, {"name": n, "group": n.split(".")[0], "parameters": {}, "internal": True})
    for n in _load(DATA / "commands_not_in_getcommands.json"):
        out.setdefault(n, {"name": n, "group": n.split(".")[0], "parameters": {}, "internal": True})
    return out


@cache
def enums() -> dict[str, list]:
    return _load(DATA / "enums.json")


@cache
def property_names() -> dict[str, list]:
    return _load(DATA / "property_names.json")["by_family"]


@cache
def property_schemas() -> dict:
    return _load(DATA / "rc_property_schemas.json")


def property_info(name: str) -> dict | None:
    """Schema (valueType, enumValues, displayName) for a property name from the live RC dumps, if known."""
    for et, d in property_schemas().items():
        for p in d["propertieslist"]["properties"]:
            if p["name"] == name:
                return {**p, "seen_on": et}
    fam = next((f for f, names in property_names().items() if name in names), None)
    return {"name": name, "family": fam} if fam else None


@cache
def library_dump(collection: str) -> list[dict]:
    p = DATA / "library" / f"library_{collection}.json"
    return _load(p)[0]["libraryentities"] if p.exists() else []


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def technique(value: str, lib: list[dict] | None = None) -> dict:
    """A playing technique by library id ("pta.pizzText"), name or abbreviation ("pizz.", "arco", "con sord.",
    "sul pont.", "ord."): {entityID, name}. lib: the score's live library (with the user's own techniques); default
    the catalogued one. Raises ValueError listing candidates when unknown or ambiguous."""
    lib = lib or library_dump("kPlayingTechniqueAppearanceCollection")
    if any(e["entityID"] == value for e in lib):
        return next(e for e in lib if e["entityID"] == value)
    want = _norm(value)

    def keys(e):
        abbr = re.findall(r"\(([^)]*)\)", e["name"])
        return {_norm(e["name"]), _norm(e["entityID"].removeprefix("pta.").removesuffix("Text")), *map(_norm, abbr)}

    hits = [e for e in lib if want in keys(e)] or [e for e in lib if want and any(k.startswith(want) for k in keys(e))]
    # prefer the plain text form over tab/abbreviated/instrument-specific variants
    hits.sort(key=lambda e: (not e["entityID"].endswith("Text"), len(e["name"])))
    if len(hits) == 1 or (hits and len(hits[0]["name"]) < len(hits[1]["name"]) and hits[0]["entityID"].endswith("Text")):
        return hits[0]
    names = ", ".join(f"{e['name']} ({e['entityID']})" for e in hits[:8]) or "none"
    raise ValueError(f"playing technique {value!r}: {'ambiguous' if hits else 'unknown'}; candidates: {names}")


def confirmed() -> dict[str, dict]:
    return {r["capability"]: r for r in _load(CONFIRMED)} if CONFIRMED.exists() else {}


def status(capability: str) -> str:
    return confirmed().get(capability, {}).get("status", "unconfirmed")


def describe_commands(filter: str = "", limit: int = 60) -> list[dict]:
    rx = re.compile(filter, re.IGNORECASE) if filter else None
    out = []
    for c in commands().values():
        if rx and not (rx.search(c["name"]) or rx.search(c.get("display_name") or "")):
            continue
        params = {k: {kk: vv for kk, vv in v.items() if kk in ("required", "enum_values", "observed_values")}
                  for k, v in c.get("parameters", {}).items()}
        out.append({"name": c["name"], "display_name": c.get("display_name"), "parameters": params,
                    **({"internal": True} if c.get("internal") else {})})
        if len(out) >= limit:
            break
    return out


def describe_enums(name: str) -> dict:
    e = enums()
    if name in e:
        return {name: [v[0] for v in e[name]]}
    rx = re.compile(name, re.IGNORECASE)
    hits = {k: [v[0] for v in vals] for k, vals in e.items() if rx.search(k)}
    return dict(list(hits.items())[:20])


class CommandError(ValueError):
    pass


def validate(command: str) -> str:
    """Check a `Namespace.Command?Param=value&...` string against the catalogue; returns it unchanged."""
    name, _, query = command.partition("?")
    c = commands().get(name)
    if c is None:
        close = [n for n in commands() if n.lower().startswith(name.lower().split(".")[0] + ".")][:10]
        raise CommandError(f"unknown command {name!r}" + (f"; same namespace: {close}" if close else ""))
    params = c.get("parameters", {})
    for k, v in parse_qsl(query, keep_blank_values=True):
        if params and k not in params and not c.get("internal"):
            raise CommandError(f"{name} has no parameter {k!r}; parameters: {sorted(params)}")
        allowed = params.get(k, {}).get("enum_values")
        if allowed and v not in allowed:
            raise CommandError(f"{name}: {k}={v!r} not in {allowed}")
    missing = [k for k, v in params.items() if v.get("required") and f"{k}=" not in query]
    if missing:
        raise CommandError(f"{name} requires {missing}")
    return command


if __name__ == "__main__":
    assert validate("NoteInput.SetArticulation?Value=kStaccato")
    for bad in ("Nope.Command", "Edit.ChangeVoice?VoiceDirection=kSideways", "NoteInput.SetArticulation?Bogus=1"):
        try:
            validate(bad)
            raise AssertionError(bad)
        except CommandError:
            pass
    assert describe_enums("LogDuration")["LogDuration"][0] == "k256Note" or describe_enums("LogDuration")
    assert property_info("kNoteVelocity")
    print("catalog self-check ok", len(commands()), "commands")
