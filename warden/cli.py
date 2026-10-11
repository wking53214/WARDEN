"""warden — govern a change: observe, authorize, gate on the suite, record.

Warden does not decide what a good fix or good code looks like. A Drafter
(in the loop) and a Finisher (once, after it) do; see `warden.roles`.
`tagteam --drafter MODULE:FACTORY --finisher MODULE:FACTORY` names them.
Without a drafter the loop can only observe. Writes require --authorize ACTOR --reason TEXT. There is no
default actor.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from . import CONTRACT, __version__
from .authorization import Unauthorized, grant
from . import audit as audit_file, gitstate, runstate, textio, versions
from .ghost import load_report, scan as ghost_scan
from .tagteam import TagTeam


#: What `warden tagteam` exits with, by decision. Anything not listed here exits 1, never 0.
EXIT_CODES = {
    "ACCEPT": 0,
    "REJECT": 1,
    "JUDGE_REJECTED": 1,
    "NOT_CONVERGED": 1,
    "FINISH_REJECTED": 1,
    "USAGE_ERROR": 2,
    "SEAT_NOT_LOADED": 2,
    "ACCEPT_UNVERIFIED": 3,
    "ERROR": 4,
    "REFUSED": 5,
    "INCONCLUSIVE": 6,
    "INTERRUPTED": 7,
}

EXIT_CODE_HELP = """\
exit codes (only 0 means the change was accepted):
  0  ACCEPT. Measured, judged, and standing.
  1  REJECT, JUDGE_REJECTED, NOT_CONVERGED, FINISH_REJECTED, or any other rejection.
  2  usage error (the JSON says USAGE_ERROR), a seat could not be loaded, or SWIZZLE's own proofs are
     unsound (the JSON says INCONCLUSIVE; the exit is still 2). Nothing was written.
  3  ACCEPT_UNVERIFIED. A check did not run or the Judge could not decide. Changes were put back and held; keep them only with `warden keep`.
  4  ERROR. A seat failed, timed out, or gave the wrong kind of answer (an unknown Judge label counts).
     Nothing was approved and the tree was put back.
  5  REFUSED. No human authorization, or the folder has uncommitted git changes (commit or stash
     them first). A proposal may have been shown; nothing was written.
  6  INCONCLUSIVE. A needed measurement could not be made (Ghost down, a red suite from the
     start, an unusable ASSAY key), another run holds the target, or the folder is too big to put
     back. Nothing was written.
  7  INTERRUPTED. SIGTERM, SIGHUP or SIGINT arrived. The tree was put back as it was found.
The command always prints valid JSON on stdout; `reason` says why in one sentence."""


class ContractMismatch(ValueError):
    """A seat was written for a different version of Warden's shapes."""


class SeatShadowed(ContractMismatch):
    """A seat module came from inside the folder being governed instead of from its install."""


#: The folder being governed, set for the length of one `tagteam` so seat loading can check where a
#: seat's code really came from.
_governed: Path | None = None


def _clean_import_path(target: Path) -> None:
    """Take the working directory and the target out of the places Python looks for modules.

    Otherwise a `judge/seat.py` (or any seat module) planted in the folder being governed, or in the
    folder Warden was started from, would be imported instead of the installed seat.
    """
    cwd = Path.cwd().resolve()
    kept = []
    for entry in sys.path:
        if entry == "":
            continue
        try:
            real = Path(entry).resolve()
        except OSError:
            kept.append(entry)
            continue
        if real == cwd or real == target or real.is_relative_to(target):
            continue
        kept.append(entry)
    sys.path[:] = kept
    importlib.invalidate_caches()


def _check_seat_origin(spec: str, module_name: str, seat, target: Path) -> None:
    """Refuse a seat whose code (module, package or class) lives inside the folder being governed."""
    module = sys.modules.get(module_name)
    places = [getattr(module, "__file__", None), *list(getattr(module, "__path__", []) or [])]
    places.append(getattr(sys.modules.get(type(seat).__module__), "__file__", None))
    for place in places:
        if place and Path(place).resolve().is_relative_to(target):
            raise SeatShadowed(f"The seat {spec} was loaded from {place}, which is inside the folder being "
                               "governed, not from an installed seat. Warden will not run a seat the run could "
                               "edit. Nothing was run.")


def _positive_number(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
    if not value > 0 or value != value or value == float("inf"):
        raise argparse.ArgumentTypeError(f"{text!r} must be a number above 0")
    return value


def _at_least_one(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"{text!r} must be 1 or more")
    return value


def _assay_floor(text: str) -> int:
    """0 is the one explicit way to skip enforcement. Anything below 0 is a mistake, not a setting."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if value < 0:
        raise argparse.ArgumentTypeError(
            f"{text!r} is below 0. Use a positive number to require Ghost to catch that many known failure "
            "modes, or 0 to record the score without enforcing it")
    return value


class _JsonParser(argparse.ArgumentParser):
    """An argument parser whose errors also come out as valid JSON on stdout, exit 2, like every other stop."""

    def error(self, message: str):  # type: ignore[override]
        reason = f"usage error: {message}. Nothing was run."
        _print_json({"decision": "USAGE_ERROR", "reason": reason, "contract": CONTRACT, "notes": [reason]})
        self.print_usage(sys.stderr)
        print(f"warden: {reason}", file=sys.stderr)
        raise SystemExit(EXIT_CODES["USAGE_ERROR"])


def main(argv: list[str] | None = None) -> int:
    parser = _JsonParser(prog="warden")
    parser.add_argument("--version", action="version", version=f"warden {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_t = sub.add_parser("tagteam", help="loop: observe → propose → apply → re-inspect, until converged; then finish once",
                         epilog=EXIT_CODE_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    p_t.add_argument("path", type=Path)
    p_t.add_argument("--ghost-root", type=Path, default=None)
    p_t.add_argument("--drafter", default=None, metavar="MODULE:FACTORY",
                     help="in the loop: proposes fixes, e.g. drafter.seat:Drafter")
    p_t.add_argument("--judge", default=None, metavar="MODULE:FACTORY",
                     help="at the end, once: reads the evidence and decides ACCEPT or REJECT. "
                          "Without one, a run cannot be ACCEPTed, only ACCEPT_UNVERIFIED")
    p_t.add_argument("--finisher", default=None, metavar="MODULE:FACTORY",
                     help="after the loop, once: beautifies and writes the final README")
    p_t.add_argument("--max-cycles", type=_at_least_one, default=10,
                     help="most proposals that may be applied; declined ones do not use a cycle (default 10)")
    p_t.add_argument("--ghost-timeout", type=_positive_number, default=600,
                     help="seconds one Ghost scan may take; longer counts as Ghost being down (default 600)")
    p_t.add_argument("--suite-timeout", type=_positive_number, default=900,
                     help="seconds one run of the target's own test suite may take; longer counts as the "
                          "suite not running (default 900)")
    p_t.add_argument("--seat-timeout", type=_positive_number, default=3600,
                     help="seconds one seat call (Drafter, Finisher, Judge, or building a seat) may take "
                          "before the run stops as ERROR (default 3600)")
    p_t.add_argument("--swizzle-root", type=Path, default=None,
                     help="SWIZZLE checkout; its proofs must hold before anything is ACCEPTed")
    p_t.add_argument("--assay-root", type=Path, default=None,
                     help="ASSAY checkout; with --swizzle-root, Ghost is graded against its answer key first")
    p_t.add_argument("--assay-floor", type=_assay_floor, default=3,
                     help="the fewest known failure modes Ghost must catch for the Judge to accept "
                          "(default 3, where Ghost stands today). 0 is the one explicit way to skip: the score "
                          "is recorded, nothing requires it, and the output says so. Below 0 is rejected")
    p_t.add_argument("--from-ghost", type=Path, default=None, help="findings JSON instead of a live scan")
    p_t.add_argument("--authorize", default=None, metavar="ACTOR")
    p_t.add_argument("--reason", default="")
    p_t.add_argument("--scope", default="documentation",
                     help="documentation: real prose only (.md, .rst, .txt; not requirements, LICENSE, NOTICE "
                          "or CMakeLists.txt). code: anything outside tests, test and build config, CI, "
                          "dependency lists and git hooks")

    p_k = sub.add_parser("keep", help="apply one held unverified result, only with a human grant for its digest")
    p_k.add_argument("path", type=Path)
    p_k.add_argument("--digest", required=True, help="the held_digest a tagteam run reported for this folder")
    p_k.add_argument("--authorize", default=None, metavar="ACTOR",
                     help="the human approving this exact result; without it nothing is applied")
    p_k.add_argument("--reason", default="")

    p_a = sub.add_parser("audit", help="WARDEN_AUDIT.md: Ghost findings under durable IDs (Rules 5, 9)")
    p_a.add_argument("path", type=Path)
    p_a.add_argument("--ghost-root", type=Path, default=None)
    p_a.add_argument("--from-ghost", type=Path, default=None, help="findings JSON instead of a live scan")
    p_a.add_argument("--authorize", default=None, metavar="ACTOR",
                     help="write the file; without it the result is printed and nothing is written")
    p_a.add_argument("--reason", default="")

    args = parser.parse_args(argv)
    if args.command == "audit":
        return _audit(args)
    if args.command == "keep":
        return _keep(args)
    if args.command == "tagteam":
        try:
            return _tagteam(args)
        except Unauthorized as e:
            return _stop("REFUSED", str(e))
        except Exception as e:  # noqa: BLE001 - the CLI always prints valid JSON, never a traceback
            return _stop("ERROR", f"Warden failed with {type(e).__name__}. Nothing was approved.")
    return 2


def _print_json(payload) -> None:
    print(json.dumps(payload, indent=2))


def _stop(decision: str, reason: str, notes: list[str] | None = None) -> int:
    """End before a run: valid JSON on stdout, the reason on stderr, and the exit code for `decision`."""
    _print_json({"decision": decision, "reason": reason, "contract": CONTRACT, "notes": (notes or []) + [reason]})
    print(f"warden: {reason}", file=sys.stderr)
    return EXIT_CODES[decision]


def _keep(args) -> int:
    """Apply one held unverified result, and only with a human grant for that exact digest."""
    from .held import KEEP_OPERATION, HeldError, keep as keep_held
    path = Path(args.path)
    if not path.is_dir():
        return _stop("USAGE_ERROR", f"The folder {str(path)!r} does not exist or is not a directory. Nothing was kept.")
    if not args.authorize:
        return _stop("REFUSED", "Nothing was kept: no person was named. Pass --authorize with the approving "
                                "person's name and a --reason.")
    if not args.reason.strip():
        return _stop("REFUSED", "a reason is required")
    try:
        auth = grant(args.authorize, KEEP_OPERATION, f"{path.resolve()}@{args.digest}", "held-result", args.reason)
        outcome = keep_held(path, args.digest, auth)
    except (Unauthorized, HeldError) as e:
        return _stop("REFUSED", str(e))
    except Exception as e:  # noqa: BLE001 - the CLI always prints valid JSON, never a traceback
        return _stop("ERROR", f"Warden failed with {type(e).__name__}. Nothing was kept.")
    _print_json({"decision": outcome["decision"], "digest": outcome["digest"], "reason": outcome["reason"],
                 "approved_by": args.authorize, "contract": CONTRACT, "notes": [outcome["reason"]]})
    return 0


def _tagteam(args) -> int:
    """Run the loop once and print what happened as JSON."""
    path = Path(args.path)
    if not path.is_dir():
        what = "does not exist" if not path.exists() else "is not a directory"
        return _stop("USAGE_ERROR", f"The target {str(path)!r} {what}. Nothing was run.")
    findings = load_report(args.from_ghost) if args.from_ghost else None
    auth = None
    if args.authorize:
        if not args.reason.strip():
            return _stop("REFUSED", "a reason is required")
        try:
            auth = grant(args.authorize, "transform", str(path.resolve()), args.scope, args.reason)
        except Unauthorized as e:
            return _stop("REFUSED", str(e))
    warnings: list[str] = []
    global _governed
    _governed = path.resolve()
    saved_path = list(sys.path)  # put back afterwards so an in-process caller (a test) is not left changed
    try:
        _clean_import_path(_governed)
        try:
            with runstate.interrupts(), runstate.stdout_to_stderr(), \
                    runstate.seat_timer(args.seat_timeout, "A seat while it was being loaded"):
                drafter = _load_seat(args.drafter, warnings)
                finisher = _load_seat(args.finisher, warnings)
                judge = _load_seat(args.judge, warnings)
        except ContractMismatch as e:
            return _stop("SEAT_NOT_LOADED", str(e))
        except runstate.Interrupted as sig:
            return _stop("INTERRUPTED", f"Warden received {sig.signal_name} while loading seats. Nothing was run.")
        except runstate.SeatTimedOut as e:
            return _stop("SEAT_NOT_LOADED", f"{e} while it was being loaded. Nothing was run.")
        except Exception as e:  # noqa: BLE001 - a seat that will not load is named, never a traceback
            return _stop("SEAT_NOT_LOADED", f"A seat could not be loaded ({type(e).__name__}: {str(e)[:120]}).")
        for w in warnings:
            print(f"warden: warning: {w}", file=sys.stderr)
        return _run_team(args, auth, findings, drafter, finisher, judge, warnings)
    finally:
        _governed = None
        sys.path[:] = saved_path


def _run_team(args, auth, findings, drafter, finisher, judge, warnings=()) -> int:
    team = TagTeam(ghost_tools_root=args.ghost_root, swizzle_root=args.swizzle_root,
                   assay_root=args.assay_root, assay_floor=args.assay_floor,
                   drafter=drafter, finisher=finisher, judge=judge, max_cycles=args.max_cycles,
                   ghost_timeout=args.ghost_timeout, suite_timeout=args.suite_timeout,
                   seat_timeout=args.seat_timeout)
    # A seat that print()s, or writes straight to file descriptor 1, must not corrupt the JSON on stdout.
    with runstate.stdout_to_stderr():
        result = team.run(args.path, authorization=auth, findings=findings)
    payload = {
        "decision": result.decision,
        "converged": result.converged,
        "cycles": [{"number": c.number, "outcome": c.outcome, "observed": c.observed}
                   for c in result.cycles],
        "finished": result.finished,
        "put_back": result.put_back,
        "held_digest": result.held_digest,
        "reason": None if result.decision == "ACCEPT" else (result.reason or (result.notes[-1] if result.notes else "")),
        "notes": list(result.notes) + list(warnings),
        "observed": [d.identity for d in result.observed],
        "reobserved": [d.identity for d in result.reobserved],
        "contract": CONTRACT,
        "versions": _versions(args, drafter, finisher, judge),
        "swizzle_sound": result.swizzle_sound,
        "unmeasured": list(result.unmeasured),
        "ghost_scan": result.ghost_scan,
        "ghost_baseline": result.ghost_baseline,
        "drafter_skipped": list(result.drafter_skipped),
        "informational": list(result.informational),
        "verdict": None if result.verdict is None else {
            "decision": result.verdict.decision, "reasons": list(result.verdict.reasons),
            "judge": result.verdict.judge},
    }
    _print_json(payload)
    if result.swizzle_sound is False:
        print("warden: SWIZZLE's own proofs do not hold; nothing was written.", file=sys.stderr)
        return 2
    return EXIT_CODES.get(result.decision, 1)


def _versions(args, drafter, finisher, judge) -> dict:
    """What took part in this run: Warden, the instrument checkouts given, and the seats loaded."""
    import warden
    return versions.report(
        warden_module=warden, contract=CONTRACT, version=__version__,
        ghost_root=args.ghost_root, swizzle_root=args.swizzle_root, assay_root=args.assay_root,
        target=Path(args.path).resolve(),
        seats={"drafter": versions.seat(args.drafter, drafter, Path(args.path).resolve()),
               "finisher": versions.seat(args.finisher, finisher, Path(args.path).resolve()),
               "judge": versions.seat(args.judge, judge, Path(args.path).resolve())})


def _load_seat(spec, warnings: list[str] | None = None):  # `warnings` is kept for old callers; unused now
    """The seat-filler named as MODULE:FACTORY, built with no arguments; None if not named.

    A seat must declare `requires_contract`, the version of Warden's shapes it was written for. A
    different version is refused, and so is a seat that declares nothing: Warden cannot know such
    a seat fits, and it will not govern a run with a part it has not checked.
    """
    if not spec:
        return None
    module_name, _, attr = spec.partition(":")
    if not module_name or not attr:
        raise ValueError("expected MODULE:FACTORY")
    seat = getattr(importlib.import_module(module_name), attr)()
    if _governed is not None:
        _check_seat_origin(spec, module_name, seat, _governed)
    wanted = getattr(seat, "requires_contract", None)
    if wanted is None:
        raise ContractMismatch(f"The seat {spec} does not say which Warden contract it was written for, so its fit "
                               f"with this Warden (contract {CONTRACT!r}) cannot be checked. Nothing was run. "
                               f'Add requires_contract = "{CONTRACT}" to the seat.')
    if not isinstance(wanted, str) or wanted != CONTRACT:
        raise ContractMismatch(f"The seat {spec} was written for Warden contract {wanted!r} but this Warden "
                               f"is contract {CONTRACT!r}. Nothing was run.")
    return seat


def _audit(args) -> int:
    """Print the updated audit; write it only under a human grant."""
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"warden: the target {str(args.path)!r} does not exist or is not a directory.", file=sys.stderr)
        return 2
    try:
        if args.from_ghost:
            findings = load_report(args.from_ghost)
        elif args.ghost_root:
            findings = ghost_scan(root, ghost_tools_root=args.ghost_root)
        else:
            findings = None
    except Exception as e:  # noqa: BLE001 - an audit that could not read its findings must not look clean
        print(f"warden: the findings could not be read ({type(e).__name__}: {str(e)[:120]}). "
              "Nothing was printed or written.", file=sys.stderr)
        return 2
    if findings is not None and getattr(findings, "blind", None):
        print(f"warden: {findings.blind}. Nothing was printed or written.", file=sys.stderr)
        return 2
    if getattr(findings, "gaps", None):
        print("warden: warning: Ghost's scan had gaps (" + "; ".join(findings.gaps[:3]) + "), so a row marked "
              "'not seen in latest scan' may only be one Ghost could not look at.", file=sys.stderr)
    if findings is None:
        print("warden: audit needs --ghost-root or --from-ghost; an audit of nothing "
              "would read as a clean repository", file=sys.stderr)
        return 2
    path = root / audit_file.FILENAME
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        print(f"warden: {path} is a link or points outside the target; the audit will not be read "
              "or written through it.", file=sys.stderr)
        return 2
    try:
        current = textio.read_text(path) if path.is_file() else ""
    except textio.Undecodable:
        print(f"warden: {path} is not valid UTF-8, so it will not be touched.", file=sys.stderr)
        return 2
    try:
        updated = audit_file.update(current, findings)
    except Exception as e:  # noqa: BLE001 - garbled findings must not produce a half-made audit
        print(f"warden: the findings could not be used ({type(e).__name__}). Nothing was printed or written.",
              file=sys.stderr)
        return 2
    if not args.authorize:
        print(updated)
        return 0
    if current.strip() and not audit_file.has_markers(current):
        print(f"warden: {path} exists, has no Warden markers ({audit_file.BEGIN} and {audit_file.END}), "
              "and looks hand-written. It was not changed. Add the two markers where the table should go, "
              "or move the file aside.", file=sys.stderr)
        return 2
    try:
        auth = grant(args.authorize, "audit", str(root), "documentation", args.reason)
    except Unauthorized as e:
        print(f"warden: {e}", file=sys.stderr)
        return 2
    # Writing into the target follows the same rule as `tagteam`: uncommitted work is refused, except the
    # audit file itself (rerunning the audit to update its table is the normal flow).
    state = gitstate.tree_state(root, allow=(audit_file.FILENAME,))
    if state.kind in {"dirty", "unknown"}:
        why = ("the folder has uncommitted changes (" + state.detail + "). Commit or stash them first"
               if state.kind == "dirty" else state.detail)
        print(f"warden: {why}. Nothing was written.", file=sys.stderr)
        return 2
    try:
        textio.write_text(path, updated)
    except OSError as e:
        print(f"warden: {path} could not be written ({type(e).__name__}).", file=sys.stderr)
        return 2
    print(f"wrote {path} (authorized by {auth.actor})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

