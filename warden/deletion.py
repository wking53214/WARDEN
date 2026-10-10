"""The removal gate: code is commented out only after two opposite tests pass.

WHY

A suite that stays green does not prove deleted code was unused. On CNS,
three of four "unused" findings were pytest hooks that the framework calls by
name; deleting them would have passed the tests and silently dropped an
enforcement rule. Silent loss is the failure a deletion test cannot see.

THE TWO TESTS, in one cycle, both required

  keep test    "what happens if I don't delete it?" The code stays, but Warden
               temporarily makes it fail loudly (it raises when it runs). If
               the suite stays green, nothing runs it. If the suite goes red,
               something uses it, and the removal is refused. A hook that is
               called by name fails here instead of vanishing quietly.
  delete test  "what happens if I take it out?" The code is commented out, never
               deleted, each block stamped with the time and the Ghost finding.
               Applied under the usual gate: suite green before and after,
               Ghost finds nothing new, put back on any failure.

The keep test always restores the files, pass or fail. Without Ghost, the
suite, or a way to name and trap the code, nothing is touched.
"""

from __future__ import annotations

import ast
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from . import textio
from .guard import is_prose
from .models import Transformation, safe_id

_MESSAGE = "warden keep-test: this code is a deletion candidate and was still executed"


def _lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def is_deletion(target: Path, proposal: Transformation) -> bool:
    """True when any edit takes code away: a delete, or a code file that shrinks."""
    target = Path(target)
    for edit in proposal.edits:
        if edit.kind == "delete":
            return True
        if is_prose(edit.path):
            continue
        if edit.kind == "replace" and _lines(edit.old) > _lines(edit.new):
            return True
        if edit.kind == "write":
            path = target / edit.path
            if path.is_file() and _lines(textio.read_text(path)) > _lines(edit.new):
                return True
    return False


def _defs(tree: ast.AST) -> Dict[str, ast.AST]:
    return {n.name: n for n in getattr(tree, "body", [])
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}


def _boobytrap(text: str, only: Optional[set]) -> Optional[str]:
    """`text` with a raise as the first statement of each top-level def or class
    named in `only` (all of them when None). None when there is nothing to trap."""
    lines = text.splitlines()
    indent = next((l[:len(l) - len(l.lstrip())] for l in lines if l.strip()), "")
    body = textwrap.dedent(text)
    try:
        nodes = _defs(ast.parse(body))
    except SyntaxError:
        return None
    marks = []
    for name, node in nodes.items():
        if only is None or name in only:
            first = node.body[0]
            marks.append((first.lineno - 1, first.col_offset))
    if not marks:
        return None
    out = body.splitlines()
    for at, col in sorted(marks, reverse=True):
        out.insert(at, " " * col + f"raise RuntimeError({_MESSAGE!r})")
    return "\n".join((indent + l) if l.strip() else l for l in out) + ("\n" if text.endswith("\n") else "")


def removal_plan(target: Path, proposal: Transformation) -> Optional[Dict[str, Optional[set]]]:
    """Which top-level functions and classes a proposal takes away, per file.

    path -> set of names, or None meaning the whole file. Returns None when any
    removal is something Warden cannot name precisely (statements, data files,
    nested code); the gate then refuses rather than guess.
    """
    target = Path(target)
    plan: Dict[str, Optional[set]] = {}
    for edit in proposal.edits:
        path = target / edit.path
        if edit.kind == "delete":
            if not path.is_file() or path.suffix != ".py":
                return None
            plan[edit.path] = None
        elif is_prose(edit.path):
            continue
        elif edit.kind == "replace" and _lines(edit.old) > _lines(edit.new):
            if not path.is_file() or path.suffix != ".py":
                return None
            gone = _removed_names(edit.old, edit.new)
            if not gone:
                return None
            plan[edit.path] = gone
        elif edit.kind == "write" and path.is_file():
            original = textio.read_text(path)
            if _lines(original) > _lines(edit.new):
                gone = _removed_names(original, edit.new)
                if not gone or path.suffix != ".py":
                    return None
                plan[edit.path] = gone
    return plan or None


def keep_variant(target: Path, proposal: Transformation) -> Optional[Dict[str, str]]:
    """The files as they would be if the code were KEPT but made to fail loudly."""
    plan = removal_plan(target, proposal)
    if plan is None:
        return None
    out: Dict[str, str] = {}
    for rel, names in plan.items():
        original = textio.read_text(Path(target) / rel)
        trapped = _boobytrap(original, names)
        if trapped is None:
            if names is not None:
                return None
            trapped = f"raise RuntimeError({_MESSAGE!r})\n"
        out[rel] = trapped
    return out


def stamp_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def commented_variant(target: Path, proposal: Transformation, stamp: str) -> Optional[Dict[str, str]]:
    """The files with the removed code commented out, each block stamped.

    Nothing is deleted: the original lines stay in place behind "# ".
    """
    plan = removal_plan(target, proposal)
    if plan is None:
        return None
    ids = ", ".join(safe_id(d.ghost_id) for d in proposal.known_defects if d.ghost_id) or "no finding id"
    header = f"# WARDEN COMMENTED OUT {stamp} | {ids} | passed keep test and delete test"
    out: Dict[str, str] = {}
    for rel, names in plan.items():
        original = textio.read_text(Path(target) / rel)
        lines = original.splitlines()
        if names is None:
            spans = [(0, len(lines))]
        else:
            try:
                tree = ast.parse(original)
            except SyntaxError:
                return None
            spans = []
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in names:
                    start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
                    spans.append((start, node.end_lineno))
            if not spans:
                return None
        for start, end in sorted(spans, reverse=True):
            block = [("# " + l) if l.strip() else "#" for l in lines[start:end]]
            lines[start:end] = [header] + block
        out[rel] = "\n".join(lines) + "\n"
    return out


def _removed_names(old: str, new: str) -> set:
    try:
        before = set(_defs(ast.parse(textwrap.dedent(old))))
        after = set(_defs(ast.parse(textwrap.dedent(new)))) if new.strip() else set()
    except SyntaxError:
        return set()
    return before - after
