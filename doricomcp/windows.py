"""Dorico's on-screen windows (CoreGraphics window list via a small compiled Swift helper):
screenshots of the score window, and detection of modal dialogs that block Dorico.
Dialogs are read and answered through macOS Accessibility (Dorico's Qt widgets are exposed there); that needs
Accessibility permission for the app running the server, and only ever touches windows other than project windows.

Depends on: rc.
"""
import hashlib
import json
import pathlib
import subprocess
import tempfile
from typing import Any

from .rc import HOME

SRC = r'''
import CoreGraphics
import Foundation
let list = CGWindowListCopyWindowInfo([.optionAll], kCGNullWindowID) as? [[String: Any]] ?? []
var out: [[String: Any]] = []
for w in list where (w[kCGWindowOwnerName as String] as? String) == "Dorico" && (w[kCGWindowLayer as String] as? Int) == 0 {
  let r = w[kCGWindowBounds as String] as? [String: Double] ?? [:]
  out.append(["id": w[kCGWindowNumber as String] as? Int ?? 0, "w": Int(r["Width"] ?? 0), "h": Int(r["Height"] ?? 0),
              "name": w[kCGWindowName as String] as? String ?? "", "onscreen": (w[kCGWindowIsOnscreen as String] as? Bool) ?? false])
}
print(String(data: try! JSONSerialization.data(withJSONObject: out), encoding: .utf8)!)
'''
AX_SRC = r'''
import ApplicationServices
import AppKit
import Foundation

func attr(_ e: AXUIElement, _ a: String) -> AnyObject? {
  var v: AnyObject?
  return AXUIElementCopyAttributeValue(e, a as CFString, &v) == .success ? v : nil
}
func str(_ e: AXUIElement, _ a: String) -> String? { attr(e, a) as? String }
func kids(_ e: AXUIElement) -> [AXUIElement] { (attr(e, kAXChildrenAttribute) as? [AXUIElement]) ?? [] }
func value(_ e: AXUIElement) -> String? {
  let v = attr(e, kAXValueAttribute)
  if let n = v as? NSNumber { return n.stringValue }
  return v as? String
}
func out(_ v: Any) { print(String(data: try! JSONSerialization.data(withJSONObject: v), encoding: .utf8)!) }
func fail(_ m: String) -> Never { out(["error": m]); exit(1) }

let CONTROLS: Set<String> = ["AXButton", "AXCheckBox", "AXRadioButton", "AXTextField", "AXTextArea", "AXPopUpButton",
                             "AXComboBox", "AXSlider", "AXIncrementor", "AXMenuButton", "AXDisclosureTriangle"]
guard AXIsProcessTrusted() else {
  fail("no Accessibility permission: allow the app that runs this server (Claude, or the terminal for Claude Code) in " +
       "System Settings > Privacy & Security > Accessibility, then quit and reopen it")
}
guard let app = NSWorkspace.shared.runningApplications.first(where: { $0.localizedName == "Dorico" }) else { fail("Dorico is not running") }
let axApp = AXUIElementCreateApplication(app.processIdentifier)
let wins = (attr(axApp, kAXWindowsAttribute) as? [AXUIElement]) ?? []

func isProject(_ w: AXUIElement) -> Bool {
  (str(w, kAXSubroleAttribute) == "AXStandardWindow") && !((attr(w, kAXModalAttribute) as? Bool) ?? false)
    && (str(w, kAXTitleAttribute) ?? "").contains(" in ")
}

func describe(_ i: Int, _ w: AXUIElement) -> [String: Any] {
  var controls: [[String: Any]] = [], texts: [String] = [], label: String? = nil, count = 0
  func walk(_ e: AXUIElement, _ path: [Int]) {
    count += 1
    if count > 600 || path.count > 16 { return }
    let role = str(e, kAXRoleAttribute) ?? ""
    if role == "AXStaticText", let t = value(e) ?? str(e, kAXTitleAttribute), !t.isEmpty { texts.append(t); label = t }
    if CONTROLS.contains(role) {
      let title = str(e, kAXTitleAttribute).flatMap { $0.isEmpty ? nil : $0 } ?? str(e, kAXDescriptionAttribute).flatMap { $0.isEmpty ? nil : $0 }
      var c: [String: Any] = ["path": path.map(String.init).joined(separator: "."), "role": role,
                              "enabled": (attr(e, kAXEnabledAttribute) as? Bool) ?? true]
      if let t = title { c["title"] = t } else if let l = label { c["label"] = l }
      if let v = value(e) { c["value"] = v }
      controls.append(c)
    }
    for (k, c) in kids(e).enumerated() { walk(c, path + [k]) }
  }
  walk(w, [])
  return ["window": i, "title": str(w, kAXTitleAttribute) ?? "", "subrole": str(w, kAXSubroleAttribute) ?? "",
          "modal": (attr(w, kAXModalAttribute) as? Bool) ?? false, "texts": texts, "controls": controls]
}

func element(_ win: Int, _ path: String) -> AXUIElement {
  guard win >= 0 && win < wins.count, !isProject(wins[win]) else { fail("window \(win) is not an open dialog") }
  var e = wins[win]
  for p in path.split(separator: ".").compactMap({ Int($0) }) {
    let k = kids(e)
    guard p < k.count else { fail("control \(path) is gone (the dialog changed); list the dialogs again") }
    e = k[p]
  }
  return e
}

func find(_ root: AXUIElement, role: String, title: String, depth: Int = 0) -> AXUIElement? {
  if depth > 8 { return nil }
  if str(root, kAXRoleAttribute) == role && (str(root, kAXTitleAttribute) ?? "").lowercased() == title.lowercased() { return root }
  for c in kids(root) { if let f = find(c, role: role, title: title, depth: depth + 1) { return f } }
  return nil
}

let args = CommandLine.arguments
switch args.count > 1 ? args[1] : "list" {
case "list":
  out(wins.enumerated().filter { !isProject($0.element) }.map { describe($0.offset, $0.element) })
case "press":
  let e = element(Int(args[2]) ?? -1, args[3])
  let r = AXUIElementPerformAction(e, kAXPressAction as CFString)
  out(["ok": r == .success, "code": r.rawValue])
case "set":
  let e = element(Int(args[2]) ?? -1, args[3]), want = args[4]
  switch str(e, kAXRoleAttribute) ?? "" {
  case "AXCheckBox", "AXRadioButton":
    let on = ["true", "1", "on", "yes"].contains(want.lowercased())
    if (value(e) == "1") != on { _ = AXUIElementPerformAction(e, kAXPressAction as CFString) }
  case "AXPopUpButton", "AXComboBox", "AXMenuButton":
    _ = AXUIElementPerformAction(e, kAXPressAction as CFString)
    Thread.sleep(forTimeInterval: 0.4)
    guard let item = find(e, role: "AXMenuItem", title: want) ?? find(axApp, role: "AXMenuItem", title: want) else {
      _ = AXUIElementPerformAction(e, kAXCancelAction as CFString)
      fail("no item \(want) in that list")
    }
    _ = AXUIElementPerformAction(item, kAXPressAction as CFString)
  default:
    _ = AXUIElementSetAttributeValue(e, kAXFocusedAttribute as CFString, kCFBooleanTrue)
    let r = AXUIElementSetAttributeValue(e, kAXValueAttribute as CFString, want as CFTypeRef)
    guard r == .success else { fail("the control refused the value (code \(r.rawValue))") }
    _ = AXUIElementPerformAction(e, kAXConfirmAction as CFString)
  }
  out(["ok": true])
default:
  fail("usage: list | press <window> <path> | set <window> <path> <value>")
}
'''


def _compiled(name: str, src: str) -> pathlib.Path:
    """The helper binary for this exact source (rebuilt when the source changes)."""
    b = HOME / "bin" / f"{name}-{hashlib.sha256(src.encode()).hexdigest()[:10]}"
    if not b.exists():
        b.parent.mkdir(parents=True, exist_ok=True)
        swift = b.with_suffix(".swift")
        swift.write_text(src)
        subprocess.run(["swiftc", "-O", "-o", str(b), str(swift)], check=True, capture_output=True)
    return b


def windows() -> list[dict]:
    return json.loads(subprocess.run([str(_compiled("dorico-windows", SRC))], capture_output=True, text=True, check=True).stdout or "[]")


def _ax(*args) -> Any:
    r = subprocess.run([str(_compiled("dorico-ax", AX_SRC)), *map(str, args)], capture_output=True, text=True, timeout=20, check=False)
    data = json.loads(r.stdout or "null")
    if isinstance(data, dict) and "error" in data:
        raise RuntimeError(data["error"])
    return data


def ax_dialogs() -> list[dict]:
    """Every Dorico window that is not a project window: title, modal, its texts and controls (with paths)."""
    return _ax("list")


def _norm(t: str | None) -> str:
    return (t or "").strip().rstrip(":").replace("\u2026", "...").lower()


def find_control(dialogs: list[dict], control: str, dialog: str | None = None) -> tuple[dict, dict]:
    """(dialog, control) by control title, preceding label, or path; the dialog by title when several are open."""
    if dialog is None:  # only real dialogs unless a window is named: never click into Steinberg Hub by accident
        ds = [d for d in dialogs if d["modal"] or d["subrole"] == "AXDialog"]
    else:
        ds = [d for d in dialogs if _norm(d["title"]) == _norm(dialog)]
    if not ds:
        others = [d["title"] for d in dialogs]
        raise ValueError(f"no open dialog {dialog!r}; windows: {others}" if dialog else
                         f"no dialog is open{f' (other windows: {others}; name one with dialog=)' if others else ''}")
    if len(ds) > 1:
        ds = [d for d in ds if d["modal"]] or ds
    if len(ds) > 1:
        raise ValueError(f"several dialogs are open ({[d['title'] for d in ds]}); name one with dialog=")
    d = ds[0]
    hits = [c for c in d["controls"] if c["path"] == control] or \
           [c for c in d["controls"] if _norm(c.get("title")) == _norm(control)] or \
           [c for c in d["controls"] if _norm(c.get("label")) == _norm(control)]
    if len(hits) > 1:
        hits = [c for c in hits if c["enabled"]] or hits
    if not hits:
        names = [c.get("title") or c.get("label") or c["path"] for c in d["controls"]]
        raise ValueError(f"no control {control!r} in dialog {d['title']!r}; controls: {names}")
    if len(hits) > 1:
        raise ValueError(f"{len(hits)} controls match {control!r}; use a path: {[c['path'] for c in hits]}")
    return d, hits[0]


def dialog_press(control: str, dialog: str | None = None) -> dict:
    d, c = find_control(ax_dialogs(), control, dialog)
    if not c["enabled"]:
        raise ValueError(f"{c.get('title') or c['path']} is disabled")
    _ax("press", d["window"], c["path"])
    return {"pressed": c, "dialog": d["title"]}


def dialog_set_value(control: str, value: str, dialog: str | None = None) -> dict:
    d, c = find_control(ax_dialogs(), control, dialog)
    _ax("set", d["window"], c["path"], value)
    return {"set": c, "dialog": d["title"]}


def score_windows() -> list[dict]:
    """Project windows ("<flow> in <project>"), on-screen first. Other large windows (Steinberg Hub, Preferences...)
    only when no window title is readable at all, i.e. without Screen Recording permission."""
    big = [w for w in windows() if w["w"] * w["h"] > 250000]
    projects = [w for w in big if " in " in w["name"]]
    pool = projects or ([] if any(w["name"] for w in big) else big)
    return sorted(pool, key=lambda w: (not w["onscreen"], -w["w"] * w["h"]))


def dialogs() -> list[dict]:
    """On-screen Dorico windows that look like modal dialogs/popups (not the score window or toolbars)."""
    return [w for w in windows() if w["onscreen"] and w["h"] > 40 and w["w"] * w["h"] < 600000 and " in " not in w["name"]]


def screenshot(max_px: int = 1600) -> bytes:
    ws = score_windows()
    for w in ws:
        with tempfile.NamedTemporaryFile(suffix=".png") as f:
            r = subprocess.run(["screencapture", "-x", "-o", "-l", str(w["id"]), f.name], capture_output=True, check=False)
            if r.returncode == 0 and pathlib.Path(f.name).stat().st_size > 0:
                subprocess.run(["sips", "-Z", str(max_px), f.name], capture_output=True, check=False)
                return pathlib.Path(f.name).read_bytes()
    if not ws:
        raise RuntimeError("no Dorico score window found: is Dorico running with a project open?")
    # window titles of other apps are hidden without Screen Recording permission, so that is the likely cause
    raise RuntimeError("Dorico's window could not be captured: the app that runs this server (Claude, or the terminal "
                       "for Claude Code) needs Screen Recording permission in System Settings > Privacy & Security > "
                       "Screen & System Audio Recording; quit and reopen it after granting"
                       + ("" if any(w["name"] for w in ws) else " (window titles are hidden too, which confirms it)"))


if __name__ == "__main__":
    print(json.dumps(score_windows()[:2]), json.dumps(dialogs()))
    assert screenshot()[:4] == b"\x89PNG"
    print("windows self-check ok")
