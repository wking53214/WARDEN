"""warden: govern a change: observe, authorize, gate on the suite, record.

Warden does not decide what a good fix or good code looks like. A Drafter
(in the loop) and a Finisher (once, after it) do; see `warden.roles`.
`tagteam --drafter MODULE:FACTORY --finisher MODULE:FACTORY` names them.
Without a drafter the loop can only observe. Writes require --authorize ACTOR --reason TEXT. There is no
default actor.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import os
import re
import stat
import sys
from typing import Any, Optional, Sequence
from pathlib import Path

from . import CONTRACT, __version__
from .authorization import Unauthorized, grant
from . import audit as audit_file, gitstate, isolation, runstate, textio, versions
from . import claim as claimseat
from . import log as warden_log
from .ghost import load_report, scan as ghost_scan
from .tagteam import TagTeam

logger = warden_log.get("cli")


#: The ASSAY floor `warden tagteam --assay-floor` uses when the option is not given. The library's
#: `TagTeam(assay_floor=...)` defaults to `warden.tagteam.LIBRARY_ASSAY_FLOOR` (0, not enforced) instead.
CLI_ASSAY_FLOOR = 3


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
  3  ACCEPT_UNVERIFIED. A check did not run or the Judge could not decide. Changes were put back and
     held; keep them only with `warden keep`.
  4  ERROR. A seat failed, timed out, or gave the wrong kind of answer (an unknown Judge label counts),
     or the findings file given to --from-ghost could not be used. Nothing was approved and the tree was
     put back.
  5  REFUSED. No human authorization, or the folder has uncommitted git changes (commit or stash
     them first). A proposal may have been shown; nothing was written.
  6  INCONCLUSIVE. A needed measurement could not be made (Ghost down, the suite red when a
     proposed change was about to be applied, an unusable ASSAY key), another run holds the target,
     or the folder is too big to put back. Nothing was written. A suite that is red from the start
     but never meets a Drafter proposal ends 1 instead: FINISH_REJECTED if the Finisher's change
     was refused, JUDGE_REJECTED if the Judge saw the red suite.
  7  INTERRUPTED. SIGTERM, SIGHUP or SIGINT arrived. The tree was put back as it was found.
The command always prints valid JSON on stdout; `reason` says why in one sentence."""


#: What a `--stack` folder must hold, by folder name (matched without regard to case), and the
#: option each one fills when that option was not given: the three instrument roots and the three
#: seats, each seat by the module and class its repository publishes.
STACK_ROOTS = {"ghost_tools": "ghost_root", "swizzle": "swizzle_root", "assay": "assay_root"}
STACK_SEATS = {"drafter": ("drafter", "drafter.seat:Drafter"),
               "judge": ("judge", "judge.seat:Judge"),
               "burnish": ("finisher", "burnish.finisher:Burnish")}


def _resolve_stack(args) -> tuple[list[Path], str]:
    """Fill the instrument roots and the seats from one folder of sibling checkouts.

    Returns the seat checkouts to put on the import path and an empty string, or no paths and
    the reason the folder cannot be used. Every part must be there: a circuit with a seat
    missing is not the circuit, and a run that quietly went without it would read as one. An
    option given explicitly wins over the folder's copy. Folder names are matched without
    regard to case (`SWIZZLE` and `swizzle` are the same checkout); two folders that differ
    only by case are refused rather than guessed between. The folders actually filled in (not
    overridden by an explicit option) are left in `args.stack_used`, name to path: those are the
    checkouts the run executes or reads as instruments, and `_stack_use_problem` vets them.
    """
    stack = Path(args.stack)
    if not stack.is_dir():
        return [], f"the --stack folder {str(stack)!r} does not exist or is not a directory"
    found: dict[str, Path] = {}
    twice: list[str] = []
    for child in sorted(stack.iterdir()):
        if not child.is_dir():
            continue
        name = child.name.lower()
        if name in found:
            twice.append(name)
        found.setdefault(name, child)
    wanted = (*STACK_ROOTS, *STACK_SEATS)
    doubled = sorted(set(twice) & set(wanted))
    if doubled:
        return [], (f"the --stack folder {str(stack)!r} holds more than one folder named "
                    f"{', '.join(doubled)} (differing only by case), so it cannot be used")
    missing = [name for name in wanted if name not in found]
    if missing:
        return [], f"the --stack folder {str(stack)!r} has no {', '.join(missing)} checkout"
    used: dict[str, Path] = {}
    for name, option in STACK_ROOTS.items():
        if getattr(args, option) is None:
            setattr(args, option, found[name].resolve())
            used[name] = found[name].resolve()
    paths: list[Path] = []
    for name, (option, spec) in STACK_SEATS.items():
        if getattr(args, option) is None:
            setattr(args, option, spec)
            paths.append(found[name].resolve())
            used[name] = found[name].resolve()
    args.stack_used = used
    return paths, ""


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


STACK_MANIFEST_SCHEMA = "warden-stack/1"
#: A manifest pin: the whole commit, spelled the way git prints it (the same form `versions` records).
_FULL_COMMIT = re.compile(r"[0-9a-f]{40}")
#: Where CNS, the hub, keeps the circuit's stack manifest (relative to a CNS checkout).
CNS_MANIFEST = Path("contracts") / "warden-stack.json"


def _stack_folders(stack: Path) -> dict[str, Path]:
    """The checkouts in a --stack folder by lower-cased name (the same matching as `_resolve_stack`)."""
    out: dict[str, Path] = {}
    for child in sorted(stack.iterdir()):
        if child.is_dir():
            out.setdefault(child.name.lower(), child)
    return out


def _is_target(folder: Path, target: Path) -> bool:
    """The governed target itself, or a folder overlapping it: governed, not joined or vetted as a stack member."""
    real = folder.resolve()
    return real == target or real.is_relative_to(target) or target.is_relative_to(real)


def _joins_from_manifest(manifest_path: Path, stack: Optional[Path], target: Path,
                         used: Optional[dict] = None) -> tuple[list[Path], str]:
    """The checkouts a stack manifest names, each verified to be in the --stack folder at the pinned
    commit and free of uncommitted changes, minus the target itself. Returns (joins, "") or ([], the reason
    nothing can be run).

    `used` is the stack folders the run will execute or read as instruments (`args.stack_used`): each must be
    named by the manifest, because a folder the manifest does not cover has no pinned commit to be checked
    against. A clone of the target at the same commit as a stack member is not joined (it is the same
    repository), but it is still verified: it may be a seat or an instrument, and the pin says nothing about
    uncommitted changes in it."""
    from .versions import own_commit
    if stack is None:
        return [], "--stack-manifest needs --stack: the manifest names checkouts inside that folder"
    try:
        data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        return [], f"the stack manifest {str(manifest_path)!r} cannot be read: {type(err).__name__}: {err}"
    if not isinstance(data, dict) or data.get("schema") != STACK_MANIFEST_SCHEMA:
        return [], (f"the stack manifest {str(manifest_path)!r} does not say \"schema\": "
                    f"\"{STACK_MANIFEST_SCHEMA}\"")
    if str(data.get("contract")) != CONTRACT:
        return [], (f"the stack manifest is for seat contract {data.get('contract')!r}; this Warden "
                    f"speaks contract {CONTRACT!r}")
    repos = data.get("repos")
    if not isinstance(repos, dict) or not repos or not all(
            isinstance(k, str) and isinstance(v, str) and v for k, v in repos.items()):
        return [], "the stack manifest's \"repos\" must map each checkout name to a commit"
    folders = _stack_folders(Path(stack))
    joins: list[Path] = []
    target = target.resolve()
    target_commit = own_commit(target)
    covered = {name.lower() for name in repos}
    unnamed = [f"{name!r} (the checkout at {str(folder)!r})" for name, folder in (used or {}).items()
               if name not in covered and not _is_target(folder, target)]
    if unnamed:
        return [], ("the stack manifest does not name " + ", ".join(unnamed) + ", yet this run uses "
                    + ("it" if len(unnamed) == 1 else "them") + " as an instrument root or a seat, so nothing pins "
                    + ("it" if len(unnamed) == 1 else "them") + " to a commit. Add "
                    + ("it" if len(unnamed) == 1 else "them") + " to the manifest, or give that option explicitly")
    for name, pinned in repos.items():
        if not _FULL_COMMIT.fullmatch(pinned):
            return [], (f"the stack manifest pins {name!r} to {pinned[:12]!r}, which is not a full "
                        "40-character commit (lowercase hex, as git prints it). A full 40-character commit is "
                        "required: a short prefix or another spelling of a commit is refused")
        folder = folders.get(name.lower())
        if folder is None:
            return [], f"the stack manifest names {name!r}, which is not in the --stack folder"
        actual = own_commit(folder)
        if actual is None:
            return [], f"the stack manifest pins {name!r} to {pinned[:12]}, but {str(folder)!r} is not a git checkout"
        if actual != pinned:
            return [], (f"the stack manifest pins {name!r} to {pinned[:12]}, but the checkout at "
                        f"{str(folder)!r} is at {actual[:12]}")
        real = folder.resolve()
        if _is_target(folder, target):
            continue  # the target itself: governed, not joined
        problem = _joined_checkout_problem(name, folder)
        if problem:
            return [], problem
        if target_commit is not None and actual == target_commit:
            continue  # a clone of the target at the same commit: the same repository, so not joined (but vetted above)
        joins.append(real)
    return joins, ""


def _joined_checkout_problem(name: str, folder: Path, allow_not_git: bool = False) -> str:
    """The reason a stack checkout cannot be trusted to be its pinned commit, or empty.

    The commit alone does not say what is in the folder: a modified file or an untracked one (what
    `git status --porcelain` reports; ignored files do not count) is code the pin does not describe, and a seat
    or an instrument from there would run it. The target is not asked: its own dirty policy applies to it."""
    state = gitstate.tree_state(folder)
    if state.kind == "clean" or (allow_not_git and state.kind == "not_git"):
        return ""
    if state.kind == "dirty":
        flagged = (f"; {state.hidden} of them hidden from git status by an index flag, which `git update-index "
                   "--no-assume-unchanged` or `--no-skip-worktree` clears") if state.hidden else ""
        return (f"the stack folder {name!r} at {str(folder)!r} has uncommitted changes "
                f"({state.changed} path(s) are dirty{flagged}), so it is not the pinned commit. "
                "Commit, stash or remove them, or restore the checkout, then run again")
    detail = state.detail or "git would not say whether this folder has uncommitted work"
    return (f"whether the stack folder {name!r} at {str(folder)!r} has uncommitted "
            f"changes cannot be ruled out: {detail}")


def _stack_use_problem(used: dict, target: Path) -> str:
    """The reason a --stack run without a manifest cannot use the folders it filled in, or empty.

    Every stack folder the run executes or reads as an instrument must have no uncommitted changes, with or
    without a manifest. A folder that is not a git checkout cannot be asked (without a manifest nothing says it
    must be one), and the target itself is excluded as it is everywhere else."""
    for name, folder in used.items():
        if _is_target(folder, target):
            continue
        problem = _joined_checkout_problem(name, folder, allow_not_git=True)
        if problem:
            return problem
    return ""


def _join_problem(joins, target: Path) -> str:
    """The reason a --join cannot be used, or empty. A join must exist and lie wholly outside the target."""
    target = target.resolve()
    for join in joins:
        real = Path(join).expanduser().resolve()
        if not real.is_dir():
            return f"--join {str(join)!r} does not exist or is not a directory"
        if real == target or real.is_relative_to(target) or target.is_relative_to(real):
            return (f"--join {str(join)!r} is the folder being governed or overlaps it; a joined checkout "
                    "must lie outside the target")
    return ""


def _instrument_inside(args, target: Path) -> str:
    """The reason to refuse, when an instrument checkout (Ghost, SWIZZLE, ASSAY) is the folder being
    governed, lies inside it, or contains it; empty when none does. Like a seat, an instrument the run could
    edit is not independent of the run: its findings, proofs and answer key would be judging their own change.
    Both directions count: a target that is a subfolder of an instrument checkout (its package folder, its tests)
    is the instrument's own code under governance, as much as an instrument vendored into the target."""
    for option, flag in (("ghost_root", "--ghost-root"), ("swizzle_root", "--swizzle-root"),
                         ("assay_root", "--assay-root")):
        root = getattr(args, option, None)
        if not root:
            continue
        try:
            real = Path(root).resolve()
        except OSError:
            continue
        if real == target or real.is_relative_to(target):
            return (f"The instrument {flag} {root} is inside the folder being governed. Warden will not run "
                    "an instrument the run could edit. Nothing was run.")
        if target.is_relative_to(real):
            return (f"The folder being governed is inside the instrument {flag} {root}. Warden will not run "
                    "an instrument the run could edit. Nothing was run.")
    return ""


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

    def error(self, message: str):
        reason = f"usage error: {message}. Nothing was run."
        _print_json(_record("USAGE_ERROR", reason))
        self.print_usage(sys.stderr)
        print(f"warden: {reason}", file=sys.stderr)
        raise SystemExit(EXIT_CODES["USAGE_ERROR"])


#: What `_write_stdout` answers when the reader of stdout went away (a broken pipe).
_READER_LEFT = "the reader of standard output left"
#: The first stdout failure of the current `main` call, or None. Reset at the start of every call.
_delivery: dict[str, Optional[str]] = {"failure": None}


def _write_stdout(text: str) -> Optional[str]:
    """Print `text` and flush. None when delivered, `_READER_LEFT` on a broken pipe, otherwise why it was not."""
    out = sys.stdout
    if out is None:
        return "standard output is closed"
    try:
        print(text, file=out)
        out.flush()
        return None
    except BrokenPipeError:
        failure = _READER_LEFT
    except (OSError, ValueError) as err:  # ValueError: the stream was closed under us
        failure = f"{type(err).__name__}: {err}"
    real = sys.__stdout__
    if real is not None and out is real:
        # The bytes that failed are still queued; the interpreter would flush them again at exit and end in status
        # 120 with a message of its own. Closing the stream drops them (its close error is this same failure).
        try:
            real.close()
        except (OSError, ValueError):
            pass
    return failure


def _emit(text: str) -> None:
    """Everything Warden prints on stdout goes through here. A failure is remembered, not raised: the run carries
    on (a receipt is still written, the earned exit code is still worked out) and `main` settles the exit code."""
    if _delivery["failure"] is None:
        _delivery["failure"] = _write_stdout(text)


def main(argv: list[str] | None = None) -> int:
    """Run the command line and return its exit code.

    Delivery. Standard output carries the result, so a result that was not delivered is not an approval. If the reader
    of stdout left (a broken pipe, `warden tagteam DIR | head`) nothing more is printed and the earned exit code stands.
    If stdout is closed or a write fails for any other reason (a full device), one line on stderr says so, no traceback
    is printed, and a run that earned 0 exits 1. A non-zero code is kept as it is."""
    _delivery["failure"] = None
    with isolation.private_bytecode_cache():  # before any seat module is imported
        code = _main(argv)
    failure = _delivery["failure"]
    if failure is None or failure == _READER_LEFT:
        return code
    try:
        print(f"warden: the result could not be delivered on standard output ({failure})"
              + ("; a run that was not delivered is not an ACCEPT, so the exit code is 1" if code == 0 else ""),
              file=sys.stderr)
    except (OSError, ValueError):
        pass  # a closed or broken stderr loses this one line; the exit code is unchanged by it
    return code or 1


def _main(argv: list[str] | None) -> int:
    parser = _JsonParser(prog="warden")
    parser.add_argument("--version", action="version", version=f"warden {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    common = _JsonParser(add_help=False)
    common.add_argument("-v", "--verbose", action="count", default=0,
                        help="log the seams (seats, instruments, verdict) to stderr: -v for INFO, -vv for DEBUG. "
                             "WARDEN_LOG_LEVEL sets the level by name. Stdout stays the JSON run record")

    p_t = sub.add_parser("tagteam", parents=[common],
                         help="loop: observe → propose → apply → re-inspect, until converged; then finish once",
                         epilog=EXIT_CODE_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    p_t.add_argument("path", type=Path)
    p_t.add_argument("--ghost-root", type=Path, default=None)
    p_t.add_argument("--drafter", default=None, metavar="MODULE:FACTORY",
                     help="in the loop: proposes fixes, e.g. drafter.seat:Drafter")
    p_t.add_argument("--claim-commit", default=None, metavar="SHA",
                     help="take the Drafter seat with a real change: the diff of SHA against its first parent, read "
                          "from the target's own git (or from --claim-repo), proposed once and then nothing. The "
                          "target must stand at the parent. Cannot be combined with --drafter")
    p_t.add_argument("--claim-repo", type=Path, default=None, metavar="PATH",
                     help="with --claim-commit: the git repository that holds the commit, when the target does not")
    p_t.add_argument("--claim-diff", type=Path, default=None, metavar="FILE",
                     help="take the Drafter seat with a unified diff applied to the target as it stands, proposed "
                          "once and then nothing; needs --claim-subject and --claim-author. Binary files, renames "
                          "and mode changes are refused, not guessed. Cannot be combined with --drafter")
    p_t.add_argument("--claim-subject", default=None, metavar="TEXT", help="with --claim-diff: what the change is")
    p_t.add_argument("--claim-author", default=None, metavar="TEXT", help="with --claim-diff: who made the change")
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
    p_t.add_argument("--suite-runner", choices=("auto", "pytest", "cargo"), default="auto",
                     help="which tool measures the target's suite: auto picks cargo for a Rust project with no "
                          "Python tests and pytest otherwise (default auto)")
    p_t.add_argument("--seat-timeout", type=_positive_number, default=3600,
                     help="seconds one seat call (Drafter, Finisher, Judge, or building a seat) may take "
                          "before the run stops as ERROR (default 3600)")
    p_t.add_argument("--swizzle-root", type=Path, default=None,
                     help="SWIZZLE checkout; its proofs must hold before anything is ACCEPTed")
    p_t.add_argument("--assay-root", type=Path, default=None,
                     help="ASSAY checkout; with --swizzle-root, Ghost is graded against its answer key first")
    p_t.add_argument("--allow-uncommitted-instruments", action="store_true",
                     help="let an instrument root (--ghost-root, --swizzle-root, --assay-root) run although Warden "
                          "cannot name it: no git commit of its own or no readable version, such as a plain copy of "
                          "the package. Off by default, the root is refused. On, the run is recorded as having used "
                          "one and is never better than ACCEPT_UNVERIFIED. A root inside site-packages or the "
                          "Python installation is always refused")
    p_t.add_argument("--assay-floor", type=_assay_floor, default=CLI_ASSAY_FLOOR,
                     help="the fewest known failure modes Ghost must catch for the Judge to accept "
                          f"(default {CLI_ASSAY_FLOOR}). 0 is the one explicit way to skip: the score "
                          "is recorded, nothing requires it, and the output says so. Below 0 is rejected")
    p_t.add_argument("--from-ghost", type=Path, default=None, help="findings JSON instead of a live scan")
    p_t.add_argument("--stack", type=Path, default=None, metavar="DIR",
                     help="a folder holding checkouts of the whole circuit: ghost_tools, swizzle, assay, "
                          "drafter, judge and burnish (names matched without regard to case). Fills "
                          "--ghost-root, --swizzle-root, --assay-root, --drafter, --judge and --finisher "
                          "with them; an option you give explicitly wins. Every one of the six must be "
                          "there, or the command is a usage error and nothing is run")
    p_t.add_argument("--join", type=Path, action="append", default=[], metavar="PATH",
                     help="a sibling checkout Ghost may read beside the target (repeatable). A boundary the "
                          "target reaches across is then measured instead of reported as a gap that holds the "
                          "result. A joined checkout is read, never imported, and must lie outside the target")
    p_t.add_argument("--stack-manifest", type=Path, default=None, metavar="FILE",
                     help="with --stack: a JSON file naming the circuit's checkouts and the commit each must be "
                          "at ({\"schema\": \"warden-stack/1\", \"contract\": \"1\", \"repos\": {name: commit}}). "
                          "Each commit must be the full 40 characters (lowercase hex), not a prefix. Every named "
                          "checkout is verified against the folder and joined for Ghost, the target "
                          "itself excepted; a missing, mismatched or uncommitted-changes one (modified or "
                          "untracked files; ignored ones do not count) is a usage error and nothing is run. So is "
                          "a stack folder the run uses (instrument root or seat) that the manifest does not name")
    p_t.add_argument("--cns", type=Path, default=None, metavar="DIR",
                     help="with --stack: a checkout of CNS, the hub that holds the circuit's stack manifest at "
                          "contracts/warden-stack.json. The same as --stack-manifest pointed at that file: every "
                          "named checkout is verified at its commit and joined for Ghost. CNS is read, never written")
    p_t.add_argument("--authorize", default=None, metavar="ACTOR")
    p_t.add_argument("--reason", default="")
    p_t.add_argument("--scope", default="documentation",
                     help="documentation: real prose only (.md, .rst, .txt; not requirements, LICENSE, NOTICE "
                          "or CMakeLists.txt). code: anything outside tests, test and build config, CI, "
                          "dependency lists and git hooks")

    p_t.add_argument("--receipt", type=Path, default=None, metavar="FILE",
                     help="after an authorized run, write the horsemen production receipt (JSON) here. It must "
                          "lie outside the target and, if it exists, be a regular file (a pipe, device or folder "
                          "is refused before anything runs). The run's decision and exit code are unchanged")

    p_k = sub.add_parser("keep", parents=[common],
                         help="apply one held unverified result, only with a human grant for its digest")
    p_k.add_argument("path", type=Path)
    p_k.add_argument("--digest", required=True, help="the held_digest a tagteam run reported for this folder")
    p_k.add_argument("--authorize", default=None, metavar="ACTOR",
                     help="the human approving this exact result; without it nothing is applied")
    p_k.add_argument("--reason", default="")

    p_a = sub.add_parser("audit", parents=[common],
                         help="WARDEN_AUDIT.md: Ghost findings under durable IDs (Rules 5, 9)")
    p_a.add_argument("path", type=Path)
    p_a.add_argument("--ghost-root", type=Path, default=None)
    p_a.add_argument("--from-ghost", type=Path, default=None, help="findings JSON instead of a live scan")
    p_a.add_argument("--authorize", default=None, metavar="ACTOR",
                     help="write the file; without it the result is printed and nothing is written")
    p_a.add_argument("--reason", default="")

    try:
        args = parser.parse_args(argv)
    except BrokenPipeError:
        # `--help` or `--version` printed to a reader that had left: nothing was decided, the answer is 0.
        _delivery["failure"] = _READER_LEFT
        return 0
    warden_log.configure(args.verbose)
    logger.debug("warden %s: %s", __version__, args.command)
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
    _emit(json.dumps(payload, indent=2))


#: The contract every run record Warden prints is written against (cns.run in the CNS repository).
CNS_RUN_SCHEMA = "cns.run/1"


def _record(decision: str, reason: str, notes: list[str] | None = None, **extra) -> dict:
    """A run record that ended before the run started: every field cns.run/1 requires, false where the
    run never reached that point. The reason is always text, never null."""
    record = {"schema": CNS_RUN_SCHEMA, "decision": decision, "reason": reason or "", "contract": CONTRACT,
              "converged": False, "finished": False, "put_back": False, "held_digest": "",
              "notes": list(notes or []) + ([reason] if reason else []), "observed": [], "unmeasured": []}
    record.update(extra)
    return record


def _stop(decision: str, reason: str, notes: list[str] | None = None) -> int:
    """End before a run: valid JSON on stdout, the reason on stderr, and the exit code for `decision`."""
    _print_json(_record(decision, reason, notes))
    print(f"warden: {reason}", file=sys.stderr)
    logger.info("stopped before a run: %s (exit %s)", decision, EXIT_CODES[decision])
    return EXIT_CODES[decision]


def _not_regular(path: Path) -> str:
    """What `path` is when it exists and is not a regular file (a link is followed), else "".

    Warden writes a file by writing a temporary name and renaming it into place. Run by a user who may replace
    anything, that rename would swap a device node, a FIFO or a folder the caller named for a regular file. A path
    that does not exist (yet) is fine; one that cannot be looked at is treated as not safe to write."""
    try:
        mode = os.stat(path).st_mode
    except (FileNotFoundError, NotADirectoryError):
        return ""
    except OSError as err:
        return f"something that cannot be examined ({err.strerror or type(err).__name__})"
    if stat.S_ISREG(mode):
        return ""
    for check, name in ((stat.S_ISDIR, "a folder"), (stat.S_ISFIFO, "a named pipe (FIFO)"),
                        (stat.S_ISCHR, "a character device"), (stat.S_ISBLK, "a block device"),
                        (stat.S_ISSOCK, "a socket")):
        if check(mode):
            return name
    return "not a regular file"


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
    if args.receipt is not None:
        receipt_path = Path(args.receipt).expanduser().resolve()
        if receipt_path.is_relative_to(path.resolve()):
            return _stop("USAGE_ERROR", "--receipt names a file inside the target, which would change the folder "
                                        "being governed. Name a file outside it. Nothing was run.")
        kind = _not_regular(receipt_path)
        if kind:
            return _stop("USAGE_ERROR", f"--receipt {str(args.receipt)!r} is {kind}, not a regular file, and Warden "
                                        "replaces the receipt file whole, so it would swap that for a plain file. "
                                        "Name a regular file or a path that does not exist yet. Nothing was run.")
    problem = _claim_problem(args)
    if problem:
        return _stop("USAGE_ERROR", f"usage error: {problem}. Nothing was run.")
    claiming = args.claim_commit is not None or args.claim_diff is not None
    if claiming:
        args.drafter = claimseat.SEAT_SPEC  # the claim takes the Drafter seat, so --stack does not fill it
    seat_paths: list[Path] = []
    if args.stack is not None:
        seat_paths, problem = _resolve_stack(args)
        if problem:
            return _stop("USAGE_ERROR", f"usage error: {problem}. Nothing was run.")
    try:
        findings = load_report(args.from_ghost) if args.from_ghost else None
    except Exception as e:  # noqa: BLE001 - a bad findings file is named, never a raw exception type
        return _stop("ERROR", _findings_problem(args.from_ghost, e))
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
    shadowed = _instrument_inside(args, _governed)
    if shadowed:
        _governed = None
        return _stop("SEAT_NOT_LOADED", shadowed)
    claim_drafter = None
    if claiming:
        try:
            claim_drafter = claimseat.seat_from_args(args, _governed)
        except (claimseat.ClaimError, OSError) as e:
            _governed = None
            return _stop("USAGE_ERROR", f"The claimed change cannot be governed: {e} Nothing was run.")
    joins = [Path(j).expanduser().resolve() for j in (args.join or [])]
    manifest = args.stack_manifest
    if args.cns is not None:
        if manifest is not None:
            _governed = None
            return _stop("USAGE_ERROR", "--cns and --stack-manifest both name a manifest; give one. Nothing was run.")
        manifest = Path(args.cns).expanduser() / CNS_MANIFEST
        if not manifest.is_file():
            _governed = None
            return _stop("USAGE_ERROR", f"--cns {str(args.cns)!r} has no {CNS_MANIFEST}; is it a CNS checkout? "
                                        "Nothing was run.")
    if manifest is not None:
        from_manifest, problem = _joins_from_manifest(manifest, args.stack, _governed,
                                                      getattr(args, "stack_used", None))
        if problem:
            _governed = None
            return _stop("USAGE_ERROR", f"{problem}. Nothing was run.")
        joins += [j for j in from_manifest if j not in joins]
    elif args.stack is not None:
        problem = _stack_use_problem(getattr(args, "stack_used", {}), _governed)
        if problem:
            _governed = None
            return _stop("USAGE_ERROR", f"{problem}. Nothing was run.")
    problem = _join_problem(joins, _governed)
    if problem:
        _governed = None
        return _stop("USAGE_ERROR", f"{problem}. Nothing was run.")
    args.joins = tuple(joins)
    saved_path = list(sys.path)  # put back afterwards so an in-process caller (a test) is not left changed
    try:
        _clean_import_path(_governed)
        # The seats a --stack folder names come from its checkouts, ahead of any other copy on the
        # path. One inside the target is still refused by _check_seat_origin like any other seat.
        for seat_path in reversed(seat_paths):
            sys.path.insert(0, str(seat_path))
        if seat_paths:
            importlib.invalidate_caches()
        try:
            with runstate.interrupts(), runstate.stdout_to_stderr(), \
                    runstate.seat_timer(args.seat_timeout, "A seat while it was being loaded"):
                drafter = claim_drafter if claiming else _load_seat(args.drafter, warnings)
                finisher = _load_seat(args.finisher, warnings)
                judge = _load_seat(args.judge, warnings)
        except ContractMismatch as e:
            return _stop("SEAT_NOT_LOADED", str(e))
        except runstate.Interrupted as sig:
            return _stop("INTERRUPTED", f"Warden received {sig.signal_name} while loading seats. Nothing was run.")
        except runstate.SeatTimedOut as e:
            return _stop("SEAT_NOT_LOADED", f"{e} while it was being loaded. Nothing was run.")
        except Exception as e:  # noqa: BLE001 - a seat that will not load is named, never a traceback
            return _stop("SEAT_NOT_LOADED",
                         f"A seat could not be loaded ({type(e).__name__}: {textio.clip(str(e), 160)}).")
        for w in warnings:
            print(f"warden: warning: {w}", file=sys.stderr)
        return _run_team(args, auth, findings, drafter, finisher, judge, warnings)
    finally:
        _governed = None
        sys.path[:] = saved_path


def _claim_problem(args) -> str:
    """The reason the --claim-* options cannot be used as given, or empty. The claim seat and --drafter both fill
    the Drafter seat, so naming both is a usage error; so is naming the change twice or half."""
    claiming = args.claim_commit is not None or args.claim_diff is not None
    if not claiming:
        if args.claim_repo is not None:
            return "--claim-repo goes with --claim-commit"
        if args.claim_subject is not None or args.claim_author is not None:
            return "--claim-subject and --claim-author go with --claim-diff"
        return ""
    if args.drafter:
        return "--claim-commit or --claim-diff takes the Drafter seat, so --drafter cannot be given as well; give one"
    if args.claim_commit is not None and args.claim_diff is not None:
        return "--claim-commit and --claim-diff both name the change; give one"
    if args.claim_diff is not None:
        if args.claim_repo is not None:
            return "--claim-repo goes with --claim-commit, not with --claim-diff"
        if not (args.claim_subject or "").strip() or not (args.claim_author or "").strip():
            return "--claim-diff needs --claim-subject and --claim-author"
    elif args.claim_subject is not None or args.claim_author is not None:
        return ("--claim-commit reads the subject and author from git; --claim-subject and --claim-author go with "
                "--claim-diff")
    return ""


def _findings_problem(path, err: Exception) -> str:
    """One plain sentence for a --from-ghost file that could not be used: which file and what was wrong."""
    named = f"The findings file {str(path)!r} given to --from-ghost"
    if isinstance(err, json.JSONDecodeError):
        what = f"is not valid JSON ({err.msg}, at line {err.lineno} column {err.colno})"
    elif isinstance(err, UnicodeDecodeError):
        what = "is not valid UTF-8 text"
    elif isinstance(err, OSError):
        what = f"could not be read ({err.strerror or type(err).__name__})"
    elif isinstance(err, ValueError):
        what = "is not a Ghost Tools findings file: " + textio.clip(str(err).split(": ", 1)[-1], 200)
    else:
        what = f"could not be used ({type(err).__name__})"
    return f"{named} {what}. Nothing was run."


def _run_team(args, auth, findings, drafter, finisher, judge, warnings=()) -> int:
    team = TagTeam(ghost_tools_root=args.ghost_root, swizzle_root=args.swizzle_root,
                   assay_root=args.assay_root, assay_floor=args.assay_floor,
                   drafter=drafter, finisher=finisher, judge=judge, max_cycles=args.max_cycles,
                   ghost_timeout=args.ghost_timeout, suite_timeout=args.suite_timeout, suite_runner=args.suite_runner,
                   seat_timeout=args.seat_timeout, joins=getattr(args, "joins", ()),
                   allow_uncommitted_instruments=getattr(args, "allow_uncommitted_instruments", False))
    # A seat that print()s, or writes straight to file descriptor 1, must not corrupt the JSON on stdout.
    with runstate.stdout_to_stderr():
        result = team.run(args.path, authorization=auth, findings=findings)
    payload = {
        "schema": CNS_RUN_SCHEMA,
        "decision": result.decision,
        "converged": result.converged,
        "cycles": [{"number": c.number, "outcome": c.outcome, "observed": c.observed}
                   for c in result.cycles],
        "finished": result.finished,
        "put_back": result.put_back,
        "held_digest": result.held_digest,
        "reason": "" if result.decision == "ACCEPT" else (result.reason or (result.notes[-1] if result.notes else "")),
        "notes": list(result.notes) + list(warnings),
        "observed": [d.identity for d in result.observed],
        "reobserved": [d.identity for d in result.reobserved],
        "contract": CONTRACT,
        "versions": _versions(args, drafter, finisher, judge),
        "swizzle_sound": result.swizzle_sound,
        "allow_uncommitted_instruments": bool(getattr(args, "allow_uncommitted_instruments", False)),
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
    code = 2 if result.swizzle_sound is False else EXIT_CODES.get(result.decision, 1)
    logger.info("tagteam finished: decision=%s exit=%s put_back=%s unmeasured=%s", result.decision, code,
                result.put_back, ",".join(result.unmeasured) or "none")
    if args.receipt is not None:
        _write_receipt(args, auth, result)
    if result.swizzle_sound is False:
        print("warden: SWIZZLE's own proofs do not hold; nothing was written.", file=sys.stderr)
    return code


def _write_receipt(args, auth, result) -> None:
    """Write the horsemen production receipt for a finished run. A failure is said on stderr and never
    changes the run's decision or exit code: the run is over, and the JSON on stdout is the record.

    The file is written under a temporary name and renamed into place, so a reader never sees half a receipt.
    The rename must never swap a special file (checked again here, since the run took time), and an existing
    regular file keeps its permission bits."""
    from .horsemen import receipt_for_run
    target = Path(args.path).resolve()
    out = Path(args.receipt).expanduser()
    tmp = out.with_name(f".{out.name}.{os.getpid()}.part")
    try:
        kind = _not_regular(out)
        if kind:
            raise OSError(f"{str(out)!r} is {kind}, not a regular file, so it was not replaced")
        receipt = receipt_for_run(result=result, target=target, authorization=auth,
                                  baseline_sha=versions.own_commit(target) or "unknown", assay_root=args.assay_root)
        tmp.write_text(json.dumps(receipt.to_dict(), indent=2) + "\n", encoding="utf-8")
        try:
            tmp.chmod(stat.S_IMODE(os.stat(out).st_mode))
        except (FileNotFoundError, NotADirectoryError):
            pass  # a new file: it keeps the mode it was created with
        kind = _not_regular(out)
        if kind:
            raise OSError(f"{str(out)!r} became {kind}, not a regular file, so it was not replaced")
        os.replace(tmp, out)
    except Exception as e:  # noqa: BLE001 - a receipt that cannot be written is said, never a traceback
        with contextlib.suppress(OSError):
            tmp.unlink()
        logger.error("receipt not written: %s: %s", type(e).__name__, textio.clip(str(e), 200))
        print(f"warden: the receipt was not written ({type(e).__name__}: {textio.clip(str(e), 160)}).", file=sys.stderr)
        return
    print(f"warden: receipt written to {out}", file=sys.stderr)


def _versions(args, drafter, finisher, judge) -> dict:
    """What took part in this run: Warden, the instrument checkouts given, and the seats loaded."""
    import warden
    return versions.report(
        warden_module=warden, contract=CONTRACT, version=__version__,
        ghost_root=args.ghost_root, swizzle_root=args.swizzle_root, assay_root=args.assay_root,
        target=Path(args.path).resolve(),
        seats={"drafter": versions.seat(args.drafter, drafter, Path(args.path).resolve()),
               "finisher": versions.seat(args.finisher, finisher, Path(args.path).resolve()),
               "judge": versions.seat(args.judge, judge, Path(args.path).resolve())},
        joins=tuple(getattr(args, "joins", ())))


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
    logger.info("seat loaded: %s (%s, requires_contract=%s)", spec, type(seat).__name__, wanted)
    return seat


def _audit(args) -> int:
    """Print the updated audit; write it only under a human grant."""
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"warden: the target {str(args.path)!r} does not exist or is not a directory.", file=sys.stderr)
        return 2
    findings: Optional[Sequence[Any]]
    try:
        if args.from_ghost:
            findings = load_report(args.from_ghost)
        elif args.ghost_root:
            findings = ghost_scan(root, ghost_tools_root=args.ghost_root)
        else:
            findings = None
    except Exception as e:  # noqa: BLE001 - an audit that could not read its findings must not look clean
        print(f"warden: the findings could not be read ({type(e).__name__}: {textio.clip(str(e), 160)}). "
              "Nothing was printed or written.", file=sys.stderr)
        return 2
    blind = getattr(findings, "blind", None)
    if blind:
        print(f"warden: {blind}. Nothing was printed or written.", file=sys.stderr)
        return 2
    gaps = getattr(findings, "gaps", None)
    if gaps:
        print("warden: warning: Ghost's scan had gaps (" + "; ".join(gaps[:3]) + "), so a row marked "
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
        _emit(updated)
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
    kind = _not_regular(path)
    if kind:
        print(f"warden: {path} is {kind}, not a regular file, so the audit will not be written into it. "
              "Nothing was written.", file=sys.stderr)
        return 2
    try:
        textio.write_text(path, updated)
    except OSError as e:
        print(f"warden: {path} could not be written ({type(e).__name__}).", file=sys.stderr)
        return 2
    _emit(f"wrote {path} (authorized by {auth.actor})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
