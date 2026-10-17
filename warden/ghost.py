"""Ghost Tools consumer.

Ghost Tools owns forensic truth. This module reads its JSON. It does not
re-implement detectors, ledgers, surgeons, or mutation.

If ghost_buster is importable, `scan()` will run a read-only mechanical
scan. If it is not, `load_findings()` still works on a JSON file produced
elsewhere. Absence of Ghost Tools is UNKNOWN, not a clean bill of health.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from .isolation import run_instrument
from .models import Defect, defects_from_ghost


class GhostCrashed(RuntimeError):
    """Ghost started and died (exit 3). A fault in Ghost, never a finding and never a clean scan."""


class GhostRefused(RuntimeError):
    """Ghost did not start (exit 2): bad arguments, missing target, unreadable input."""


def load_findings(path: Path) -> tuple[dict[str, Any], ...]:
    return load_report(path)


def load_report(path: Path) -> "Findings":
    """Findings from a saved Ghost JSON: the old bare list or the new object. Same tuple of
    records either way; the new object's status, scan counts and gaps ride along."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "findings" in raw:
        try:
            return _read_report(raw)
        except RuntimeError as exc:
            raise ValueError(f"{path}: {exc}") from exc
    if isinstance(raw, list) and all(isinstance(f, dict) for f in raw):
        old = Findings(raw)
        old.version_unverified = True
        return old
    raise ValueError(f"{path}: not a Ghost Tools findings JSON (a list of records)")


def defects_from_file(path: Path) -> tuple[Defect, ...]:
    return defects_from_ghost(load_findings(path))


class Findings(tuple):
    """Ghost's findings, plus what Ghost said about how much it looked at.

    It is an ordinary tuple of findings. `blind` is a plain sentence when Ghost
    said it analysed nothing, so an empty list must not be read as clean; it is
    None when nothing was wrong or Ghost did not say.
    """

    blind: Optional[str] = None
    #: New Ghost only (None for the old bare list): "ok", "incomplete" or "error".
    status: Optional[str] = None
    #: New Ghost only: files_scanned, files_skipped, files_unparsable.
    scan_counts: Optional[dict] = None
    #: Plain sentences for checks that should have run and did not (see `_gaps`). Empty means no real gap.
    gaps: tuple[str, ...] = ()
    #: Names of checks left out because the caller asked (or they are opt-in). Information, not a gap.
    declined: tuple[str, ...] = ()
    #: New Ghost only: what it said about its baseline file, {"path": str|None, "suppressed": int}.
    #: None: it said nothing.
    baseline: Optional[dict] = None
    #: True for an old Ghost that prints a bare list. It cannot say what it did not look at, so a clean
    #: result from it is accepted as before, but its version could not be verified.
    version_unverified: bool = False


DEFAULT_TIMEOUT = 600

_SCANNED = re.compile(r"scanning\s+(\d+)\s+file", re.IGNORECASE)
_NOTHING = re.compile(r"nothing\s+(was\s+)?analy[sz]ed|no\s+files?\s+(were\s+)?(scanned|analy[sz]ed)", re.IGNORECASE)


def _blind(stderr: str) -> Optional[str]:
    """A sentence if Ghost's stderr says it analysed nothing (Ghost prints 'scanning N file(s)')."""
    if _NOTHING.search(stderr):
        return "Ghost said it analysed nothing, so an empty list of findings does not mean the code is clean"
    counts = [int(n) for n in _SCANNED.findall(stderr)]
    if counts and counts[-1] == 0:
        return "Ghost scanned 0 files, so an empty list of findings does not mean the code is clean"
    return None


def _clean(text: Any, limit: int = 160) -> str:
    """One line of plain text, no control characters, capped. Ghost's words are data, not markup."""
    out = "".join(ch if ch.isprintable() else " " for ch in str(text))
    out = " ".join(out.split())
    return out if len(out) <= limit else out[: limit - 3] + "..."


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _gaps(rows: Any, counts: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(gaps, declined) from Ghost's `unmeasured` rows.

    The rule: a row counts as a gap unless Ghost says the caller asked for it
    (`by_request` true; `requested` is accepted as the same thing). Opt-in checks nobody
    requested and checks the caller declined are information. A row that does not say
    either way is a gap, because a missing answer is not permission. Unparsable files are a
    gap even if Ghost forgot the row.
    """
    gaps: list[str] = []
    declined: list[str] = []
    if not isinstance(rows, list):
        return ("Ghost's list of unmeasured checks was not readable",), ()
    for row in rows:
        if not isinstance(row, Mapping):
            gaps.append("Ghost gave an unmeasured entry that was not a record")
            continue
        check = _clean(row.get("check", "?"), 40)
        asked = row.get("by_request", row.get("requested"))
        if asked is True:
            declined.append(check)
            continue
        gaps.append(f"{check}: {_clean(row.get('reason') or 'did not run, no reason given')}")
    if _count(counts.get("files_unparsable")) and not any(g.startswith("parse:") for g in gaps):
        gaps.append(f"parse: {_count(counts.get('files_unparsable'))} file(s) could not be parsed")
    return tuple(gaps), tuple(declined)


def _read_baseline(raw: Any, out: "Findings") -> Optional[str]:
    """Read Ghost's `baseline` object, tolerantly. Returns a gap sentence when findings were hidden by it.

    Absent is fine (older Ghost). Present but unreadable, or with suppressed above 0, is a gap: a
    finding hidden by a baseline is a finding the caller was not shown.
    """
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        return "Ghost's baseline note was not readable, so findings it hid cannot be ruled out"
    path = raw.get("path")
    path = _clean(path, 120) if isinstance(path, str) and path else None
    suppressed = raw.get("suppressed")
    if suppressed is None:
        out.baseline = {"path": path, "suppressed": None}
        return None
    if isinstance(suppressed, bool) or not isinstance(suppressed, int) or suppressed < 0:
        out.baseline = {"path": path, "suppressed": None}
        return "Ghost's baseline note did not give a usable count of hidden findings"
    out.baseline = {"path": path, "suppressed": suppressed}
    if suppressed > 0:
        where = f" ({path})" if path else ""
        return (f"baseline: {suppressed} finding(s) were hidden by Ghost's baseline file{where}, so the scan "
                "did not show everything it found")
    return None


def _read_report(data: Mapping[str, Any]) -> "Findings":
    """Findings from new Ghost's JSON object. Raises RuntimeError if it cannot be trusted."""
    rows = data["findings"]
    if not isinstance(rows, list) or not all(isinstance(f, dict) for f in rows):
        raise RuntimeError("ghost_buster JSON was not a list of findings")
    for f in rows:
        if "id" in f and not isinstance(f["id"], str):
            raise RuntimeError("ghost_buster gave a finding whose id is not text")
    status = data.get("status")
    if status is not None and status not in ("ok", "incomplete", "error"):
        raise RuntimeError(f"ghost_buster gave a status Warden does not know ({_clean(status, 30)!r})")
    if status == "error":
        err = data.get("error")
        said = _clean(err.get("message", "") if isinstance(err, Mapping) else err or "no reason given")
        raise RuntimeError(f"ghost_buster reported an error instead of a scan: {said}")
    counts = data.get("scan")
    counts = counts if isinstance(counts, Mapping) else {}
    out = Findings(rows)
    out.status = status
    out.scan_counts = {k: _count(counts.get(k)) for k in ("files_scanned", "files_skipped", "files_unparsable")}
    out.gaps, out.declined = _gaps(data.get("unmeasured", []), counts)
    # New Ghost always says what it left unmeasured, how much it scanned and how it ended. An object that
    # leaves one of them out has not said what it did not look at.
    absent = [k for k in ("status", "scan", "unmeasured") if k not in data]
    if absent:
        out.gaps += (f"Ghost's output left out {', '.join(absent)}, so what it did not look at is unknown",)
    baseline_gap = _read_baseline(data.get("baseline"), out)
    if baseline_gap:
        out.gaps += (baseline_gap,)
    if status == "incomplete" and not out.gaps:
        out.gaps = ("Ghost said its scan was incomplete and did not say why",)
    if "files_scanned" in counts and out.scan_counts["files_scanned"] == 0 and not rows:
        out.blind = "Ghost scanned 0 files, so an empty list of findings does not mean the code is clean"
    return out


def _stderr_tail(stderr: str) -> str:
    lines = [ln for ln in stderr.strip().splitlines() if ln.strip()]
    return _clean(lines[-1], 200) if lines else "no reason given"


def scan(
    target: Path,
    *,
    ghost_tools_root: Optional[Path] = None,
    python: str = sys.executable,
    ghost_timeout: float = DEFAULT_TIMEOUT,
    joins: Sequence[Path] = (),
) -> tuple[dict[str, Any], ...]:
    """Read-only Ghost Tools scan. Does not operate, does not write a ledger.

    `joins` are sibling checkouts Ghost may read beside the target (its `--join`), so a boundary
    the target reaches across is looked at instead of reported as a gap. Without any, the scan
    is single-repository and Ghost says so. Ghost only reads a joined checkout; it is never on
    the import path (see `isolation`).

    Returns the findings list (a `Findings`; with new Ghost it also carries `status`,
    `scan_counts`, `gaps` and `declined`, see `_gaps` for the rule). Raises `InstrumentRootError` when
    `ghost_tools_root` is not an existing directory holding `ghost_buster` (an installed copy never stands in),
    and raises if the CLI cannot be run, does not finish within `ghost_timeout` seconds, or prints something
    that is not a list of findings. That is UNKNOWN-as-exception, not 'zero findings'.
    """
    target = Path(target).resolve()
    cmd = [
        python,
        "-m",
        "ghost_buster.cli",
        str(target),
        "--json",
        *(["--single-repo"] if not joins else []),
        "--no-tests",
        "--no-secrets",
        "--no-ledger",
        "--no-structure",
        "--no-project",
        "--no-correlate",
    ]
    for join in joins:
        cmd += ["--join", str(Path(join).resolve())]
    try:
        proc = run_instrument(cmd, roots=[ghost_tools_root], timeout=ghost_timeout,
                              packages={"ghost_buster": ghost_tools_root})
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"ghost_buster did not finish within {ghost_timeout:g} seconds") from exc
    # New Ghost: 0 clean, 1 findings, 2 did not start, 3 crashed. Old Ghost: 2 was usage.
    if proc.returncode == 3:
        raise GhostCrashed(f"Ghost crashed (exit code 3): {_stderr_tail(proc.stderr)}")
    if proc.returncode == 2:
        raise GhostRefused(f"Ghost did not start (exit code 2): {_stderr_tail(proc.stderr)}")
    if proc.returncode not in (0, 1) or not proc.stdout.strip():
        raise RuntimeError(
            f"ghost_buster failed ({proc.returncode}): {proc.stderr[-800:]}"
        )
    try:
        data = json.loads(proc.stdout)
    except ValueError as exc:
        raise RuntimeError("ghost_buster printed something that is not JSON") from exc
    if isinstance(data, dict) and "findings" in data:
        report = _read_report(data)
        if not report and not report.blind:
            report.blind = _blind(proc.stderr)
        return _check_exit_matches(report, proc.returncode)
    if not isinstance(data, list) or not all(isinstance(f, dict) for f in data):
        raise RuntimeError("ghost_buster JSON was not a list of findings")
    for f in data:
        if "id" in f and not isinstance(f["id"], str):
            raise RuntimeError("ghost_buster gave a finding whose id is not text")
    out = Findings(data)
    out.blind = _blind(proc.stderr) if not data else None
    out.version_unverified = True
    return _check_exit_matches(out, proc.returncode)


def _check_exit_matches(report: "Findings", code: int) -> "Findings":
    """Ghost exits 1 when it found something. Exit 1 with an empty list does not add up: a gap."""
    if code == 1 and not len(report):
        report.gaps += ("Ghost exited 1 (it found something) but listed no findings",)
    return report


def finding_ids(findings: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(str(f["id"]) for f in findings if f.get("id"))
