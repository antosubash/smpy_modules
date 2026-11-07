"""The TypeScript half of ``moved_paths.py``: a re-export stub at every old path (#319).

A host resolves ``@simple-module-py/<module>/…`` to the installed package
directory, so an old import keeps working when a file at the old path
re-exports the new one. Each stub re-exports everything of the file the old one
became (``export *``, plus ``default``), and names by name the exports the old
file had that ended up elsewhere. ``moved_paths_exports.mjs`` reads the export
surfaces with the TypeScript checker.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path, PurePosixPath

from moved_paths_common import REMOVE_IN, SKIP, Move, Package, guess

EXPORTS_JS = Path(__file__).with_name("moved_paths_exports.mjs")
MARKER = "/** @deprecated Moved to "
CSS_MARKER = "/* @deprecated Moved to "
TS_SUFFIXES = (".ts", ".tsx")
STUB_SUFFIXES = (*TS_SUFFIXES, ".css")
LINE_WIDTH = 100


def is_stub(path: Path) -> bool:
    """Whether ``path`` is a TS or CSS file ``--generate`` wrote."""
    return path.suffix in STUB_SUFFIXES and path.read_text(encoding="utf-8").startswith(
        (MARKER, CSS_MARKER)
    )


def sources(root: Path, pkg: Package) -> list[str]:
    """The package's own TS files (not tests, not stubs), relative to the package dir."""
    base = root / pkg.rel
    found = []
    for path in sorted(base.rglob("*")):
        rel = path.relative_to(base).as_posix()
        if path.suffix in TS_SUFFIXES and not SKIP.search(rel) and not is_stub(path):
            found.append(rel)
    return found


def surfaces(root: Path, wanted: dict[Package, list[str]]) -> dict[Package, dict[str, dict]]:
    """``{pkg: {rel: {"default": bool, "exports": {name: {"kind", "decl"}}}}}``, decl relative."""
    projects = [
        {
            "tsconfig": str(root / "modules" / p.module / "tsconfig.json"),
            "files": [str(root / p.rel / f) for f in files],
        }
        for p, files in wanted.items()
        if files
    ]
    run = subprocess.run(
        ["node", str(EXPORTS_JS)],
        input=json.dumps({"projects": projects}),
        capture_output=True,
        text=True,
        check=True,
        cwd=root,
    )
    raw = json.loads(run.stdout)
    out: dict[Package, dict[str, dict]] = {}
    for pkg, files in wanted.items():
        base = str(root / pkg.rel) + os.sep
        out[pkg] = {}
        for rel in files:
            surf = raw.get(str(root / pkg.rel / rel)) or {"default": False, "exports": {}}
            for entry in surf["exports"].values():
                decl = entry["decl"]
                entry["decl"] = decl[len(base) :] if decl and decl.startswith(base) else None
            out[pkg][rel] = surf
    return out


def _stem(rel: str) -> str:
    return PurePosixPath(rel).stem


def _home(name: str, old: str, primary: str | None, new: dict[str, dict]) -> str | None:
    homes = [rel for rel, surf in new.items() if name in surf["exports"]]
    if not homes:
        return None
    near = str(PurePosixPath(primary).parent) if primary else ""

    def rank(rel: str) -> tuple:
        here = new[rel]["exports"][name]["decl"] == rel
        return (
            not here,
            _stem(rel) != _stem(old),
            str(PurePosixPath(rel).parent) != near,
            len(rel),
            rel,
        )

    return min(homes, key=rank)


def plan(pkg: Package, moves: list[Move], dirs: dict, old: dict[str, dict], new: dict[str, dict]):
    """``(ts, css, removed)``: the stub specs, the CSS stubs and the names lost."""
    ts: dict[str, dict] = {}
    css: dict[str, str] = {}
    removed: dict[str, list[str]] = {}
    for move in (m for m in moves if m.package == pkg):
        candidates = [p for p in dict.fromkeys([move.new, guess(move, dirs)]) if p]
        if move.old.endswith(".css"):
            existing = [c for c in candidates if c.endswith(".css")]
            if existing:
                css[move.old] = existing[0]
            continue
        if not move.old.endswith(TS_SUFFIXES):
            continue
        stems = [str(PurePosixPath(c).with_suffix("")) for c in candidates]
        candidates = [
            f"{s}{x}" for s in dict.fromkeys(stems) for x in TS_SUFFIXES if f"{s}{x}" in new
        ]
        was = old[move.old]
        wanted = sorted(was["exports"])

        def score(rel: str, was=was, wanted=wanted) -> int:
            hits = sum(n in new[rel]["exports"] for n in wanted)
            return hits + (was["default"] and new[rel]["default"])

        primary = max(candidates, key=score) if candidates else None  # max keeps git's on a tie
        spec: dict = {"star": primary, "default": None, "values": {}, "types": {}}
        lost = []
        for name in wanted:
            if primary and name in new[primary]["exports"]:
                continue
            home = _home(name, move.old, primary, new)
            if home is None:
                lost.append(name)
                continue
            kinds = (was["exports"][name]["kind"], new[home]["exports"][name]["kind"])
            kind = "types" if "type" in kinds else "values"
            spec[kind].setdefault(home, []).append(name)
        if primary and new[primary]["default"]:
            spec["default"] = primary
        elif was["default"]:
            same = [r for r in new if new[r]["default"] and _stem(r) == _stem(move.old)]
            spec["default"] = (
                min(same, key=lambda r: (r not in candidates, len(r))) if same else None
            )
            if spec["default"] is None:
                lost.append("default")
        if stub := {k: v for k, v in spec.items() if v}:  # nothing to re-export: no stub
            ts[move.old] = stub
        if lost:
            removed[move.old] = lost
    return ts, css, removed


def _specifier(old: str, target: str) -> str:
    rel = os.path.relpath(target, str(PurePosixPath(old).parent)).replace(os.sep, "/")
    rel = rel.removesuffix(".tsx").removesuffix(".ts")
    return rel if rel.startswith(".") else f"./{rel}"


def _header(marker: str, to: str) -> str:
    return f"{marker}`{to}` in 0.0.14; this path goes in {REMOVE_IN} (#319). */"


def _export(keyword: str, names: list[str], spec: str) -> str:
    line = f"{keyword} {{ {', '.join(names)} }} from '{spec}';"
    if len(line) <= LINE_WIDTH:
        return line
    body = "".join(f"  {n},\n" for n in names)
    return f"{keyword} {{\n{body}}} from '{spec}';"


def render(old: str, spec: dict) -> str:
    """The stub's text; ``--check`` compares the file on disk with it."""
    to = (
        spec.get("star")
        or spec.get("default")
        or next(iter({**spec.get("values", {}), **spec.get("types", {})}))
    )
    lines = [_header(MARKER, to)]
    if spec.get("star"):
        lines.append(f"export * from '{_specifier(old, spec['star'])}';")
    if spec.get("default"):
        lines.append(f"export {{ default }} from '{_specifier(old, spec['default'])}';")
    for keyword, group in (("export", "values"), ("export type", "types")):
        for target, names in sorted(spec.get(group, {}).items()):
            lines.append(_export(keyword, sorted(names), _specifier(old, target)))
    return "\n".join(lines) + "\n"


def render_css(old: str, target: str) -> str:
    return f'{_header(CSS_MARKER, target)}\n@import "{_specifier(old, target)}";\n'
