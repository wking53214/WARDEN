# Changelog

All notable changes to Warden. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the version in `warden/__init__.py` (read by `pyproject.toml`) is the single source of truth.
The seat contract (`warden.CONTRACT`) is `"1"` throughout and has not changed.

Tags exist for v0.8.0 to v0.11.4 only. `0.11.5`, `0.12.0`, `0.13.0` and `0.13.1` are not tagged: tagging is the owner's
decision, and the satellites (Judge, Drafter, Burnish) pin Warden by full commit SHA, not by tag.

## [0.13.1] - 2026-10-17

### Behavior changes

- **Warden checks SWIZZLE's contract before it reads anything SWIZZLE prints.** It runs
  `python -m swizzle.cli --contract` and requires a JSON object with `name` `"swizzle"` and `contract` `1`
  (SWIZZLE 0.8.0, `docs/CONTRACT.md`). Fails closed: a SWIZZLE with no such flag (older than 0.8.0), a different
  contract number, another tool answering as SWIZZLE, output that is not that JSON, or a check that cannot run
  makes the SWIZZLE proof gate unmeasured: `swizzle_sound` is false, `swizzle` is in `unmeasured`, ASSAY
  grading (which runs through SWIZZLE) is not run, nothing is written, and the run ends `INCONCLUSIVE`
  (exit 2, like any SWIZZLE whose proofs do not hold), never a plain `ACCEPT`. The reason is in `reason` and
  `notes`. A matching SWIZZLE changes nothing.
- New API: `warden.swizzle.swizzle_contract_holds`, and `swizzle_proofs_hold(..., check_contract=True)`, which
  returns `(False, reason)` for an unconfirmed SWIZZLE without running `prove`. The seat contract
  (`warden.CONTRACT`) is still `"1"` and no other public name changed.

### Changed

- The `ghost` extra is pinned to ghost_tools 1.10.0 (`288cefa7608cace8be0f91cabcc305930466d84b`).
- CI sibling pins moved to the fixed siblings so the `circuit` job tests what is shipped: ghost_tools 1.10.0
  (`288cefa7608cace8be0f91cabcc305930466d84b`), SWIZZLE 0.8.0 (`04b72b197b703e7e64be62039509c1c9e6c3bf20`)
  and ASSAY 0.11.0 (`5aafbf3b45c68d0948574ff4364cde614890839e`). The non-blocking `assay-latest` job is kept.
- `tests/test_closing_false_accepts.py::test_a_fake_ghost_inside_the_target_is_not_used_by_the_scan` no longer
  assumes Ghost Tools is absent: with `warden[ghost]` installed the real Ghost answers, and the test checks the
  fake in the target is not the one that ran, in either environment.

## [0.13.0] - 2026-10-17

### Behavior changes

- **A Judge's ACCEPT can no longer waive the ASSAY floor.** Warden now enforces `--assay-floor` itself: when
  the score is graded and Ghost caught fewer known failure modes than the floor, the run ends `REJECT`
  (exit 1) whatever the Judge said, and also when no Judge is seated. Before, only a Judge that happened to
  check the floor enforced it, and a stub Judge returning ACCEPT left the changes standing under
  `--assay-floor 7`. Floor `0` is still the one explicit way to skip it.
- **A Judge verdict with no reasons is an `ERROR`** (exit 4, tree put back), for any label. A verdict with
  reasons that are all blank counts as none. A return that is not a verdict at all (a string, `None`, a
  tuple) was already an `ERROR` and is now pinned by tests.
- **SWIZZLE attacks that did not run now hold the run.** When SWIZZLE's proofs hold but its attacks on the
  governor cannot be run or read, `unmeasured` gains `swizzle_attacks` and the run ends `ACCEPT_UNVERIFIED`
  (exit 3) instead of leaving the decision to the Judge. This reverses the old KNOWN DEFECTS line that said
  such attacks "do not by themselves turn an ACCEPT into ACCEPT_UNVERIFIED".
- **The target's test suite no longer receives credentials from the caller's environment.** Variables whose
  names mark a credential (`*TOKEN*`, `*SECRET*`, `*PASSWORD*`, `*API_KEY*`, `AWS_*`, `ANTHROPIC_*`,
  `OPENAI_*`, `SSH_AUTH_SOCK` and similar) are withheld from `pytest` and `cargo test` runs. `PYTHONPATH` is
  kept. `WARDEN_SUITE_ENV_PASSTHROUGH=1` hands over the full environment for a suite that really needs one.
  This is a cheap hardening, not a sandbox: see KNOWN DEFECTS.
- `SwizzleAdapter.handoff_verdicts` no longer counts a result it does not know (`UNKNOWN`, `NOT_RUN`,
  `ERROR`) as a pass; the handoff is `INCONCLUSIVE` with epistemic state `UNKNOWN`.
- `warden.horsemen.try_import_shared_contracts` is removed. It imported a module (`horsemen_contracts`) that
  does not exist and nothing used it.

### Not changed, pinned by a test

- With no `--swizzle-root`, a run is `ACCEPT_UNVERIFIED` (exit 3), never `ACCEPT`, under either scope and
  whatever the Judge says. The README's old "a change can still be ACCEPTed" line was stale and is corrected.

### Added

- `warden tagteam --receipt FILE`: writes the horsemen production receipt for an authorized run, built by
  walking a real `HorsemenWorkflow` through `AssayAdapter`, `GhostToolsAdapter` and `SwizzleAdapter`
  (`warden.horsemen.circuit.receipt_for_run`). The file must lie outside the target. The run's decision,
  exit code and stdout JSON are unchanged.
- Logging with the standard library, to stderr only: seat load, each instrument run, the suite, the verdict
  and the put-back. `-v` / `-vv` on every command, or `WARDEN_LOG_LEVEL`. Stdout stays one JSON document.
- `TagTeamResult.attacks`: SWIZZLE's attack results as reported (default `None`).
- `CHANGELOG.md`, `docs/ARCHITECTURE.md`, `docs/EXIT_CODES.md` (the exit-code page is generated from
  `warden.cli.EXIT_CODES` by `tools/gen_docs.py`, and a test fails when either page is stale).
- `tools/circuit_smoke.py` and a `circuit` CI job: the horsemen circuit smoke test against ASSAY,
  ghost_tools and SWIZZLE at pinned commits.
- Rust projects are measured with `cargo test` (Rule 7 gate, merged after 0.12.0 without a version bump).

### Changed

- Lint and types are gates: ruff (`E`, `F`, `W`, `B`) and mypy run in CI and pass. 14 mypy errors fixed,
  among them an `int + None` in the cargo reader, a `.group` on a possibly-missing match in the audit
  reader, and a possibly-`None` suite result passed to `preserved`.
- CI runs on Python 3.11, 3.12 and 3.13.
- Pins: `cns` by commit SHA (v1.8.0), the `ghost` extra by commit SHA (ghost_tools main after V1.9.1), and
  the CI ASSAY checkout by commit SHA, each with a bump instruction beside it.
- The version is read from `warden/__init__.py` by `pyproject.toml` instead of being written twice.
- README: the history paragraph moved here, test counts removed (the count was wrong: 535 against 571
  passing), the seat pin described correctly (a commit SHA, not tag `v0.11.0`), and "NOT PROVEN" corrected
  to say what `docs/REGISTRY.json` actually records.

## [0.12.0] - 2026-10-17

- Enforces the two CNS rows where Warden reads records from other repositories. A Ghost finding that does
  not meet `cns.finding` stops the observation as unreadable, so the run is `INCONCLUSIVE`; a SWIZZLE
  attack result that does not meet `cns.attack` leaves the attacks not measured. Clean records are read as
  before. Depends on CNS `v1.8.0`.

## [0.11.5] - 2026-10-15

- Checks the Ghost findings and SWIZZLE attack results against their CNS rows and notes drift without
  refusing it.

## [0.11.4] - 2026-10-15

- Imports the shared rows (defects, seat rows, epistemic vocabulary, suite result) from CNS 1.7.0 instead of
  carrying copies. Classes and behavior unchanged.
- Every run record is printed as `cns.run/1`: the schema marker and text reasons.

## [0.11.3] - 2026-10-15

- `--cns DIR` reads the stack manifest from CNS, the hub, instead of a file.

## [0.11.2] - 2026-10-15

- `--join PATH` and `--stack-manifest FILE`: sibling checkouts Ghost may read beside the target, so a
  cross-repository boundary is measured instead of held as `ghost_partial`.
- Refuses an instrument checkout inside the governed folder, and any edit under a fixture folder.

## [0.11.1] - 2026-10-14

- Hardens the tree watch around each seat: source files are compared byte for byte, and `.venv`, `venv`,
  `env` and `node_modules` are watched by name, size and time.

## [0.11.0] - 2026-10-13

- `--stack DIR` seats the whole circuit from one folder of checkouts.
- The scope handoff: a Drafter or Finisher that keeps a `scope` attribute is told the grant's scope.

## [0.10.1] - 2026-10-12

- Version corrected after v0.10.0 (the held-result rule and the instrument isolation fix).

## [0.10.0] - 2026-10-12

- Held results: an `ACCEPT_UNVERIFIED` run is put back and saved under a digest; `warden keep` applies it
  only under a human grant for that exact digest.
- Instruments run with only their named roots on `PYTHONPATH`.
- Stops the run when Ghost's baseline has entries that match nothing. Restores the tree when saving a held
  result fails.

## [0.9.0] - 2026-10-10

- Closes the round 3 red-team holes: dirty folder refused, the suite result read from pytest's own report
  and exit status, the protected-file guard, the keep-test journal, Judge handling, seat checks, honest
  accounting. Hands Ghost's baseline report to the Judge. Declares Ghost Tools as the optional `ghost` extra.

## [0.8.0] - 2026-10-09

- Seat handshake: a seat must declare `requires_contract`; the output names `contract` and `versions`.
- Honest exit codes, honest "not measured", strict instrument readers, both Ghosts read honestly, the
  Drafter's skipped reasons surfaced, eleven false accepts closed, defect lifecycle moves checked.

## [0.7.0] and earlier - 2026-10-04 to 2026-10-08 (untagged)

- 2026-10-08: renamed from Elegant to Warden. Judge seat (only a third party can turn a run into ACCEPT),
  ASSAY in the loop (Ghost graded against the answer key first, floor default 3), the removal gate (keep
  test then comment-out test, never delete), seam checks, converging loop with a one-time Finisher, Rule 7
  test gate and Rule 9 audit file.
- 2026-10-07: tag team calls SWIZZLE; no write when SWIZZLE's proofs fail; the ASSAY link fails loudly
  instead of returning no specimens. Apache-2.0 licence.
- 2026-10-05: the Four Horsemen interface (typed handoffs, scoped grants, receipts).
- 2026-10-04: Elegant 0.1.0, the first commit.
