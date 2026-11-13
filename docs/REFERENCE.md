# Reference

Why Warden exists, what it owns, its architecture picture, module table and key concepts.

*Moved from the README on 2026-11-10 with the text unchanged. Where it says "the README", "above" or names a section (WHAT WORKS, KNOWN DEFECTS, LIFECYCLE and so on), it means this documentation set; the map is in [README.md](../README.md).*

## REFERENCE

The sections below describe how Warden behaves. The claims above are the ones with proof attached; a statement below that names no test is a description of the code, not a measurement.

## WHY IT EXISTS

Beautifying code is easy to do badly: a cleanup that quietly changes behavior,
a rewrite nobody approved, a verdict that certifies its own author's work.
Warden is the part that makes those failures impossible to do quietly. It was
split out of the original Warden, which mixed this discipline with the
opinion about what better code looks like. The opinion moved to Burnish on
2026-10-08 so each can be judged on its own.

## WHAT IT OWNS

- Transformation proposals as data: reason, target, baseline, preservation, evidence
- The human authorization boundary (`UNKNOWN` is not `APPROVED`; Warden cannot authorize itself; it rests on who can run the command, not on identity, see WHAT DOES NOT WORK)
- Rule 7, the test gate: the target's own suite before and after every write
- Rule 9, the audit file: `WARDEN_AUDIT.md`, Ghost findings under IDs that never change meaning
- The SWIZZLE proof gate: SWIZZLE's own proofs must hold before anything is accepted
- The tag-team loop that *calls* Ghost Tools, SWIZZLE, a Drafter and a Finisher without becoming any of them
- The Horsemen interface (an older name; the circuit now has five seats): typed handoffs between ASSAY, Ghost Tools, SWIZZLE and Warden. Warden's own command line drives it through `--receipt`; ASSAY's tests import `AssayAdapter`; Judge, Drafter and Burnish do not import it (they import `warden.models`, `warden.roles` and `warden.authorization` only)

## WHAT IT DOES NOT OWN

- Which fix to propose (Drafter), and the beautifying and final README (Burnish)
- Forensic detectors, ledgers, mutation (Ghost Tools)
- Independent oracles and ground truth (SWIZZLE)
- Row shapes and interoperability contracts (CNS), which Warden never modifies
- Live admission, decision, conservation, execution, custody
- A numeric elegance score

## ARCHITECTURAL STORY

The picture below shows the loop with a Drafter and a Finisher seated. Today a real change usually enters through the claim seat instead, and no Finisher is part of the circuit (see [STACK.md](STACK.md)).

```
CODEBASE
   │
   ▼
SWIZZLE       proves its own instrument first; nothing is written if its proofs fail
   │
   ▼
┌─ THE LOOP, repeated until the Drafter has nothing left ───────────────┐
│  GHOST TOOLS   observe / find   (findings keep ghost-* identity)       │
│  DRAFTER      proposes one change (data, never a write)               │
│  human grant   Authorization.granted == True                           │
│  TARGET SUITE  green before (Rule 7)                                   │
│  WARDEN       applies the change: the one point a file is written     │
│  TARGET SUITE  green after, or the change is put back                  │
│  GHOST TOOLS   re-inspect                                              │
└─────────────────────────────────────────────────────────────────────────┘
   │  converged (or NOT_CONVERGED at the cycle limit: no hand-off)
   ▼
SWIZZLE       proofs checked again
   │
   ▼
FINISHER      once: beautified code and the final README (Burnish)
   │          Warden applies it under the same gate; the suite breaking or
   │          any new Ghost finding puts it back
   ▼
ACCEPT / FINISH_REJECTED
```

| module | owns |
|---|---|
| `warden.epistemic` | GUARANTEED / VERIFIED / IMPLEMENTED / DESIGNED / ASSUMED / UNKNOWN / NOT_IMPLEMENTED / INTENTIONALLY_NOT_PROVIDED |
| `warden.models` | Defect, Transformation, FileEdit; consumes `ghost-*` IDs |
| `warden.authorization` | grant / refuse; self-grant is Unauthorized |
| `warden.roles` | the two seats: Drafter (in the loop) and Finisher (once, after it) |
| `warden.tagteam` | the loop |
| `warden.suite` | Rule 7: runs the target's own test suite before and after a change |
| `warden.audit` | Rules 5 and 9: `WARDEN_AUDIT.md` |
| `warden.swizzle` | the SWIZZLE proof gate |
| `warden.ghost` | JSON consumer plus an optional read-only scan |
| `warden.registry` | campaign record; the current one is `docs/REGISTRY.json` |
| `warden.horsemen` | typed handoffs, scoped grants, receipts. `AssayAdapter` reads ASSAY's `assay_production/registry.json` and raises `AssayUnavailable` rather than return no specimens. `warden.horsemen.circuit.receipt_for_run` is what `--receipt` calls; a result an adapter does not know is `INCONCLUSIVE`, never a pass |
| `warden.log` | stdlib logging to stderr only: `-v` / `-vv` or `WARDEN_LOG_LEVEL` |
| `warden.isolation` | runs SWIZZLE, Ghost and ASSAY grading in an empty directory, with absolute roots, and refuses a root that is not the checkout the instrument would load from |
| `warden.seatproc`, `warden.seat_runner`, `warden.seatwire`, `warden.sandbox` | `--isolate-seats`: each named seat in its own program. `seatproc` starts it and talks to it, `seat_runner` is the program, `seatwire` turns the shared rows into JSON and back (only `cns` and `warden` classes), `sandbox` applies the Linux limits (Landlock files, seccomp network, size caps) |
| `warden.runstate` | the per-target lock and the keep-test journal, kept in the repository's own git folder (or a private per-user state folder), never in TMPDIR and never through a symlink; also the SIGTERM/SIGHUP/SIGINT handlers, the seat timer and the fd 1 redirect |
| `warden.gitstate` | read-only questions to git: is the folder dirty, where is its git folder, what is `core.hooksPath` |
| `warden.guard` | what an edit may touch: the protected-file list, prose-only documentation scope, symlink resolution, and the snapshot that undoes a seat that wrote |
| `warden.textio` | byte-faithful reads and writes: line endings kept, non-UTF-8 files refused |
| `warden.deletion` | the removal gate: code is commented out only after two opposite tests pass |
| `warden.held` | held results: an unverified run's final state, kept for a person to approve with `warden keep` |
| `warden.versions` | which versions took part in a run, for the `versions` field of the JSON |
| `warden.claim` | the claim seat: `--claim-commit` and `--claim-diff`, a real change proposed once as writes and deletes of UTF-8 text, refused with a reason when it cannot be said that way |
| `warden.claimrow` | the claim row: what one run governed, by commit, diff digest, file digests, grant, suite, findings, verdict and held tree |
| `warden.chronicle` | one line per run keyed by origin and commits, the promises a held result opens, and their settlement by the next run on that tree |
| `warden.cli` | `tagteam`, `keep`, `chronicle` and `audit`; the exit-code table, the seat handshake, and `--stack` |

## KEY INTERNAL CONCEPTS

- **Governor, not judge.** A Drafter or Finisher never outvotes a red suite, a missing grant, or a new Ghost finding.
- **Converged is not clean.** The loop ends when the Drafter has nothing left, not when Ghost reports zero; the notes say how many findings remain.
- **One intentional change.** Ambiguous replacements refuse.
- **Identity.** Ghost's hash is the machine identity. C1/H1/M1/L1 are labels.
- **Self-certification is a bug.** Warden cannot grant actor `warden` / `self` / `unknown`, nor any seat or tool name (Drafter, Burnish, Ghost, SWIZZLE, ASSAY, Judge), however it is spelled: case, spaces, zero-width characters and look-alike letters are folded away before the check.
- **One-way dependency.** Drafter and Burnish import Warden's data shapes. Warden imports neither.

## IMPORTANT BOUNDARIES

Warden does not sit on Admission → Custody.
A CNS mention is not a CNS seam.
Running a repository's tests runs its code, so Rule 7 happens only after a human grant.
