"""The loop: Ghost sees, Drafter proposes, Warden decides and applies, SWIZZLE checks.

    calibrate (SWIZZLE proves its own instrument)
    repeat, up to max_cycles:
        observe (Ghost) -> Drafter proposes -> authorize (human)
        -> suite before -> apply -> suite after (put back on failure)
        -> Ghost re-inspects
      until the Drafter has nothing left to propose
    SWIZZLE proofs again
    hand off ONCE to the Finisher: beautified code and the final README,
      applied by Warden under the same gate and put back if the suite
      breaks or Ghost finds anything new

Warden is the only writer and the only one who says the loop is done. The
Drafter cannot declare itself finished; it can only run out of proposals, and
Warden checks that Ghost agrees before calling it converged.

This module refuses three self-certifying loops:

    Warden says Warden is good.
    Ghost Tools finds its own work correct merely because it produced it.
    SWIZZLE trusts the transformation framework without independent challenge.
"""

from __future__ import annotations

import hashlib
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence

from . import gitstate, held, runstate, textio
from .authorization import Authorization, Unauthorized, is_stack_actor
from .deletion import commented_variant, is_deletion, keep_variant, stamp_now
from .ghost import GhostCrashed, GhostRefused, _clean as _plain, defects_from_ghost, scan as ghost_scan
from .guard import (FORBIDDEN_DIRS, SeatBrokeCharter, Snapshot, _RESTORE_LIMIT, is_protected,
                    is_test_code, violation, watch)
from .models import Defect, FileEdit, Transformation, TransformationStatus, safe_id
from .roles import Evidence, Facts, Finisher, Drafter, Judge, Verdict
from .suite import DEFAULT_TIMEOUT as DEFAULT_SUITE_TIMEOUT, SuiteRun, preserved, run_suite
from .swizzle import assay_score, governor_attacks, swizzle_proofs_hold

DEFAULT_MAX_CYCLES = 10
DEFAULT_GHOST_TIMEOUT = 600
#: The Ghost detector that reports baseline entries matching nothing in the scan.
STALE_BASELINE_DETECTOR = "stale_baseline"
#: Seconds one seat call (propose, finish, decide, or building the seat) may take before the run stops.
DEFAULT_SEAT_TIMEOUT = 3600
#: Proposals declined without a write (scope, protected file, failed keep test) do not use up a cycle, but
#: this many in one run end it, so a Drafter that keeps offering new declined proposals cannot loop forever.
DEFAULT_MAX_DECLINED = 50

#: Every decision this module can produce. The CLI maps each one to an exit code and
#: treats anything else as a failure, never as success.
DECISIONS = ("ACCEPT", "ACCEPT_UNVERIFIED", "REJECT", "JUDGE_REJECTED", "NOT_CONVERGED",
             "FINISH_REJECTED", "REFUSED", "INCONCLUSIVE", "ERROR", "INTERRUPTED")


PUT_BACK_NOTE = "The tree was put back as it was found because the run did not finish accepted."
LOOP_PUT_BACK_NOTE = ("The loop's own changes were put back as well: a run that does not end accepted leaves "
                      "the whole tree as it was found, so nothing from the converged loop stands.")
NOT_GIT_NOTE = ("The folder is not inside a git repository, so Warden cannot see whether it holds uncommitted "
                "work; the snapshot taken at the start is the only way back.")
SOURCE_CHANGED_NOTE = "the test suite changed source files, so its result cannot be trusted"
#: Only a full ACCEPT lets changes stand. ACCEPT_UNVERIFIED is saved as a held result and put back
#: until a human approves that exact result (see held.py).
_ENDS_ACCEPTED = {"ACCEPT"}
_JUDGE_LABELS = ("ACCEPT", "REJECT", "INSUFFICIENT")


#: At most this many Drafter "skipped" lines are kept in the output.
MAX_SKIPPED_LINES = 20


class GhostUnavailable(RuntimeError):
    """Ghost could not be run or its output could not be read. UNKNOWN, not zero findings."""


class SuiteChangedSource(RuntimeError):
    """Running the target's suite changed its source files."""


class WrongAnswer(RuntimeError):
    """A seat returned the wrong kind of thing."""

    def __init__(self, seat: str, got: object, wanted: str, message: Optional[str] = None) -> None:
        super().__init__(message or f"{seat} returned {type(got).__name__} instead of {wanted}")
        self.seat = seat


@dataclass
class Cycle:
    """One turn of the loop: what was proposed and whether it stood."""

    number: int
    observed: int
    proposal: Optional[Transformation]
    applied: bool
    outcome: str  # APPLIED / PUT_BACK / NOTHING_TO_PROPOSE / REFUSED / SUITE_RED
    suite_before: Optional[SuiteRun] = None
    suite_after: Optional[SuiteRun] = None


@dataclass
class TagTeamResult:
    target: str
    baseline: str
    observed: tuple[Defect, ...]
    reobserved: tuple[Defect, ...]
    cycles: tuple[Cycle, ...]
    converged: bool
    #: ACCEPT / ACCEPT_UNVERIFIED / FINISH_REJECTED / JUDGE_REJECTED / NOT_CONVERGED / REJECT /
    #: REFUSED / INCONCLUSIVE / ERROR (a seat failed or misbehaved)
    decision: str
    notes: tuple[str, ...]
    finish: Optional[Transformation] = None
    finished: bool = False
    #: True: SWIZZLE's proofs held. False: they did not. None: not configured.
    swizzle_sound: Optional[bool] = None
    #: Checks that did not run. A non-empty value turns ACCEPT into ACCEPT_UNVERIFIED.
    unmeasured: tuple[str, ...] = ()
    #: What the Judge said, when one was seated.
    verdict: Optional[Verdict] = None
    #: What new Ghost said about its last scan: status, file counts, real gaps, declined checks.
    #: None when Ghost was not scanned in this run or is the old kind that says none of this.
    ghost_scan: Optional[dict] = None
    #: Why the Drafter left findings alone, as short sanitized lines (capped). Information, not a gap.
    drafter_skipped: tuple[str, ...] = ()
    #: True when edits had been made and the whole tree was restored because the run did not end accepted.
    put_back: bool = False

    #: For an ACCEPT_UNVERIFIED run that was put back: the digest of its saved final state, which a
    #: human can approve with a grant for `keep_unverified` on this folder (see held.py).
    held_digest: Optional[str] = None
    #: One plain sentence saying why the run ended as it did (the same sentence as the last note
    #: before any put-back text). Empty for a plain ACCEPT.
    reason: str = ""
    #: Information that is not a gap and changes no decision, such as `ghost_version_unverified`.
    informational: tuple[str, ...] = ()
    #: Ghost's baseline report at the first and the last scan ({"before": {path, suppressed}|None,
    #: "after": ...}), the same values handed to the Judge. None: no scan reported one.
    ghost_baseline: Optional[dict] = None

    @property
    def suite_before(self) -> Optional[SuiteRun]:
        """The target's suite before the first cycle that measured it."""
        return next((c.suite_before for c in self.cycles if c.suite_before is not None), None)

    @property
    def suite_after(self) -> Optional[SuiteRun]:
        """The suite after the last cycle that measured it."""
        return next((c.suite_after for c in reversed(self.cycles) if c.suite_after is not None), None)

    @property
    def applied(self) -> bool:
        return (any(c.applied for c in self.cycles) or self.finished) and not self.put_back


class TagTeam:
    def __init__(
        self,
        *,
        ghost_tools_root: Optional[Path] = None,
        swizzle_root: Optional[Path] = None,
        assay_root: Optional[Path] = None,
        assay_floor: int = 0,
        drafter: Optional[Drafter] = None,
        finisher: Optional[Finisher] = None,
        judge: Optional[Judge] = None,
        max_cycles: int = DEFAULT_MAX_CYCLES,
        run_tests: bool = True,
        ghost_timeout: float = DEFAULT_GHOST_TIMEOUT,
        suite_timeout: float = DEFAULT_SUITE_TIMEOUT,
        seat_timeout: Optional[float] = DEFAULT_SEAT_TIMEOUT,
        max_declined: int = DEFAULT_MAX_DECLINED,
    ) -> None:
        self.ghost_tools_root = ghost_tools_root
        self.swizzle_root = swizzle_root
        #: ASSAY checkout. With SWIZZLE, Ghost is graded against its answer key before anything is written.
        self.assay_root = assay_root
        #: The fewest known failure modes Ghost must catch for the Judge to accept.
        self.assay_floor = assay_floor
        self.drafter = drafter
        self.finisher = finisher
        self.judge = judge
        self.max_cycles = max_cycles
        #: Rule 7. Off only for callers that measure the suite some other way;
        #: the notes say so when it is off.
        self.run_tests = run_tests
        #: Seconds one Ghost scan may take. A scan that takes longer counts as Ghost being unavailable.
        self.ghost_timeout = ghost_timeout
        #: Seconds the target's suite may take per run; longer counts as the suite not running.
        self.suite_timeout = suite_timeout
        #: Seconds one seat call may take. None or 0 turns the limit off.
        self.seat_timeout = seat_timeout
        self.max_declined = max_declined

    def run(
        self,
        target: Path,
        *,
        authorization: Optional[Authorization] = None,
        findings: Optional[Sequence[dict]] = None,
        python: str = "",
    ) -> TagTeamResult:
        target = Path(target).resolve()
        _refuse_self_authorization(target, authorization)
        self._notes: list[str] = []
        self._trail: list[Cycle] = []
        self._assay_state: Optional[bool] = None
        self._assay: dict = {}
        self._start: Optional[Snapshot] = None
        self._seat = "Warden"
        self._baseline_fp = ""
        #: Instruments found to be down or unreadable during this run.
        self._down: set[str] = set()
        self._suite_ran = False
        self._sound: Optional[bool] = None
        #: Real gaps in the latest Ghost scan (see ghost._gaps), and the summary shown in the output.
        self._ghost_gaps: list[str] = []
        self._stale_baseline: int = 0
        self._ghost_info: Optional[dict] = None
        #: Ghost's baseline report ({path, suppressed}) from the first scan and the latest scan, or None.
        self._baseline_first: Optional[dict] = None
        self._baseline_last: Optional[dict] = None
        self._baseline_seen = False
        self._info: list[str] = []
        self._skipped: list[str] = []
        self._skipped_more = 0
        lock = runstate.TargetLock(target)
        try:
            held = lock.acquire()
        except runstate.StateUnavailable as exc:
            return self._early(target, "INCONCLUSIVE", f"Warden could not set up its lock for this target ({exc}). "
                                                       "Nothing was changed.")
        if not held:
            return self._early(target, "INCONCLUSIVE", runstate.BUSY_NOTE + ". Nothing was changed.")
        try:
            with runstate.interrupts():
                return self._guarded(target, authorization, findings, python or sys.executable)
        finally:
            lock.release()

    def _early(self, target: Path, decision: str, why: str) -> TagTeamResult:
        """A run that ends before it starts: nothing was read from the target, nothing written."""
        return TagTeamResult(
            target=str(target), baseline="", observed=(), reobserved=(), cycles=(), converged=False,
            decision=decision, notes=tuple(self._notes + [why]), unmeasured=self._unmeasured(None, never_ran=True),
            reason=why, informational=tuple(self._info))

    def _guarded(self, target: Path, authorization, findings, python: str) -> TagTeamResult:
        """Everything after the lock is held. Whatever happens, the tree is put back unless the run ends accepted."""
        try:
            if authorization is not None and authorization.granted:
                # Only a human grant may touch the tree, and putting back an interrupted keep test is touching it.
                self._notes.extend(runstate.recover(target))
            elif runstate.has_journal(target):
                self._notes.append(runstate.PENDING_NOTE)
            state = gitstate.tree_state(target)
            if state.kind == "dirty":
                return self._early(target, "REFUSED",
                                   f"The folder has uncommitted changes ({state.detail}). Commit or stash them, then run "
                                   "again, so everything Warden changes can be told apart from your own work. "
                                   "Nothing was written.")
            if state.kind == "unknown":
                return self._early(target, "REFUSED", f"{state.detail[0].upper()}{state.detail[1:]}. Nothing was written.")
            if state.kind == "not_git":
                self._notes.append(NOT_GIT_NOTE)
            # Always taken: a run that does not end accepted puts the tree back to this.
            self._start = Snapshot(target)
            self._baseline_fp = _fingerprint(target)
            result = self._run(target, authorization, findings, python)
        except runstate.Interrupted as sig:
            result = self._failed(target, sig)
        except Exception as err:  # noqa: BLE001 - any failure ends the run with the tree put back
            result = self._failed(target, err)
        except runstate.SeatTimedOut as err:
            result = self._failed(target, err)
        except KeyboardInterrupt:
            self._settle(target, self._failed(target, RuntimeError("interrupted")))
            raise
        return self._settle(target, result)

    def _failed(self, target: Path, err: BaseException) -> TagTeamResult:
        """The result for a run that stopped on an error. Never carries a traceback."""
        if isinstance(err, runstate.Interrupted):
            decision, said = "INTERRUPTED", f"Warden received {err.signal_name} and stopped."
        elif isinstance(err, SeatBrokeCharter):
            decision, said = "REJECT", str(err)
        elif isinstance(err, GhostUnavailable):
            decision, said = "INCONCLUSIVE", str(err)
            self._down.add("ghost")
        elif isinstance(err, SuiteChangedSource):
            decision, said = "INCONCLUSIVE", f"The run stopped: {SOURCE_CHANGED_NOTE}."
            self._down.add("suite")
        elif isinstance(err, runstate.SeatTimedOut):
            decision = "ERROR"
            said = f"{err}. The run was stopped and nothing was approved."
        else:
            seat = getattr(err, "seat", None) or self._seat
            if isinstance(err, WrongAnswer):
                said = f"{seat} gave a wrong kind of answer ({type(err).__name__}): {err}. The run was stopped."
            else:
                said = (f"{seat} failed with {type(err).__name__}. The run was stopped and nothing "
                        "was approved.")
            decision = "ERROR"
        return TagTeamResult(
            target=str(target), baseline="", observed=(), reobserved=(),
            cycles=tuple(self._trail), converged=False, decision=decision,
            notes=tuple(self._notes + [said]), unmeasured=self._unmeasured(self._sound, never_ran=True),
            reason=said, ghost_scan=self._ghost_info, drafter_skipped=self._skipped_lines(),
            ghost_baseline=self._baseline_report(),
            informational=tuple(self._info))

    def _settle(self, target: Path, result: TagTeamResult) -> TagTeamResult:
        """A run that does not end accepted leaves the tree as it was found. An ACCEPT_UNVERIFIED run
        is also put back, but its final state is saved first as a held result a human can approve."""
        start = self._start
        if result.decision in _ENDS_ACCEPTED or start is None:
            return result
        try:
            changed = start.changes()
        except OSError:
            changed = ["unknown"]
        if not changed:
            return result
        if not start.restorable:
            warning = ("WARNING: the tree is too large to restore automatically, so this run's changes "
                       "were NOT put back and are still on disk.")
            return replace(result, notes=result.notes[:-1] + (result.notes[-1] + " Changes were NOT undone.",
                                                              warning) if result.notes else (warning,))
        digest = None
        hold_failure = None
        if result.decision == "ACCEPT_UNVERIFIED":
            try:
                digest = held.hold(target, Snapshot(target), self._baseline_fp, result.decision,
                                   result.reason, result.unmeasured)
            except OSError as exc:
                # Still attempt the restore below: unverified changes must not stand because a save failed.
                hold_failure = type(exc).__name__
        try:
            start.restore()
            left = start.changes()
        except OSError as exc:
            left = [f"could not restore ({type(exc).__name__})"]
        if hold_failure or left:
            problems = []
            if hold_failure:
                problems.append(f"the unverified result could not be saved ({hold_failure})")
            if left:
                problems.append("putting the tree back did not fully work; still different: "
                                + ", ".join(left[:5]))
            message = ("The run is an ERROR and nothing was approved: " + "; ".join(problems) + ".")
            return replace(result, decision="ERROR", reason=message, held_digest=None,
                           put_back=not left,
                           notes=result.notes + ("WARNING: " + message,))
        extra = (LOOP_PUT_BACK_NOTE,) if result.decision == "FINISH_REJECTED" and any(
            c.applied for c in result.cycles) else ()
        if result.decision == "ACCEPT_UNVERIFIED":
            if digest is None:
                extra = extra + ("This unverified result is too large to save, so it was put back and cannot "
                                 "be kept later.",)
            else:
                extra = extra + (f"The unverified result was saved as {digest}. It stands only if a person "
                                 "grants keep_unverified for that digest on this folder.",)
        return replace(result, notes=result.notes + (PUT_BACK_NOTE,) + extra, put_back=True,
                       held_digest=digest)

    @contextmanager
    def _seated(self, who: str):
        """Name the seat in control, so an unexpected error can say whose it was. A seat that does not
        answer within `seat_timeout` seconds stops the run."""
        self._seat = who
        with runstate.seat_timer(self.seat_timeout, who):
            yield
        self._seat = "Warden"  # not reached on an error, so the handler can still name the seat

    def _judge(self, target, authorization, cycles, first, current, finish, finished, sound,
               declined, python, notes, start):
        """Hand the evidence to the Judge. Only the Judge can turn a run into ACCEPT.

        REJECT puts the whole tree back as it was found. INSUFFICIENT (the Judge cannot decide) leaves
        the changes held and unjudged. A Judge that fails or answers wrongly ends the run as ERROR.
        """
        edits = [(e.path, e.kind) for c in cycles if c.applied and c.proposal for e in c.proposal.edits]
        if finished and finish is not None:
            edits += [(e.path, e.kind) for e in finish.edits]
        attacks = None
        if self.swizzle_root is not None and sound is True:
            import warden
            attacks = governor_attacks(swizzle_root=self.swizzle_root,
                                       warden_root=Path(warden.__file__).resolve().parents[1], python=python,
                                       note=notes)
            notes.append("SWIZZLE attacks on the governor: "
                         + ("not run" if attacks is None else
                            f"{sum(a['status'] == 'violated' for a in attacks)} of {len(attacks)} violated"))
        suite_after = self._suite(target, python, notes, "final state, for the Judge")  # may stop the run
        first_suite = next((c.suite_before for c in cycles if c.suite_before is not None), None)
        ghost = self.ghost_tools_root is not None
        evidence = Evidence(
            target=str(target), scope=authorization.scope if authorization else "",
            cycles=tuple((c.number, c.outcome) for c in cycles), changed=tuple(edits),
            judging_files_touched=tuple(sorted({p for p, _ in edits if is_protected(p)})),
            suite_before=first_suite if first_suite is not None else suite_after, suite_after=suite_after,
            ghost_before=tuple(sorted(d.identity for d in first)) if ghost else None,
            ghost_after=tuple(sorted(d.identity for d in current)) if ghost else None,
            declined=tuple(sorted(declined)), swizzle_proofs=sound, attacks=attacks,
            unmeasured=self._unmeasured(sound), notes=tuple(notes),
            assay=({**self._assay, "floor": self.assay_floor} if self._assay_state else None),
            ghost_baseline_before=self._baseline_first, ghost_baseline_after=self._baseline_last)
        # A Judge that raises, or answers with the wrong kind of thing or an unknown label, has approved
        # nothing: the error ends the run (ERROR) and the whole tree is put back like any other non-accept.
        with self._seated("The Judge"), watch(target, "The Judge"):
            verdict = self.judge.decide(evidence)
        reasons = getattr(verdict, "reasons", None)
        if not isinstance(getattr(verdict, "decision", None), str) or not isinstance(reasons, (tuple, list)) \
                or not all(isinstance(r, str) for r in reasons):
            raise WrongAnswer("The Judge", verdict, "a verdict")
        if verdict.decision not in _JUDGE_LABELS:
            raise WrongAnswer("The Judge", verdict, "a verdict", message=(
                f"The Judge returned the decision {_plain(verdict.decision, 30)!r}, which is not one of "
                f"{', '.join(_JUDGE_LABELS)}"))
        said = "; ".join(reasons) or "no reasons given"
        self._check_verdict_shape(verdict, notes)
        if verdict.decision == "ACCEPT":
            return "ACCEPT", verdict, f" Judge: ACCEPT ({said})."
        if verdict.decision == "REJECT":
            # The tree is put back by the settle step that every non-accepted run goes through.
            return "JUDGE_REJECTED", verdict, f" Judge: REJECT ({said})."
        return "ACCEPT_UNVERIFIED", verdict, f" Judge: INSUFFICIENT ({said}). The changes are held, unjudged."

    @staticmethod
    def _check_verdict_shape(verdict, notes: list[str]) -> None:
        """Say so (never crash) when a Judge's verdict names no judge or carries fields Warden does not know."""
        if not isinstance(getattr(verdict, "judge", None), str) or not verdict.judge.strip():
            notes.append("The Judge's verdict did not name the judge, so it is recorded as unnamed.")
        known = {"decision", "reasons", "judge"}
        try:
            extra = sorted(set(vars(verdict)) - known)
        except TypeError:
            extra = []
        if extra:
            notes.append(f"The Judge's verdict carried fields Warden does not know ({', '.join(map(str, extra))[:80]}); "
                         "they were ignored.")

    def _unmeasured(self, sound: Optional[bool], never_ran: bool = False, suite_pending: bool = False) -> tuple[str, ...]:
        """Checks that did not run or could not be read. The suite counts as unmeasured whenever it was
        never run (a run that changed nothing, or ended early, measured nothing about behavior), unless
        `suite_pending`: the Judge's final-state run is about to measure it. `never_ran` is kept for callers
        that pass it; it no longer changes the answer."""
        out = []
        if self._assay_state is not True:
            out.append("assay")
        if self.ghost_tools_root is None or "ghost" in self._down:
            out.append("ghost")
        elif self._ghost_gaps:
            # Ghost ran but could not look at everything it should have. Not "ghost" (down), but not whole either.
            out.append("ghost_partial")
        if self.swizzle_root is None or sound is False or "swizzle" in self._down:
            out.append("swizzle")
        if not self.run_tests or "suite" in self._down or (not self._suite_ran and not suite_pending):
            out.append("suite")
        if self.judge is None:
            out.append("judge")
        return tuple(out)

    def _tell_scope(self, target: Path, authorization: Optional[Authorization], notes: list[str]) -> None:
        """Tell the maker seats the grant's scope, when they keep one (see `warden.roles`).

        The grant is the authority: a seat built with its own idea of the scope is corrected, so
        it cannot propose code under a documentation grant and have every proposal declined. A
        seat that will not take it is noted and asked as before; the grant still checks its work.

        Setting the attribute runs the seat's code (a property can do anything), so it runs under
        the same guard as every other seat call: the seat timer, and the watch that puts back and
        refuses anything the seat wrote to the tree. Red-teamed 2026-10-14: the first version ran it
        unguarded, before Ghost's first look, so a seat could have planted a file nothing would
        later count as new.
        """
        scope = authorization.scope if authorization is not None else ""
        if not scope:
            return
        for who, seat in (("Drafter", self.drafter), ("Finisher", self.finisher)):
            if seat is None:
                continue
            with self._seated(f"The {who}"), watch(target, f"The {who}"):
                try:
                    if not hasattr(seat, "scope"):
                        continue
                    seat.scope = scope
                except Exception as err:  # noqa: BLE001 - a seat that keeps its own scope is not an error
                    notes.append(f"The {who} keeps a scope of its own and would not take the grant's "
                                 f"({scope}; {type(err).__name__}); its proposals are checked against the "
                                 "grant as usual.")

    def _run(self, target: Path, authorization: Optional[Authorization],
             findings: Optional[Sequence[dict]], python: str) -> TagTeamResult:
        notes = self._notes
        self._tell_scope(target, authorization, notes)
        sound = self._calibrate(python, notes)
        self._grade(python, notes)
        observed = self._observe(target, findings, python, notes)
        first = observed
        base0 = _fingerprint(target)
        start = self._start
        declined: set[str] = set()

        def stop(decision: str, why: str, cycles=(), converged=False, current=None,
                 finish=None, finished=False, unsound=False) -> TagTeamResult:
            shown_sound = False if unsound else sound
            candidate = decision == "ACCEPT"
            will_judge = candidate and self.judge is not None
            missing = self._unmeasured(shown_sound, never_ran=decision in {"INCONCLUSIVE", "REFUSED"},
                                       suite_pending=will_judge and self.run_tests)
            gaps = tuple(m for m in missing if m != "judge")
            if candidate and missing:
                decision = "ACCEPT_UNVERIFIED"
                why += f" Not measured: {', '.join(missing)}. Nothing here says those checks would have passed."
            verdict = None
            reobserved = observed if current is None else current
            if will_judge:
                judged, verdict, extra = self._judge(
                    target, authorization, tuple(cycles), first, reobserved, finish, finished,
                    sound, declined, python, notes, start)
                why += extra
                # Whatever the Judge says, a run with gaps in its measurements is not a plain ACCEPT.
                decision = "ACCEPT_UNVERIFIED" if judged == "ACCEPT" and gaps else judged
            return TagTeamResult(
                target=str(target), baseline=base0, observed=first,
                reobserved=reobserved, cycles=tuple(cycles),
                converged=converged, decision=decision, notes=tuple(notes + [why]),
                finish=finish, finished=finished, swizzle_sound=shown_sound, unmeasured=missing,
                verdict=verdict, reason=why.strip(), ghost_scan=self._ghost_info,
                ghost_baseline=self._baseline_report(),
                drafter_skipped=self._skipped_lines(), informational=tuple(self._info))

        if self._stale_baseline:
            return stop("REJECT", f"Ghost's baseline has {self._stale_baseline} entr"
                        f"{'y' if self._stale_baseline == 1 else 'ies'} that matched nothing in this scan. "
                        "A baseline must be re-checked on every run: remove or regenerate the stale entries first.")
        if self.drafter is None:
            return stop("INCONCLUSIVE", "No drafter. Tag team observed only; nothing can be proposed.")
        if authorization is None or not authorization.granted:
            # Show what would be proposed, change nothing.
            with self._seated("The Drafter"), watch(target, "The Drafter"):
                proposal = _expect(self.drafter.propose(target, observed, _fingerprint(target)), "The Drafter")
            self._collect_skipped()
            cycle = Cycle(1, len(observed), proposal, False, "REFUSED")
            return stop("REFUSED", "Human authorization missing. Proposal stands. No write.",
                        cycles=[cycle])
        if sound is False:
            return stop("INCONCLUSIVE", "SWIZZLE's own proofs do not hold; nothing was written.")
        if self._assay_state is False:
            return stop("INCONCLUSIVE", "ASSAY's answer key could not be used to grade Ghost; nothing was written.")

        if start is not None and not start.restorable:
            return stop("INCONCLUSIVE", f"The folder holds more than {_RESTORE_LIMIT // (1024 * 1024)} MB, which is "
                        "more than Warden can put back, so a change that failed could not be undone. "
                        "Nothing was written.")

        cycles: list[Cycle] = self._trail
        converged = False
        seen: set[str] = set()
        out_of_scope: set[str] = set()
        attempts = 0
        declined_count = 0
        #: Findings whose removal failed a test (`declined`) are not offered to the Drafter again.
        #: Only a proposal that reaches the applier uses up one of `max_cycles`; a declined one does not,
        #: but `max_declined` of them end the run.
        while attempts < self.max_cycles:
            number = len(cycles) + 1
            if declined_count >= self.max_declined:
                return stop("NOT_CONVERGED", f"Cycle {number}: {declined_count} proposals were declined without a "
                            "write and the Drafter kept offering more. Stopped.", cycles)
            baseline = _fingerprint(target)
            offered = tuple(d for d in observed if d.identity not in declined)
            with self._seated("The Drafter"), watch(target, "The Drafter"):
                proposal = _expect(self.drafter.propose(target, offered, baseline), "The Drafter")
            self._collect_skipped()
            if proposal is None or not proposal.edits:
                cycles.append(Cycle(number, len(observed), None, False, "NOTHING_TO_PROPOSE"))
                converged = True
                break
            if _changes_nothing(target, proposal):
                cycles.append(Cycle(number, len(observed), None, False, "NOTHING_TO_PROPOSE"))
                notes.append(f"Cycle {number}: the Drafter's proposal would change nothing, so it was dropped "
                             "and counted as nothing to propose.")
                converged = True
                break
            key = _edits_key(proposal)
            bad = violation(target, proposal, authorization)
            if bad:
                kind, why = bad
                if kind == "scope" and not proposal.known_defects:
                    # Out of the grant's scope and citing no defect: nothing was written, so this is a
                    # declined proposal. The same one again ends the run.
                    if key in out_of_scope:
                        cycles.append(Cycle(number, len(observed), proposal, False, "REFUSED"))
                        return stop("NOT_CONVERGED", f"Cycle {number}: the Drafter repeated a proposal that was "
                                    "already declined as out of scope. Stopped.", cycles)
                    out_of_scope.add(key)
                    cycles.append(Cycle(number, len(observed), proposal, False, "DECLINED"))
                    declined_count += 1
                    notes.append(f"Cycle {number}: change declined, nothing was written. {why}.")
                    continue
                if kind == "escape" or not proposal.known_defects:
                    cycles.append(Cycle(number, len(observed), proposal, False, "REFUSED"))
                    return stop("REJECT", f"Cycle {number}: {why}. Nothing was written.", cycles)
                declined.update(d.identity for d in proposal.known_defects)
                cycles.append(Cycle(number, len(observed), proposal, False, "DECLINED"))
                declined_count += 1
                notes.append(f"Cycle {number}: change declined. {why}.")
                continue
            removes = is_deletion(target, proposal)
            if removes:
                scope, why = self._keep_test(target, proposal, observed, python, notes, number)
                if scope == "systemic":
                    cycles.append(Cycle(number, len(observed), proposal, False, "REFUSED"))
                    return stop("REJECT", f"Cycle {number}: the removal was not applied. {why}", cycles)
                original = proposal
                proposal = None if scope else _commented(target, proposal)
                if proposal is None:
                    why = why or "The removed code could not be commented out precisely."
                    declined.update(d.identity for d in original.known_defects)
                    cycles.append(Cycle(number, len(observed), original, False, "DECLINED"))
                    declined_count += 1
                    notes.append(f"Cycle {number}: removal declined, code left as it is. {why}")
                    continue
                key = _edits_key(proposal)
            if key in seen:
                cycles.append(Cycle(number, len(observed), proposal, False, "REFUSED"))
                return stop("NOT_CONVERGED", f"Cycle {number}: the Drafter repeated an earlier "
                            "proposal, so the loop is going in circles. Stopped.", cycles)
            seen.add(key)
            attempts += 1
            cycle = self._apply(target, proposal, authorization, python, notes, number,
                                len(observed))
            cycles.append(cycle)
            if cycle.outcome == "SUITE_RED":
                return stop("INCONCLUSIVE", f"Cycle {number}: the suite is not green; nothing was written.", cycles)
            if cycle.outcome != "APPLIED":
                return stop("REJECT", f"Cycle {number}: {cycle.outcome}. The change was put back; "
                            "the loop stopped.", cycles)
            after = self._reinspect(target, observed, python, notes)
            new = {d.ghost_id for d in after if d.ghost_id} - {d.ghost_id for d in observed if d.ghost_id}
            if removes and new:
                _restore(target, cycle.restore)
                proposal.status = TransformationStatus.REJECTED
                cycle.applied, cycle.outcome = False, "DECLINED"
                declined_count += 1
                declined.update(d.identity for d in proposal.known_defects)
                notes.append(f"Cycle {number}: comment-out test failed. The change produced new Ghost "
                             f"finding(s) {sorted(map(safe_id, new))}; it was put back and the code left as it is.")
                continue
            observed = after
        if not converged:
            return stop("NOT_CONVERGED", f"No convergence in {self.max_cycles} cycles.", cycles)  # attempts, not declined proposals
        if declined:
            notes.append(f"Removals declined and left in place: {sorted(map(safe_id, declined))}.")
        if observed and self.ghost_tools_root is not None:
            notes.append(f"Drafter is out of proposals but Ghost still reports {len(observed)} finding(s). "
                         "Converged means no proposals left, not zero findings.")

        end_sound = self._calibrate(python, notes)
        if end_sound is False:
            return stop("INCONCLUSIVE", "SWIZZLE's proofs failed after the loop; finishing was not attempted.",
                        cycles, converged=True, unsound=True)
        if self.finisher is None:
            return stop("ACCEPT", "Loop converged. No finisher configured.", cycles, converged=True)

        facts = Facts(suite=self._suite(target, python, notes, "converged"),
                      remaining=observed, cycles=len([c for c in cycles if c.applied]),
                      unmeasured=self._unmeasured(end_sound))
        with self._seated("The Finisher"), watch(target, "The Finisher"):
            finish = _expect(self.finisher.finish(target, _fingerprint(target), facts), "The Finisher")
        if finish is None or not finish.edits:
            return stop("ACCEPT", "Loop converged. The Finisher had nothing to finish.",
                        cycles, converged=True)
        bad = violation(target, finish, authorization)
        if bad:
            finish.status = TransformationStatus.REJECTED
            return stop("FINISH_REJECTED", f"Finishing: {bad[1]}. The finishing change was not applied.",
                        cycles, converged=True, finish=finish)
        done = self._apply(target, finish, authorization, python, notes, 0, len(observed))
        if done.outcome != "APPLIED":
            return stop("FINISH_REJECTED", f"Finishing: {done.outcome}. The finishing change was put back.",
                        cycles, converged=True, finish=finish)
        after = self._reinspect(target, observed, python, notes)
        new = {d.ghost_id for d in after if d.ghost_id} - {d.ghost_id for d in observed if d.ghost_id}
        if new:
            _restore(target, done.restore)
            finish.status = TransformationStatus.REJECTED
            return stop("FINISH_REJECTED", f"Finishing introduced new Ghost finding(s) {sorted(map(safe_id, new))}. "
                        "The finishing change was put back.", cycles, converged=True,
                        current=observed, finish=finish)
        return stop("ACCEPT", "Loop converged and the finishing change stands.", cycles,
                    converged=True, current=after, finish=finish, finished=True)

    # -- steps ------------------------------------------------------------

    def _keep_test(self, target: Path, proposal: Transformation, observed: tuple[Defect, ...],
                   python: str, notes: list[str], number: int) -> tuple[str, str]:
        """"What happens if I don't delete it?" Returns ("", "") on pass, else (scope, reason): "systemic" stops the loop, "candidate" declines this one removal.

        The code is kept but made to raise when it runs. If the suite then fails,
        something executes it. Files are restored whatever happens.
        """
        if self.ghost_tools_root is None:
            return "systemic", "Ghost is not configured, so the removal cannot be validated."
        if not self.run_tests:
            return "systemic", "The suite is not being run, so the removal cannot be validated."
        if self._calibrate(python, notes) is False:
            return "systemic", "SWIZZLE's proofs do not hold."
        wanted = {d.ghost_id for d in proposal.known_defects if d.ghost_id}
        if not wanted:
            return "candidate", "The removal cites no Ghost finding to validate it against."
        if not wanted <= {d.ghost_id for d in observed if d.ghost_id}:
            return "candidate", "Ghost does not report the finding behind this removal."
        variant = keep_variant(target, proposal)
        if variant is None:
            return "candidate", "The removed code cannot be made to fail loudly, so the keep test cannot run."
        before = self._suite(target, python, notes, f"cycle {number} keep test baseline")
        if before is None or not before.green:
            return "systemic", "The suite is not green."
        if before.skipped or before.xfailed:
            return "candidate", (f"some tests did not run ({before.skipped} skipped, {before.xfailed} "
                                 "xfailed), so the suite cannot prove this code is unused")
        snapshot: Dict[str, Optional[bytes]] = {rel: (target / rel).read_bytes() for rel in variant}
        # Saved outside the target first, so a kill during the trap cannot leave the trap behind.
        trapped_bytes = {rel: textio.encode_like(target / rel, text) for rel, text in variant.items()}
        runstate.write_journal(target, snapshot, trapped_bytes)
        try:
            for rel, text in variant.items():
                textio.write_text(target / rel, text)
            trapped = self._suite(target, python, notes, f"cycle {number} keep test (code made to fail)")
        finally:
            _restore(target, snapshot)
            runstate.clear_journal(target)
        if trapped is None or preserved(before, trapped) is not None:
            notes.append(f"Cycle {number}: keep test FAILED. The suite noticed when the code broke, "
                         "so something uses it.")
            return "candidate", "Keep test failed: the code is still used."
        notes.append(f"Cycle {number}: keep test passed. Nothing ran the code when it was made to fail.")
        return "", ""

    def _apply(self, target: Path, proposal: Transformation, auth: Authorization, python: str,
               notes: list[str], number: int, seen: int, validated: bool = False) -> "_Applied":
        if not validated and is_deletion(target, proposal):
            notes.append("A removal reached the applier without two loop validations. Refused.")
            return _Applied(number, seen, proposal, False, "REFUSED", None, None, {})
        before = self._suite(target, python, notes, f"cycle {number} before")
        if before is not None and not before.green:
            proposal.status = TransformationStatus.PROPOSED
            notes.append("Rule 7: the target's suite is not green before the change "
                         f"({before.describe()}), so it cannot protect behavior. Nothing was written.")
            return _Applied(number, seen, proposal, False, "SUITE_RED", before, None, {})
        snapshot = _snapshot(target, proposal)
        proposal.authorize(auth)
        try:
            proposal.apply(target)
        except (ValueError, OSError, Unauthorized) as err:  # includes a file that is not UTF-8
            _restore(target, snapshot)
            proposal.status = TransformationStatus.REJECTED
            notes.append(f"Cycle {number}: the change could not be applied ({err}); it was put back.")
            return _Applied(number, seen, proposal, False, "PUT_BACK", before, None, snapshot)
        notes.append(f"Cycle {number}: transformation applied under granted authorization.")
        try:
            after = self._suite(target, python, notes, f"cycle {number} after")
        except SuiteChangedSource:
            _restore(target, snapshot)
            raise
        broken = preserved(before, after) if before is not None else None
        if broken is not None:
            _restore(target, snapshot)
            proposal.status = TransformationStatus.REJECTED
            notes.append(f"Rule 7: {broken}.")
            return _Applied(number, seen, proposal, False, "PUT_BACK", before, after, snapshot)
        return _Applied(number, seen, proposal, True, "APPLIED", before, after, snapshot)

    def _calibrate(self, python: str, notes: list[str]) -> Optional[bool]:
        """SWIZZLE's instrument check: are its own planted defects still real?"""
        if self.swizzle_root is None:
            notes.append("SWIZZLE proofs NOT RUN: no swizzle_root. The adversary is uncalibrated.")
            return None
        sound, summary = swizzle_proofs_hold(swizzle_root=self.swizzle_root, python=python)
        notes.append(summary)
        self._sound = sound
        return sound

    def _grade(self, python: str, notes: list[str]) -> None:
        """ASSAY's answer key: is Ghost's eye any good? Graded once, before anything is written."""
        if self.assay_root is None:
            notes.append("ASSAY grading NOT RUN: no assay_root. Ghost's accuracy is unchecked.")
            return
        if self.swizzle_root is None:
            notes.append("ASSAY grading NOT RUN: it is done by SWIZZLE and no swizzle_root was given.")
            return
        self._assay_state, self._assay, summary = assay_score(
            swizzle_root=self.swizzle_root, assay_root=self.assay_root,
            ghost_root=self.ghost_tools_root, python=python)
        notes.append(summary)
        if self.assay_floor == 0:
            notes.append("ASSAY floor NOT ENFORCED (--assay-floor 0): Ghost's score is recorded but nothing "
                         "requires it to catch any failure mode.")

    def _observe(self, target: Path, findings: Optional[Sequence[dict]], python: str,
                 notes: list[str]) -> tuple[Defect, ...]:
        if findings is not None:
            observed = _defects(findings)
            self._absorb_ghost(findings)
            notes.append(f"Ghost Tools findings loaded ({len(observed)}), not scanned in this process.")
            return observed
        if self.ghost_tools_root is None:
            notes.append("Ghost Tools scan SKIPPED: no ghost_tools_root. Observation is UNKNOWN.")
            return ()
        raw = self._scan(target, python)
        stale = [f for f in raw if isinstance(f, Mapping) and f.get("detector") == STALE_BASELINE_DETECTOR]
        self._stale_baseline = _inert_baseline_entries(stale)
        observed = _defects(raw)
        notes.append(f"Ghost Tools observed {len(observed)} finding(s).")
        return observed

    def _scan(self, target: Path, python: str):
        """Ghost's findings. Ghost reports only, so the tree must not change while it runs."""
        try:
            with watch(target, "Ghost Tools"):
                found = ghost_scan(target, ghost_tools_root=self.ghost_tools_root, python=python,
                                   ghost_timeout=self.ghost_timeout)
            self._absorb_ghost(found)
            blind = getattr(found, "blind", None)
            if blind:
                self._down.add("ghost")
                self._notes.append(f"{blind}. Ghost is counted as not measured.")
            return found
        except SeatBrokeCharter:
            raise
        except (GhostCrashed, GhostRefused) as err:
            # Ghost itself died or refused to start: an instrument fault, so INCONCLUSIVE (never a finding).
            raise GhostUnavailable(f"{err}. This is a fault in Ghost, not a finding. Observation is UNKNOWN; "
                                   "nothing further was attempted.") from err
        except Exception as err:  # noqa: BLE001 - any failure to see is UNKNOWN, not "no findings"
            raise GhostUnavailable(
                f"Ghost could not be run or read ({type(err).__name__}: {str(err)[:120]}). "
                "Observation is UNKNOWN; nothing further was attempted.") from err

    def _absorb_ghost(self, found) -> None:
        """Take what new Ghost said about its scan (old Ghost says nothing; that changes nothing).

        Rule: only gaps count (checks that should have run and did not, unparsable files, a detector
        that raised, git missing when needed). Checks the caller declined or that are opt-in and were
        not requested are listed as `declined` and never touch the decision.
        """
        self._note_baseline(found)
        counts = getattr(found, "scan_counts", None)
        gaps = tuple(getattr(found, "gaps", ()) or ())
        self._ghost_gaps = [_plain(g) for g in gaps]
        if getattr(found, "version_unverified", False) and "ghost_version_unverified" not in self._info:
            # An old Ghost cannot say what it did not look at. Its result is read as it always was; this
            # only records that the version could not be told apart from a complete one.
            self._info.append("ghost_version_unverified")
            self._notes.append("ghost_version_unverified: this Ghost prints a bare list of findings and cannot say "
                               "what it left unmeasured, so a clean result from it is taken as it always was.")
        if counts is None and getattr(found, "status", None) is None and not gaps:
            self._ghost_info = None
            return
        self._ghost_info = {
            "status": getattr(found, "status", None), **(counts or {}),
            "gaps": self._ghost_gaps[:10], "gaps_not_shown": max(0, len(self._ghost_gaps) - 10),
            "declined": [_plain(d, 40) for d in (getattr(found, "declined", ()) or ())][:20],
            "baseline": getattr(found, "baseline", None),
        }
        if self._ghost_gaps:
            self._notes.append("Ghost scan has gaps, so Ghost is counted as partly measured: "
                               + "; ".join(self._ghost_gaps[:5]) + ("; and more" if len(self._ghost_gaps) > 5 else ""))

    def _baseline_report(self) -> Optional[dict]:
        if self._baseline_first is None and self._baseline_last is None:
            return None
        return {"before": self._baseline_first, "after": self._baseline_last}

    def _note_baseline(self, found) -> None:
        """Keep Ghost's baseline report from the first scan and the latest one, for the Judge.

        Only a readable {path: text or None, suppressed: whole number} is kept; anything else is None, so
        the Judge says "unknown" rather than being told something Ghost did not say. This is separate from
        the gap accounting in `_absorb_ghost`, which is unchanged.
        """
        raw = getattr(found, "baseline", None)
        report = None
        if isinstance(raw, Mapping):
            suppressed, path = raw.get("suppressed"), raw.get("path")
            if (isinstance(suppressed, int) and not isinstance(suppressed, bool) and suppressed >= 0
                    and (path is None or isinstance(path, str))):
                report = {"path": path, "suppressed": suppressed}
        if not self._baseline_seen:
            self._baseline_seen = True
            self._baseline_first = report
        self._baseline_last = report

    def _collect_skipped(self) -> None:
        """After a Drafter call: gather its own account of what it left alone, if it keeps one."""
        describe = getattr(self.drafter, "describe_skipped", None)
        if not callable(describe):
            return
        try:
            lines = tuple(describe())
        except Exception:  # noqa: BLE001 - optional information must never fail a run
            return
        for line in lines:
            if not isinstance(line, str):
                continue
            line = _plain(line, 200)
            if not line or line in self._skipped:
                continue
            if len(self._skipped) < MAX_SKIPPED_LINES:
                self._skipped.append(line)
            else:
                self._skipped_more += 1

    def _skipped_lines(self) -> tuple[str, ...]:
        more = (f"... and {self._skipped_more} more not shown",) if self._skipped_more else ()
        return tuple(self._skipped) + more

    def _suite(self, target: Path, python: str, notes: list[str], when: str) -> Optional[SuiteRun]:
        if not self.run_tests:
            if when.endswith("before"):
                notes.append("Rule 7 NOT RUN: run_tests=False. Behavior preservation is unmeasured.")
            return None
        source_before = _source_hash(target)
        self._suite_ran = True
        result = run_suite(target, python, self.suite_timeout)
        notes.append(f"Rule 7 suite {when}: {result.describe()}.")
        if _source_hash(target) != source_before:
            notes.append(f"Rule 7: {SOURCE_CHANGED_NOTE}.")
            raise SuiteChangedSource(SOURCE_CHANGED_NOTE)
        return result

    def _reinspect(self, target: Path, observed: tuple[Defect, ...], python: str,
                   notes: list[str]) -> tuple[Defect, ...]:
        if self.ghost_tools_root is None:
            return observed
        reobserved = _defects(self._scan(target, python))
        before_ids = {d.ghost_id for d in observed if d.ghost_id}
        after_ids = {d.ghost_id for d in reobserved if d.ghost_id}
        notes.append(f"Ghost re-inspected: {len(reobserved)} finding(s); "
                     f"closed={sorted(map(safe_id, before_ids - after_ids))} "
                     f"new={sorted(map(safe_id, after_ids - before_ids))}")
        return reobserved


@dataclass
class _Applied(Cycle):
    restore: Dict[str, Optional[bytes]] = field(default_factory=dict)

    def __init__(self, number, observed, proposal, applied, outcome, before, after, restore):
        super().__init__(number, observed, proposal, applied, outcome, before, after)
        self.restore = restore


def _commented(target: Path, proposal: Transformation) -> Optional[Transformation]:
    """The same proposal, but commenting the code out instead of deleting it."""
    files = commented_variant(target, proposal, stamp_now())
    if files is None:
        return None
    proposal.edits = tuple(FileEdit(path=rel, kind="write", new=text,
                                    old=textio.read_text(target / rel))
                           for rel, text in files.items())
    proposal.intent = "comment out unused code (not deleted): " + proposal.intent
    return proposal


def _fingerprint(target: Path) -> str:
    """A short hash of the tree, so a proposal can say which state it was written against."""
    digest = hashlib.sha256()
    skip = {".git", "__pycache__", ".pytest_cache", ".venv", "node_modules"}
    for path in sorted(Path(target).rglob("*")):
        if path.is_file() and not skip.intersection(path.relative_to(target).parts):
            digest.update(str(path.relative_to(target)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def _edits_key(proposal: Transformation) -> str:
    return hashlib.sha256(repr([(e.path, e.kind, e.old, e.new) for e in proposal.edits]).encode()).hexdigest()


def _expect(value, seat: str):
    """A Transformation, or None. Anything else is a seat giving the wrong kind of answer."""
    if value is not None and not isinstance(value, Transformation):
        raise WrongAnswer(seat, value, "a proposal")
    return value


def _changes_nothing(target: Path, proposal: Transformation) -> bool:
    """True when every edit would leave its file exactly as it is."""
    try:
        for edit in proposal.edits:
            path = Path(target) / edit.path
            if edit.kind == "delete" or not path.is_file():
                return False
            current = textio.read_text(path, edit.path)
            if edit.kind == "write":
                same = _lf(edit.new) == _lf(current)
            elif edit.kind == "replace":
                same = _lf(edit.old) == _lf(edit.new)
            else:
                same = False
            if not same:
                return False
        return True
    except (OSError, ValueError):
        return False


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n")


def _inert_baseline_entries(stale_findings) -> int:
    """How many baseline entries matched nothing. Ghost reports them as one finding whose attributes carry
    the count; a finding with no readable count still counts as at least one entry."""
    total = 0
    for f in stale_findings:
        attrs = f.get("attributes") if isinstance(f.get("attributes"), Mapping) else {}
        try:
            total += max(1, int(attrs.get("stale", 1)))
        except (TypeError, ValueError):
            total += 1
    return total


def _defects(findings) -> tuple[Defect, ...]:
    for f in findings:
        if not isinstance(f, Mapping):
            raise GhostUnavailable("Ghost's findings could not be read (an item was not a record). "
                                   "Observation is UNKNOWN; nothing further was attempted.")
        if f.get("id") is not None and not isinstance(f.get("id"), str):
            raise GhostUnavailable("Ghost's findings could not be read (a finding's id was not text). "
                                   "Observation is UNKNOWN; nothing further was attempted.")
    try:
        return defects_from_ghost(findings)
    except (AttributeError, TypeError, ValueError) as err:
        raise GhostUnavailable(f"Ghost's findings could not be read ({type(err).__name__}). "
                               "Observation is UNKNOWN; nothing further was attempted.") from err


def _source_hash(target: Path) -> str:
    """A hash of the target's non-test Python files, to notice a suite that rewrites source."""
    digest = hashlib.sha256()
    for path in sorted(Path(target).rglob("*.py")):
        rel = path.relative_to(target)
        if FORBIDDEN_DIRS.intersection(p.lower() for p in rel.parts) or is_test_code(rel.as_posix()):
            continue
        if path.is_file():
            digest.update(rel.as_posix().encode("utf-8", "replace"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _is_warden(target: Path) -> bool:
    """Warden's own tree, recognised by what it contains and not by what the folder is called."""
    return (target / "warden" / "authorization.py").is_file()


def _refuse_self_authorization(target: Path, authorization: Optional[Authorization]) -> None:
    """Warden may transform other repos. Transforming itself under its own
    proposal is the self-certifying loop. Neither Warden nor any other part of the stack
    (a seat or an instrument) may be the human who authorizes a write, whatever the folder is
    called and however the name is spelled (case, spaces, zero-width or look-alike characters)."""
    if authorization and authorization.granted and (is_stack_actor(authorization.actor)
                                                    or not authorization.actor.strip()):
        raise Unauthorized(f"{authorization.actor!r} cannot authorize a write; a human or external governor must.")


class _Snap(dict):
    """Each file a proposal touches as it was, plus the folders applying it would have to create."""

    def __init__(self) -> None:
        super().__init__()
        self.new_dirs: list = []


def _snapshot(target: Path, proposal: Transformation) -> Dict[str, Optional[bytes]]:
    """Each file the proposal touches, byte for byte as it is now (None: it does not exist yet)."""
    out = _Snap()
    for edit in proposal.edits:
        path = target / edit.path
        out[edit.path] = path.read_bytes() if path.is_file() else None
        parent = path.parent
        while parent != target and target in parent.parents and not parent.exists():
            if parent not in out.new_dirs:
                out.new_dirs.append(parent)
            parent = parent.parent
    return out


def _restore(target: Path, snapshot: Dict[str, Optional[bytes]]) -> None:
    for rel, data in snapshot.items():
        path = target / rel
        if data is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    # Folders the apply made, now empty again, go too (deepest first).
    for folder in sorted(getattr(snapshot, "new_dirs", ()), key=lambda d: len(d.parts), reverse=True):
        try:
            folder.rmdir()
        except OSError:
            pass  # not empty, or already gone
