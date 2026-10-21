# Changelog

All notable changes to Warden. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the version in `warden/__init__.py` (read by `pyproject.toml`) is the single source of truth.
The seat contract (`warden.CONTRACT`) is `"1"` throughout and has not changed.

The last tag is `v0.11.4` (tags exist for v0.8.0 to v0.11.4 only). `0.11.5`, `0.12.0`, `0.13.0`, `0.13.1`, `0.13.2`, `0.13.3` and `0.13.4` are
not tagged: tagging is the owner's decision, and the satellites (Judge, Drafter, Burnish) pin Warden by full commit
SHA, not by tag.

## [0.13.4] - 2026-10-21

### Fixed

- **An installed copy could still be named as the root.** `--ghost-root $VENV/lib/python3.13/site-packages
  --swizzle-root <the same> --assay-root <ASSAY>` with a rubber-stamp Judge ended in `ACCEPT`, exit 0, nothing unmeasured,
  with `commit` and `version` null in the record and `module_in_root` true: the root held the package and the package
  resolved under it. A root is now also refused when it is, or lies inside, a `site-packages` or `dist-packages` folder or
  the interpreter's stdlib or site folders (links followed first), whatever it holds; and when Warden cannot name it: no
  git commit of its own or no readable version (a plain copy of the package). The opt-in is
  `--allow-uncommitted-instruments` (library: `TagTeam(allow_uncommitted_instruments=True)`, and `allow_uncommitted=` on
  `ghost.scan`, `swizzle_contract_holds`, `swizzle_proofs_hold`, `governor_attacks`, `assay_score`, `verify_root`): the
  run record says `allow_uncommitted_instruments: true`, `instrument_provenance` is added to `unmeasured`, and the run is
  at best `ACCEPT_UNVERIFIED`. It never opens an installed location. A real git checkout, including one also installed
  with `pip install -e`, is unchanged. Refusals are as before: Ghost `INCONCLUSIVE`, SWIZZLE `swizzle_sound` false (exit 2),
  ASSAY ungraded.
- `swizzle_sound` was null when Ghost failed after SWIZZLE's proofs had held (a bad `--ghost-root` beside a good
  SWIZZLE) although the notes said "12 of 12 proofs hold". It is now the proofs' answer (true here); the Ghost failure is
  recorded separately in `decision`, `reason` and `unmeasured`.
- Reasons were cut mid-word ("... does n)"). Every message that shortened text now uses `warden.textio.clip`: cut at a
  word, ` ...` marks the cut, text that fits is untouched.
- The article before ASSAY is "an" (one place, a test's skip reason). A test now fails on it anywhere in the repository's text.
- A garbage `--from-ghost` file gave `ERROR` with "Warden failed with JSONDecodeError". It still ends `ERROR`, exit 4 (now
  listed in the exit-code text), but the reason names the file and what was wrong ("... is not valid JSON (Expecting
  property name enclosed in double quotes, at line 1 column 2) ... Nothing was run."); an unreadable file, non-UTF-8 text and
  a file that is not a findings list are named the same way.

### Changed

- README: what is true about installed copies is stated exactly (the three conditions above, what the flag does, and that a
  Ghost chosen by SWIZZLE itself when `--ghost-root` is not given is not checked, which is why that run is at best
  `ACCEPT_UNVERIFIED`). That behavior is unchanged.

## [0.13.3] - 2026-10-21

### Changed

- **Merged the owner's authorization hardening** (`origin/main` d237acf, "Harden WARDEN authorization boundaries",
  2026-10-19) into this branch with a merge commit; neither history was rewritten.
  - `warden.models.Transformation.authorize` and `.apply` now refuse a reserved stack actor (`warden`, `self`, ...) or an
    actor that is empty once canonicalised (blank, zero-width), at the model boundary, in addition to `grant`.
  - `warden.horsemen.ScopedGrant.permits` and `validate_scoped` now take the repository and require it to match the scope's.
    The base grant and the scope must each permit the operation and subject (an empty allowlist denies), and the change
    class must be a `ChangeClass` matching the grant's. `validate_scoped(..., repository=...)` is a required argument now.
    Warden's own receipt path (`HorsemenWorkflow.transform`) passes it.
  - Warden's `tagteam`, instrument-root checks, `--authorize`, receipts and the Judge floor are unaffected: the run's
    grant already came from `grant`, which refused those actors, and the receipt's scope is built from the same repository
    it is checked against. No public import the satellites use changed (`warden.models`, `tagteam`, `authorization`, `held`,
    `roles`, `suite`, `cli._load_seat`), and `CONTRACT` is still `"1"`.
- The tested set moved: SWIZZLE 0.8.1 at `8166c47f321ecfb66b8efa72c1deac5d954e8e48`, ASSAY 0.11.1 at
  `4c415567d1c1cb2c1a9e8f343a7a11a5064258c8` and JUDGE 0.4.3 at `50f90f47660916d99deeb11370dd57bf85922dbe` (ghost_tools is
  unchanged at 1.10.1). CI, STACK.md and the pin tests say so.

### Fixed

- `tools/circuit_smoke.py` resolves `--ghost-tools`, `--swizzle` and `--assay` to absolute paths when the arguments are
  parsed. It runs Warden from a temporary folder, so the relative roots the CI `circuit` job passes
  (`_circuit/ghost_tools` and the like) pointed nowhere there and the job failed ("SWIZZLE's own proofs hold") while it
  passed locally with absolute paths. A root that is not a folder is now a usage error. Tooling, CI and tests only: the
  `warden` package, the version and the seat contract are unchanged. `tests/test_circuit_smoke_args.py` covers it.

## [0.13.2] - 2026-10-17

### Fixed

- **An installed copy of an instrument can no longer stand in for a root that is not there.** Dropping `PYTHONPATH`
  was not enough: the interpreter's site-packages stays importable, so with Ghost Tools installed
  `--ghost-root /nonexistent` (or `/etc`) still scanned ("Ghost Tools observed 0 finding(s)"), and with SWIZZLE
  installed `--swizzle-root /nonexistent/swz` reported "12 of 12 proofs hold" and `swizzle_sound` true, while the record
  named the missing path with a null commit. Now each instrument root (`--ghost-root`, `--swizzle-root`,
  `--assay-root`, and the folders `--stack` fills them from) must be an existing directory that holds the
  instrument's package (`ghost_buster`, `swizzle`, `assay_production`), and the interpreter, started the way the
  instrument is started, must resolve that package under the root. The module file is located, never imported. Otherwise
  nothing is run and the run fails closed exactly as it does with nothing installed: Ghost is `INCONCLUSIVE` with `ghost`
  unmeasured, SWIZZLE's contract and proofs are unconfirmed (`swizzle_sound` false, exit 2), a SWIZZLE that cannot start
  leaves ASSAY ungraded, and a bad ASSAY or Ghost root handed to `swizzle assay` leaves the key unusable. New:
  `warden.isolation.verify_root`, `locate_module`, `InstrumentRootError`, and a `packages` argument to `run_instrument`.
  A library call with no root at all (`ghost.scan(target)`) is now refused instead of using an installed Ghost.
- **`versions.assay.version` was null.** `project_version` read only a static `[project] version`; ASSAY's is dynamic.
  It now follows `[tool.setuptools.dynamic] version = {attr = "pkg.module.__version__"}` by reading the module's source
  with `ast` (a plain string literal assigned once at the top level, nothing else), without importing or running anything.
  Anything it cannot follow is still `None`, never a guess. The Watcher prints the real version.

### Changed

- The run record's `versions.ghost_tools`, `versions.swizzle` and `versions.assay` carry two new keys:
  `module` (the file the instrument's package resolved to) and `module_in_root`. They are added to what was there.
- The two ASSAY floor defaults are named and documented, and asserted by a test; **no behavior changed**. The command
  line's `--assay-floor` defaults to 3 (`warden.cli.CLI_ASSAY_FLOOR`) and the library's `TagTeam(assay_floor=...)`
  defaults to 0, floor not enforced (`warden.tagteam.LIBRARY_ASSAY_FLOOR`). README and the generated
  `docs/EXIT_CODES.md` say so.
- The `ghost` extra is pinned to ghost_tools 1.10.1 (`5d7a38638b12a75b25c84ab3652e4774acb9aa10`). `pip install -e
  ".[ghost,dev]"` resolves and `pip check` is clean (and is now a CI job).
- CI: every action is pinned by full commit SHA (checkout v4.2.2, setup-python v5.6.0). The sibling pins moved to the
  tested set: ghost_tools 1.10.1 (`5d7a38638b12a75b25c84ab3652e4774acb9aa10`), SWIZZLE 0.8.1
  (`123d7aba5d91896b6c9b381c8b0de4c89365ab81`), ASSAY 0.11.1 (`7b781cf9cb2bbc3748aaff4343d778c64dc20d8c`) and JUDGE 0.4.2
  (`51a58c01e55686c1c16a634dddd1a569cf1a98df`). The `pytest` and `circuit` jobs install the pinned Judge, so the Judge-seat
  tests run instead of skipping, and a skipped test now fails the job (`WARDEN_FAIL_ON_SKIP=1`, `tests/conftest.py`).
  The circuit job installs numpy and matplotlib (ASSAY 0.11.1 exits 1 on a skipped claim, so the answer key is not
  proven without them) and also runs the governed change under the real Judge (`tools/circuit_smoke.py --real-judge`).
  The non-blocking `assay-latest` job is kept.

### Tests

- `tests/test_instrument_roots.py`: for each of Ghost Tools, SWIZZLE and ASSAY, an installed copy in the interpreter's
  site-packages and a root that is missing, a file, a folder without the package, a package without `__init__.py`, or a
  link out to the installed copy must be refused; a good checkout still wins over the installed copy; on the command
  line, with `--stack`, and for `audit`.
- `tests/test_real_judge_loop.py`: the real Judge (JUDGE 0.4.2, which rejects internally contradictory evidence) reads
  the evidence of the real Warden loop in nine shapes (nothing to propose, one or two applied cycles, two edits in a
  cycle, a finisher only, a declined proposal, a commented-out removal) and ACCEPTs each; it does reject the same
  evidence when it is made to contradict itself on the way.
- `tests/test_versions.py`: static, dynamic-attr and unparsable versions, and the live ASSAY checkout.
- `tests/test_docs.py`: the two ASSAY floor defaults, and that the tested set agrees everywhere it is stated.
- `tests/test_skip_policy.py`: `WARDEN_FAIL_ON_SKIP=1` fails the run on a skip.

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
