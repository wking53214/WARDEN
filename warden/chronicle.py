"""The chronicle: one line per run, keyed by (origin, base commit, claimed commit); the next run settles its promises.

A held result promises things nobody checks: that the suite stays green on the held tree, that a new finding a
person keeps is still there (standing), that a finding the change closed stays closed, that the checks the scan
declined get measured one day. The next run on that tree measures all of it at its start (the first suite pass,
the first Ghost scan) and nobody joined the two records. The chronicle joins them.

`warden tagteam --chronicle DIR` appends one JSON line per run to `<DIR>/<origin slug>.jsonl`: the claim row, the
verdict, the suite counts, the finding ids (standing, new, closed), the held digest and held tree digest, the
participants, and the promises the run opens if kept. At the start of such a run the file is read; every earlier
entry whose claimed or held tree digest equals this run's base tree digest is settled against this run's first
measurements (HELD or BROKEN, each with the measurement that settles it), and the settlement is written into this
run's line and the record's notes. `warden keep --chronicle DIR` appends a human line (who, when, which digest).
`warden chronicle DIR [--origin X]` prints the chain in order.

Keyed by origin and commits, never by the path of a clone: twenty clones of one repository are one history, and a
chronicle keyed by path reads a scan of another commit as a finding that "returned" (sim9/C_CHRONICLE.md).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

#: A declined check is a gap the run leaves open; after this many days unmeasured the promise to close it is broken.
GAP_DAYS = 90
_SLUG = re.compile(r"[^A-Za-z0-9._-]+")


def slug(origin: Optional[str]) -> str:
    """The file name for an origin: its readable part plus a short digest, so two origins never share a file."""
    text = origin or "no-origin"
    plain = _SLUG.sub("-", text).strip("-")[:80] or "origin"
    return f"{plain}-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:8]}"


def path_for(directory: Path, origin: Optional[str]) -> Path:
    return Path(directory) / f"{slug(origin)}.jsonl"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read(directory: Path, origin: Optional[str]) -> list[dict]:
    """Every readable line of the origin's file, in the order it was written. An unreadable line is skipped."""
    path = path_for(directory, origin)
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def append(directory: Path, origin: Optional[str], line: Mapping[str, Any]) -> Path:
    path = path_for(directory, origin)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, sort_keys=True) + "\n")
    return path


def _counts(suite: Optional[Mapping[str, Any]]) -> Optional[dict]:
    if not suite or not suite.get("ran"):
        return None
    return {k: suite.get(k, 0) for k in ("passed", "failed", "errors", "skipped", "xfailed", "xpassed")}


def promises(row: Mapping[str, Any], declined: Sequence[str]) -> list[dict]:
    """What this run promises if its result stands or is kept: the suite stays green at these counts, each new
    finding stays where a person can see it, each closed finding stays closed, each declined check gets measured."""
    out = []
    counts = _counts(row.get("suite_after"))
    if counts is not None:
        out.append({"promise": "suite_green", "expect": counts})
    for finding in row.get("new_findings") or ():
        out.append({"promise": f"standing:{finding['id']}", "expect": "present"})
    for ident in row.get("closed_findings") or ():
        out.append({"promise": f"fixed:{ident}", "expect": "absent"})
    for check in declined:
        out.append({"promise": f"gaps_closed:{check}", "expect": f"measured within {GAP_DAYS} days"})
    return out


def entry(row: Mapping[str, Any], standing: Sequence[str], declined: Sequence[str], settled: Sequence[dict],
          when: Optional[str] = None) -> dict:
    """This run's line."""
    return {
        "kind": "run", "when": when or now_iso(),
        "key": {"origin": row["origin"], "base_commit": row["base_commit"], "claimed_commit": row["claimed_commit"]},
        "claim": dict(row), "decision": row["decision"],
        "verdict": {"judge": row["judge"], "rules_fired": row["rules_fired"]},
        "suite": {"before": _counts(row.get("suite_before")), "after": _counts(row.get("suite_after"))},
        "findings": {"standing": list(standing), "new": [f["id"] for f in row.get("new_findings") or ()],
                     "closed": list(row.get("closed_findings") or ())},
        "held_digest": row["held_digest"], "held_tree_digest": row["held_tree_digest"],
        "claimed_tree_digest": row["claimed_tree_digest"], "participants": row["participants"],
        "promises": promises(row, declined), "settled": list(settled),
    }


def keep_line(origin: Optional[str], digest: str, who: str, reason: str, key: Optional[Mapping[str, Any]]) -> dict:
    return {"kind": "keep", "when": now_iso(), "origin": origin, "digest": digest, "who": who, "reason": reason,
            "key": dict(key) if key else None}


def _days_between(opened: str, now: str) -> Optional[float]:
    try:
        return (datetime.fromisoformat(now) - datetime.fromisoformat(opened)).total_seconds() / 86400
    except ValueError:
        return None


def _settle_one(promise: Mapping[str, Any], suite_before: Optional[Mapping[str, Any]],
                observed: Optional[Sequence[str]], declined: Sequence[str], opened: str, now: str) -> tuple[str, str]:
    name, expect = str(promise.get("promise", "")), promise.get("expect")
    if name == "suite_green":
        counts = _counts(suite_before)
        if counts is None:
            return "OPEN", "the suite was not measured at the start of this run"
        green = counts["failed"] == 0 and counts["errors"] == 0 and counts["passed"] > 0
        same = isinstance(expect, Mapping) and all(
            counts.get(k) == expect.get(k) for k in ("passed", "failed", "errors"))
        words = f"first pass {counts['passed']} passed, {counts['failed']} failed, {counts['errors']} errors"
        if isinstance(expect, Mapping):
            words += f"; promised {expect.get('passed')} passed" + (", identical counts" if same else ", counts differ")
        return ("HELD" if green else "BROKEN"), words
    if name.startswith(("standing:", "fixed:")):
        if observed is None:
            return "OPEN", "Ghost did not scan at the start of this run"
        ident = name.split(":", 1)[1]
        present = ident in observed
        if name.startswith("standing:"):
            return ("HELD", "present at this run's first scan") if present else (
                "BROKEN", "absent at this run's first scan: closed or renamed without a run saying so")
        return ("BROKEN", "present at this run's first scan: the finding returned") if present else (
            "HELD", "absent at this run's first scan")
    if name.startswith("gaps_closed:"):
        check = name.split(":", 1)[1]
        if check not in declined:
            return "HELD", "measured in this run"
        age = _days_between(opened, now)
        if age is not None and age > GAP_DAYS:
            return "BROKEN", f"still declined after {age:.0f} days"
        return "OPEN", "still declined; not yet overdue"
    return "OPEN", "a promise this Warden does not know how to settle"


def settle(entries: Sequence[Mapping[str, Any]], base_tree_digest: Optional[str],
           suite_before: Optional[Mapping[str, Any]], observed: Optional[Sequence[str]], declined: Sequence[str],
           now: Optional[str] = None) -> list[dict]:
    """Every promise of every earlier run whose claimed or held tree is this run's base tree, settled against this
    run's first measurements. Nothing matches by path, by time or by chance: the trees must be the same bytes."""
    if not base_tree_digest:
        return []
    now = now or now_iso()
    out = []
    for item in entries:
        if item.get("kind") != "run":
            continue
        if base_tree_digest == item.get("held_tree_digest"):
            base_is = "held tree"
        elif base_tree_digest == item.get("claimed_tree_digest"):
            base_is = "claimed tree"
        else:
            continue
        for promise in item.get("promises") or ():
            status, measurement = _settle_one(promise, suite_before, observed, declined, str(item.get("when", "")), now)
            out.append({"settles": item.get("key"), "opened": item.get("when"), "base_is": base_is,
                        "promise": promise.get("promise"), "status": status, "measurement": measurement})
    return out


def notes_for(settled: Sequence[Mapping[str, Any]], limit: int = 20) -> list[str]:
    """One record note per settlement, so a reader of the record sees what the chronicle joined."""
    out = []
    for s in settled[:limit]:
        key = s.get("settles") or {}
        claimed = str(key.get("claimed_commit") or "no commit")[:12]
        out.append(f"Chronicle: {s['promise']} promised by the run of {claimed} on this tree ({s['base_is']}) is "
                   f"{s['status']}: {s['measurement']}.")
    if len(settled) > limit:
        out.append(f"Chronicle: and {len(settled) - limit} more settlement(s) in the chronicle line.")
    return out


def _short(value: Any, n: int = 12) -> str:
    return str(value)[:n] if value else "-"


def render(entries: Sequence[Mapping[str, Any]]) -> list[str]:
    """The chain as lines a person reads, in the order it was written."""
    lines = []
    for item in entries:
        if item.get("kind") == "keep":
            lines.append(f"{item.get('when')}  keep  {_short(item.get('digest'))} kept by {item.get('who')}: "
                         f"{item.get('reason')}")
            continue
        key, suite = item.get("key") or {}, item.get("suite") or {}
        claim = item.get("claim") or {}
        before, after = suite.get("before") or {}, suite.get("after") or {}
        findings = item.get("findings") or {}
        suite_text = (f"{before.get('passed', '-')}p/{before.get('failed', '-')}f -> "
                      f"{after.get('passed', '-')}p/{after.get('failed', '-')}f")
        lines.append(
            f"{item.get('when')}  run   base {_short(key.get('base_commit'))} -> claim "
            f"{_short(key.get('claimed_commit'))}  {item.get('decision')}  held {_short(item.get('held_digest'))}  "
            f"tree {_short(item.get('held_tree_digest'), 16)}  suite {suite_text}"
            f"  new {len(findings.get('new') or ())}  closed {len(findings.get('closed') or ())}"
            f"  opens {len(item.get('promises') or ())}  {claim.get('claimed_subject') or ''}".rstrip())
        for s in item.get("settled") or ():
            key2 = s.get("settles") or {}
            lines.append(f"    settles {_short(key2.get('claimed_commit'))}: {s.get('promise')} {s.get('status')} "
                         f"({s.get('measurement')})")
    return lines
