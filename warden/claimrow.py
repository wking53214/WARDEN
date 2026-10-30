"""The claim row: what one run governed, as facts a stranger can check without the clone.

A run record said what Warden decided; it did not say which change it decided about. `held_digest`
covers every file of the held tree, the receipt's before and after revisions are both the parent, and
`files_changed` mixes the actor's files with the Finisher's. A reader with the record and read access to
the repository could not name the commit that was held.

`claim_row` builds one flat row from what the run already had in its hands: the claim seat's facts
(commit, parent, tree, diff sha256, each file's sha256 before and after), the grant, the structured
suite results, Ghost's findings before and after, the Judge's sentences, the decision, the held digest
and the digest of the held tree. Nothing in it is invented after the fact. The key set is fixed and
shared with the hub (`cns.run.RunRecord.claim` from CNS 2.1.0): `KEYS`. `removals` (0.16.0) lists what a claim-seat
commit deleted or shrank, each with its path, kind, lines before and after and whether the path is protected.

An ordinary Drafter run gets a row too, with `claimed_commit` null and `files` from the Transformation
that was applied, so every record names its files by digest.
"""

from __future__ import annotations

import difflib
import hashlib
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Optional

from . import gitstate, versions
from .guard import hooks_dirs, is_protected, real_rel

#: The row's keys, in order. Fixed: a reader joins on these names.
KEYS = ("origin", "base_commit", "base_tree_digest", "claimed_commit", "claimed_tree_digest", "claimed_subject",
        "claimed_author", "claimed_date", "diff_sha256", "diff_bytes", "files", "actor", "authority",
        "authorization_id", "scope", "transformation_id", "suite_before", "suite_after", "ghost_before_count",
        "ghost_after_count", "new_findings", "closed_findings", "rules_fired", "judge", "decision", "held_digest",
        "held_tree_digest", "participants", "finisher_edits", "removals")

#: The authority a `warden tagteam --authorize` grant carries (the same word the horsemen receipt uses).
HUMAN_AUTHORITY = "human_operator"


def origin_of(target: Path) -> Optional[str]:
    """Where the target's history comes from: its `remote.origin.url`, or None when it has no remote.

    A row is keyed by origin and commits, never by the path of the clone the run happened in: twenty
    clones of one repository are one history, and one path reused for twenty repositories is not."""
    done = gitstate._git(Path(target), "config", "--get", "remote.origin.url")
    if done is None or done.returncode != 0:
        return None
    url = done.stdout.strip()
    return url or None


def _sha256(data: Optional[bytes]) -> Optional[str]:
    return None if data is None else hashlib.sha256(data).hexdigest()


def _suite(run: Any, passes: tuple, last: bool = False) -> Optional[dict]:
    """A suite result as a row, with the number of the pass it came from and the pass it reused, if any."""
    if run is None:
        return None
    found = [p for p in passes if p.get("result") is run]
    where = (found[-1] if last else found[0]) if found else {}
    plain = {k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(run).items()}
    return {**plain, "pass": where.get("pass"), "reused_from": where.get("reused_from")}


def _main_proposal(result: Any):
    """The proposal the row is about: the claim seat's, else the first proposal that was applied."""
    for cycle in result.cycles:
        if cycle.proposal is not None and getattr(cycle.proposal, "claim", None) is not None:
            return cycle, cycle.proposal
    for cycle in result.cycles:
        if cycle.applied and cycle.proposal is not None:
            return cycle, cycle.proposal
    return None, None


def _protected(target: Path, path: str, hooks: tuple) -> bool:
    real = real_rel(target, path)
    return is_protected(path, hooks) or (real is not None and is_protected(real, hooks))


def _files(result: Any, target: Path, claim: Mapping[str, Any]) -> list[dict]:
    hooks = hooks_dirs(target)
    if claim.get("files"):
        return [{**dict(f), "protected": _protected(target, str(f["path"]), hooks)} for f in claim["files"]]
    out: dict[str, dict] = {}
    for cycle in result.cycles:
        if not (cycle.applied and cycle.proposal is not None):
            continue
        before = getattr(cycle, "restore", {}) or {}
        after = getattr(cycle, "applied_bytes", {}) or {}
        for edit in cycle.proposal.edits:
            old, new = before.get(edit.path), after.get(edit.path)
            if edit.path in out:
                out[edit.path]["after_sha256"] = _sha256(new)
                old_sha = out[edit.path]["before_sha256"]
            else:
                old_sha = _sha256(old)
            status = "A" if old_sha is None else ("D" if new is None else "M")
            out[edit.path] = {"path": edit.path, "status": status, "before_sha256": old_sha,
                              "after_sha256": _sha256(new), "protected": _protected(target, edit.path, hooks)}
    return list(out.values())


def _lines(data: Optional[bytes]) -> list[str]:
    return [] if data is None else data.decode("utf-8", "replace").splitlines()


def _finisher_edits(result: Any) -> list[dict]:
    cycle = getattr(result, "finish_cycle", None)
    if not result.finished or cycle is None or result.finish is None:
        return []
    before = getattr(cycle, "restore", {}) or {}
    after = getattr(cycle, "applied_bytes", {}) or {}
    out = []
    for path in dict.fromkeys(e.path for e in result.finish.edits):
        added = removed = 0
        for line in difflib.unified_diff(_lines(before.get(path)), _lines(after.get(path)), n=0, lineterm=""):
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1
        out.append({"path": path, "lines_added": added, "lines_removed": removed})
    return out


def _finding(defect: Any, words: Mapping[str, str]) -> dict:
    """`severity` is Ghost's own word for the finding (null when Ghost gave none), the word the Judge receives in
    `evidence.ghost_severity`; Warden's remapped word is `warden_severity`."""
    warden_severity = getattr(defect.severity, "value", defect.severity)
    return {"id": defect.identity, "detector": defect.detector, "severity": words.get(defect.identity),
            "file": defect.file, "line": defect.line, "summary": defect.summary, "warden_severity": warden_severity}


def _findings(result: Any) -> tuple[list[dict], list[str]]:
    before = Counter(d.identity for d in result.observed)
    after = Counter(d.identity for d in result.reobserved)
    new_ids = sorted((after - before).elements())
    by_id = {d.identity: d for d in reversed(result.reobserved)}
    words = getattr(result, "ghost_words", None) or {}
    new = [_finding(by_id[i], words) for i in new_ids if i in by_id]
    return new, sorted((before - after).elements())


def _participants(report: Optional[Mapping[str, Any]]) -> list[dict]:
    if not report:
        return []
    out = []
    for name in ("warden", "ghost_tools", "swizzle", "assay"):
        entry = report.get(name)
        if isinstance(entry, Mapping):
            out.append({"name": name, "commit": entry.get("commit"), "version": entry.get("version"),
                        "dirty": entry.get("dirty")})
    seats = report.get("seats")
    if isinstance(seats, Mapping):
        for role, seat in seats.items():
            if isinstance(seat, Mapping):
                out.append({"name": f"{role} seat", "commit": seat.get("commit"), "version": seat.get("version"),
                            "dirty": seat.get("dirty")})
    for join in report.get("joins") or ():
        if isinstance(join, Mapping):
            out.append({"name": f"join {join.get('path')}", "commit": join.get("commit"),
                        "version": join.get("version"), "dirty": join.get("dirty")})
    return out


def _judge(result: Any, report: Optional[Mapping[str, Any]]) -> dict:
    seats = (report or {}).get("seats") or {}
    seat = seats.get("judge") if isinstance(seats, Mapping) else None
    seat = seat if isinstance(seat, Mapping) else {}
    verdict = result.verdict
    return {"seat": seat.get("spec"), "version": seat.get("version"), "commit": seat.get("commit"),
            "verdict": None if verdict is None else verdict.decision}


def _authorization_id(auth: Any) -> Optional[str]:
    if auth is None:
        return None
    body = "\n".join(str(getattr(auth, k, "")) for k in ("actor", "operation", "subject", "scope", "reason", "at"))
    return "auth_" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def _transformation_id(proposal: Any) -> Optional[str]:
    if proposal is None:
        return None
    body = repr([(e.path, e.kind, e.old, e.new) for e in proposal.edits])
    return "xform_" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def claim_row(result: Any, authorization: Any, versions_report: Optional[Mapping[str, Any]] = None) -> dict:
    """The row for one finished `TagTeamResult`. Every key in `KEYS`, in that order; a fact the run did not
    have is null, never guessed. `versions_report` is the record's `versions` object (the participants)."""
    target = Path(result.target)
    cycle, proposal = _main_proposal(result)
    claim: Mapping[str, Any] = getattr(proposal, "claim", None) or {}
    claimed_tree = getattr(cycle, "tree_after", None) if cycle is not None and cycle.applied else None
    if claimed_tree is None:
        applied = [c for c in result.cycles if c.applied]
        claimed_tree = getattr(applied[-1], "tree_after", None) if applied else None
    evidence = getattr(result, "evidence", None)
    # The last suite measured: the Judge's final pass, else the Finisher's after-pass, else the loop's last one.
    suite_after = result.suite_after
    finish_cycle = getattr(result, "finish_cycle", None)
    if result.finished and finish_cycle is not None and finish_cycle.suite_after is not None:
        suite_after = finish_cycle.suite_after
    if evidence is not None and evidence.suite_after is not None:
        suite_after = evidence.suite_after
    new, closed = _findings(result)
    row = {
        "origin": origin_of(target),
        "base_commit": versions.git_commit(target),
        "base_tree_digest": result.baseline or None,
        "claimed_commit": claim.get("commit"),
        "claimed_tree_digest": claimed_tree,
        "claimed_subject": claim.get("subject"),
        "claimed_author": claim.get("author"),
        "claimed_date": claim.get("date"),
        "diff_sha256": claim.get("diff_sha256"),
        "diff_bytes": claim.get("diff_bytes"),
        "files": _files(result, target, claim),
        "actor": None if authorization is None else authorization.actor,
        "authority": None if authorization is None else HUMAN_AUTHORITY,
        "authorization_id": _authorization_id(authorization),
        "scope": None if authorization is None else authorization.scope,
        "transformation_id": _transformation_id(proposal),
        "suite_before": _suite(result.suite_before, getattr(result, "suite_passes", ())),
        "suite_after": _suite(suite_after, getattr(result, "suite_passes", ()), last=True),
        "ghost_before_count": len(result.observed),
        "ghost_after_count": len(result.reobserved),
        "new_findings": new,
        "closed_findings": closed,
        "rules_fired": [] if result.verdict is None else [str(r) for r in result.verdict.reasons],
        "judge": _judge(result, versions_report),
        "decision": result.decision,
        "held_digest": result.held_digest,
        "held_tree_digest": getattr(result, "held_tree_digest", None),
        "participants": _participants(versions_report),
        "finisher_edits": _finisher_edits(result),
        "removals": [dict(r) for r in getattr(result, "removals", ())],
    }
    assert tuple(row) == KEYS
    return row
