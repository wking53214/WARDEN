# Architecture

Warden is the governor of a four-part loop and the only part of the circuit that writes. It decides
whether a change may be made, whether it stands once made, and what is recorded. It does not decide
what a good fix is (Drafter), what better code looks like (Burnish), or whether the evidence is enough
(Judge); it calls those, and instruments that observe (Ghost Tools), attack (SWIZZLE) and grade (ASSAY),
without becoming any of them.

## The run

1. The command line (`warden.cli`) loads the seats (`--drafter`, `--finisher`, `--judge`), checking each
   declares `requires_contract = "1"`, and refuses any seat or instrument that lives inside the target.
2. `warden.tagteam.TagTeam.run` takes the per-target lock, refuses a dirty git folder, and snapshots the tree.
3. SWIZZLE must first declare the contract Warden reads (`swizzle --contract`, contract 1; absent or different
   means unmeasured and nothing is written). Then SWIZZLE's own proofs are checked, ASSAY's answer key grades Ghost, and Ghost observes (`warden.swizzle`,
   `warden.ghost`, always in an empty directory via `warden.isolation`).
4. The loop: the Drafter proposes one change as data; `warden.guard` and the human grant decide whether it
   may touch anything; `warden.suite` runs the target's own suite before and after (Rule 7); Ghost
   re-inspects. Anything that breaks the suite or adds a finding is put back.
5. Once converged, the Finisher is asked once, its change goes through the same gate, and the Judge reads
   the evidence. Warden itself then enforces what the Judge cannot waive: the ASSAY floor and the list of
   unmeasured checks. Only a fully measured run with a Judge ACCEPT ends `ACCEPT`.
6. A run that does not end `ACCEPT` leaves the tree as found. `ACCEPT_UNVERIFIED` is first saved as a held
   result (`warden.held`) that a named person can approve with `warden keep`.
7. One JSON run record (`cns.run/1`) is printed on stdout and the exit code follows `docs/EXIT_CODES.md`.
   Logs (`warden.log`) go to stderr only.

## The horsemen interface

`warden.horsemen` holds typed handoffs (`Handoff`), adapters for ASSAY, Ghost Tools and SWIZZLE, scoped
grants, a workflow and a production receipt. `warden tagteam --receipt FILE` is the one place Warden's own
command line drives it: after an authorized run, `warden.horsemen.circuit.receipt_for_run` walks a real
`HorsemenWorkflow` through the handoffs the run produced. ASSAY's test suite also imports `AssayAdapter`.
Judge, Drafter and Burnish do not import it; they import Warden's data shapes (`warden.models`,
`warden.roles`, `warden.authorization`) only.

## Public surface other repositories depend on

`warden.CONTRACT` (`"1"`), `warden.models`, `warden.roles`, `warden.authorization`, `warden.held`,
`warden.tagteam`, `warden.suite`, `warden.horsemen.AssayAdapter`, and `warden.cli._load_seat`. Changing any
of these in a way that breaks a seat written for the old shape raises `CONTRACT`.

## Known limits

The seats run inside Warden's process and the target's suite runs with the target's code; neither is
sandboxed. See "KNOWN DEFECTS" in the README.

## Modules

The table below is generated from each module's own docstring by `tools/gen_docs.py` and checked by
`tests/test_docs.py`.

<!-- BEGIN GENERATED MODULES -->
| module | what it is |
|---|---|
| `warden` | Warden: the discipline of change. |
| `warden.audit` | Rules 5 and 9: the defect audit file, with IDs that never change meaning. |
| `warden.authorization` | Human authority boundary. |
| `warden.claim` | The claim seat: a Drafter that proposes one real change the operator names, then nothing. |
| `warden.cli` | warden: govern a change: observe, authorize, gate on the suite, record. |
| `warden.deletion` | The removal gate: code is commented out only after two opposite tests pass. |
| `warden.epistemic` | Truthful epistemic language. |
| `warden.ghost` | Ghost Tools consumer. |
| `warden.gitstate` | What git says about a folder, asked in a way that cannot change it or run its code. |
| `warden.guard` | The seams: what Warden checks about its own seat-fillers instead of trusting them. |
| `warden.held` | Held results: an unverified run's final state, kept for a human to approve. |
| `warden.isolation` | Run Warden's instruments (SWIZZLE, Ghost Tools, ASSAY grading) away from the target. |
| `warden.log` | Logging for Warden: the standard library's `logging`, written to stderr only. |
| `warden.models` | Transformation and defect representations. |
| `warden.registry` | Final integration registry. |
| `warden.roles` | The two seats Warden seats other repositories in. |
| `warden.runstate` | Things a run must keep outside the target and outside the temp directory: a lock and a journal. |
| `warden.suite` | Rule 7, the behavior-preservation gate: the target's own suite, before and after. |
| `warden.swizzle` | SWIZZLE consumer: is the adversary's own instrument sound? |
| `warden.tagteam` | The loop: Ghost sees, Drafter proposes, Warden decides and applies, SWIZZLE checks. |
| `warden.textio` | Reading and writing files without changing what the author wrote. |
| `warden.versions` | Which versions took part in a run, for the `versions` field of `warden tagteam`'s JSON. |
| `warden.horsemen` | Four Horsemen interface for Warden. |
| `warden.horsemen.adapters` | Adapters that consume other horsemen without becoming them. |
| `warden.horsemen.authorization_scope` | Scoped authorization for horsemen transformations. |
| `warden.horsemen.circuit` | The horsemen interface as Warden's own command line uses it. |
| `warden.horsemen.contracts` | Handoff envelopes between horsemen. |
| `warden.horsemen.receipt` | Production receipt for horsemen-mediated transformations. |
| `warden.horsemen.workflow` | Four Horsemen workflow orchestration owned by Warden. |
<!-- END GENERATED MODULES -->
