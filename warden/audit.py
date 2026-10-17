"""Rules 5 and 9: the defect audit file, with IDs that never change meaning.

Elegant.md, Rule 9: "Every defect gets a stable ID in a single source of
truth (e.g. `WARDEN_AUDIT.md`) ... IDs never reuse meanings once
published." Rule 5: document defects before fixing them.

`defects_from_ghost` numbers findings in scan order (C1, H1, ... per run), so
the same label can name a different defect tomorrow. That is fine for one
report and wrong for an audit. This module keeps the labels durable by
reading the audit file it wrote last time:

  - a finding already in the file keeps its ID, matched by Ghost's own ID;
  - a new finding gets the next unused number for its priority;
  - a finding that has left the scan keeps its row and its ID, marked
    "not seen in latest scan". It is never deleted and the ID is never given
    to anything else. A human marks it Fixed with the commit SHA.

Only the table between the markers is Warden's. Everything else in the file
(design analogy, layer map, invariants, notes) is the author's and is carried
over byte for byte.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Mapping, Sequence

from .models import DefectSeverity, ghost_severity_to_warden, safe_id

FILENAME = "WARDEN_AUDIT.md"
BEGIN = "<!-- warden:defects -->"
END = "<!-- /warden:defects -->"

_PREFIX = {DefectSeverity.CRITICAL: "C", DefectSeverity.HIGH: "H",
           DefectSeverity.MEDIUM: "M", DefectSeverity.LOW: "L"}
_ORDER = {"C": 0, "H": 1, "M": 2, "L": 3}
_ROW = re.compile(r"^\| (?P<id>[CHML]\d+) \| (?P<priority>[^|]*) \| (?P<status>[^|]*) \| "
                  r"(?P<detector>[^|]*) \| (?P<location>[^|]*) \| (?P<summary>.*) \| "
                  r"`(?P<ghost>[^`]*)` \|$", re.M)

_SKELETON = """# Warden audit

Single source of truth for defects in this repository (Elegant.md, Rules 5
and 9). The table is maintained by `warden audit`; IDs are never reused.
Mark a row Fixed by hand, with the commit SHA, when the fix lands.

## Design analogy

UNKNOWN: written by a person, not generated.

## Layer map

UNKNOWN: written by a person, not generated.

## Defects

{begin}
{end}

## Invariant properties

UNKNOWN: written by a person, not generated.
"""


@dataclass
class Row:
    id: str
    priority: str
    status: str
    detector: str
    location: str
    summary: str
    ghost: str

    def render(self) -> str:
        return (f"| {self.id} | {self.priority} | {self.status} | {self.detector} | "
                f"{self.location} | {self.summary} | `{self.ghost}` |")


def _clean(text: str, limit: int = 140) -> str:
    text = " ".join(str(text).split()).replace("|", "/")
    return text if len(text) <= limit else text[:limit - 3] + "..."


def existing_rows(text: str) -> List[Row]:
    return [Row(**{k: v.strip() for k, v in m.groupdict().items()}) for m in _ROW.finditer(text)]


def has_markers(text: str) -> bool:
    return BEGIN in text and END in text and text.index(BEGIN) < text.index(END)


def _split_location(location: str):
    m = re.match(r"^(?P<file>.*?)(?::(?P<line>\d+))?$", str(location))
    if m is None:  # the pattern can match any text, but a type checker cannot know that
        return str(location).replace("\\", "/"), ""
    return m.group("file").replace("\\", "/"), m.group("line") or ""


def _same_defect_renamed(row: Row, f: Mapping) -> bool:
    """True when `f` looks like `row` after Ghost's one-time id change: same detector, summary and
    line, and a path that is the old one with folders added in front (paths became relative to the
    scanned folder). A finding on the very same path is never a rename: it is a different finding."""
    ev = f.get("evidence") or {}
    old_file, old_line = _split_location(row.location)
    new_file = _clean(ev.get("file") or "").replace("\\", "/")
    return (bool(old_file) and new_file != old_file and new_file.endswith("/" + old_file)
            and _clean(f.get("detector", ""), 40) == row.detector
            and _clean(f.get("summary", "")) == row.summary
            and str(ev.get("line_start") or "") == old_line)


def _adopt_renamed_ids(rows: List[Row], by_ghost: Dict[str, Row], findings: Sequence[Mapping]) -> None:
    """Ghost's ids changed once. A row whose Ghost id is gone and a finding whose id is new are the
    same defect only when each is the other's single match under `_same_defect_renamed`; the row
    then keeps its Warden id and takes the new Ghost id. Anything ambiguous is left alone and
    handled as before (a new row). Never guessed."""
    current = {safe_id(f["id"]) for f in findings if f.get("id")}
    orphans = [r for r in rows if r.ghost and r.ghost not in current]
    fresh = [f for f in findings if f.get("id") and safe_id(f["id"]) not in by_ghost]
    pairs = [(r, f) for r in orphans for f in fresh if _same_defect_renamed(r, f)]
    for r, f in pairs:
        if sum(1 for r2, _ in pairs if r2 is r) == 1 and sum(1 for _, f2 in pairs if f2 is f) == 1:
            by_ghost.pop(r.ghost, None)
            r.ghost = safe_id(f["id"])
            by_ghost[r.ghost] = r


def update(existing_text: str, findings: Sequence[Mapping]) -> str:
    """The audit file with its defect table brought up to date."""
    text = existing_text if has_markers(existing_text) else (
        _SKELETON.format(begin=BEGIN, end=END))
    rows = existing_rows(text[text.index(BEGIN):text.index(END)])
    by_ghost: Dict[str, Row] = {r.ghost: r for r in rows if r.ghost}
    used: Dict[str, int] = {p: 0 for p in _ORDER}
    for r in rows:
        used[r.id[0]] = max(used[r.id[0]], int(r.id[1:]))

    _adopt_renamed_ids(rows, by_ghost, findings)
    seen = set()
    for f in findings:
        ghost = safe_id(f.get("id") or "") if f.get("id") else ""
        if not ghost or ghost in seen:
            continue
        seen.add(ghost)
        evidence = f.get("evidence") or {}
        location = _clean(evidence.get("file") or "")
        if evidence.get("line_start"):
            location += f":{evidence['line_start']}"
        if ghost in by_ghost:
            row = by_ghost[ghost]
            if row.status.startswith("not seen"):
                row.status = "Open"
            elif row.status.startswith("Fixed"):
                row.status = f"Reopened (was {row.status})"
            continue
        severity = ghost_severity_to_warden(str(f.get("severity", "minor")))
        prefix = _PREFIX[severity]
        used[prefix] += 1
        row = Row(id=f"{prefix}{used[prefix]}", priority=severity.value.upper(), status="Open",
                  detector=_clean(f.get("detector", ""), 40), location=location,
                  summary=_clean(f.get("summary", "")), ghost=ghost)
        rows.append(row)
        by_ghost[ghost] = row

    for row in rows:
        if row.ghost not in seen and (row.status == "Open" or row.status.startswith("Reopened")):
            row.status = "not seen in latest scan"

    rows.sort(key=lambda r: (_ORDER[r.id[0]], int(r.id[1:])))
    table = "\n".join(["| ID | Priority | Status | Detector | Location | Summary | Ghost ID |",
                       "|---|---|---|---|---|---|---|"] + [r.render() for r in rows])
    open_ids = [r.id for r in rows if r.status == "Open" or r.status.startswith("Reopened")]
    order = ("Fix order by priority (Rule 8: a person moves critical-path IDs to the front): "
             + (", ".join(open_ids) if open_ids else "nothing open") + ".")
    block = f"{BEGIN}\n{table}\n\n{order}\n{END}"
    return text[:text.index(BEGIN)] + block + text[text.index(END) + len(END):]
