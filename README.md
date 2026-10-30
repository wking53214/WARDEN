# Warden

*Formerly Elegant. Renamed in October 2026; the role is unchanged.*

The discipline of change.

Warden decides whether a change to code may be made, whether it stands once
made, and what is recorded about it. It does not decide what makes code
beautiful. That work lives in [Burnish](https://github.com/wking53214/burnish),
which plugs into Warden through one small interface.

It is not a formatter, not a linter, not a beauty scorer, and not an automatic
rewriting bot. Nothing is written without a named human.


## WHAT THIS IS

A governor, and the only thing in the stack that writes. It runs a loop. Ghost
Tools reports what is wrong, the Drafter proposes one fix, and Warden asks, in
order: did a person grant this, are SWIZZLE's own proofs sound, is the target's
test suite green, did it stay green after the change, and does Ghost agree
nothing new appeared. Any "no" stops the change or puts it back. The loop
cycles until the Drafter has nothing left to propose (or a cycle limit is
hit). Only then does Warden hand the code, once, to the Finisher, together with the facts it measured (the suite result and what Ghost still reports), so the Finisher counts and detects nothing itself. The Finisher beautifies the code and writes the final README. The Finisher's change goes through
the same gate.

Version `0.16.2` (seat contract `"1"`, unchanged). The history of every release is in
[CHANGELOG.md](CHANGELOG.md); the design is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and the exit codes in
[docs/EXIT_CODES.md](docs/EXIT_CODES.md). The seats (Judge, Drafter, Burnish) pin Warden by full commit SHA, not by
tag; each seat's `pyproject.toml` names the commit. Release tags exist up to `v0.12.0`; the `0.13.x` releases are not
tagged, and `0.14.0` is not tagged either, nor are `0.15.0`, `0.15.1`, `0.16.0`, `0.16.1` and `0.16.2`. The older `v0.10.0` tag does not match its tree (it points at a tree whose `__version__` is `0.9.0`). Tagging is
the owner's decision.

## HOW TO INSTALL AND RUN

Python 3.11, 3.12 or 3.13. The only runtime dependency is `cns`, installed from GitHub at the tag `v2.2.0`. The first two blocks of commands below were run as written in a fresh virtual environment on Python 3.12 on 2026-10-22 (from a clone of this repository), and `pip check` reported no broken requirements.

```
git clone https://github.com/wking53214/WARDEN.git
cd WARDEN
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
warden --version
pip check
```

Ghost Tools is optional. `pip install -e '.[ghost,dev]'` adds it, pinned to the commit in [STACK.md](STACK.md); without it `warden.ghost` still reads Ghost JSON produced elsewhere and treats a missing Ghost as unknown, never as clean.

Do not run `pip install warden` or `pip install cns`. On PyPI those names belong to other projects (checked 2026-10-22), not to this stack, so a bare install fetches someone else's code. Install from a checkout as above, or from the git URL. `tests/test_docs.py::test_no_document_tells_a_reader_to_install_a_bare_name_from_pypi` fails if a document in this repository says otherwise.

Observe only, which writes nothing (run it inside any clean git repository; with no Drafter named it can only look):

```
warden tagteam /path/to/a/clean/git/repository
echo $?
```

That prints one JSON document with `decision` `INCONCLUSIVE` and exits `6`, because nothing can be proposed and the instruments were not named. A governed run needs the whole circuit: see "The whole circuit in one command" below and [STACK.md](STACK.md). To exercise the circuit end to end without a project of your own, run `tools/circuit_smoke.py` (it builds a scratch repository, runs `warden tagteam` against live ghost_tools, SWIZZLE and ASSAY checkouts and the real Judge, and exits 0 only if every expectation holds):

```
python tools/circuit_smoke.py --ghost-tools DIR --swizzle DIR --assay DIR --real-judge
```

It needs the Judge installed (`pip install --no-deps` of the pinned JUDGE commit in STACK.md), and numpy and matplotlib installed normally (the versions CI uses are in `.github/workflows/tests.yml`).

To run the tests, the linter and the type checker from a checkout:

```
pip install -e '.[dev]'
pip install --no-deps "git+https://github.com/wking53214/JUDGE@<the JUDGE commit in STACK.md>"
ASSAY_ROOT=/path/to/an/ASSAY/checkout WARDEN_FAIL_ON_SKIP=1 pytest -q -rs
ruff check .
mypy
```

Count the tests with `pytest --collect-only -q`; this README states no count, because a number written here goes stale. A test skips when something it exercises is absent: the live ASSAY registry (`ASSAY_ROOT`), the real Judge seat (`judge.seat`) and `cargo`. `WARDEN_FAIL_ON_SKIP=1` turns any skip into a failure, as CI does.

**Moving from CNS `v1.9.0` to `v2.0.0`.** The pin is the tag `v2.0.0`, which peels to `b13e5d2f9e0e4291725f82794b89117c3d840ac1`. Warden imports `cns.attack`, `cns.defect`, `cns.epistemic`, `cns.finding`, `cns.seat` and `cns.suite`; of those only `cns.seat.Evidence` changed (it gained `finisher_ran`, which Warden now fills). Warden does not import `cns.stack`, the one item that broke. The suite was run against the installed `cns` 2.0.0 (`direct_url.json` names `requested_revision` `v2.0.0` and that commit).

**Moving from CNS `v2.0.0` to `v2.1.0`.** The pin is now the tag `v2.1.0`, which peels to `fde931ffa89aebec95647742256ad53033bd3d02` (Warden 0.15.1). Warden's code did not change: it already checked that `Evidence` has a `ghost_severity` field before filling it, and it writes `claim` and `evidence` into the run record as extra keys, which 2.1.0 now types. The suite was run against the installed `cns` 2.1.0.

**Moving from CNS `v2.1.0` to `v2.2.0`.** The pin is now the tag `v2.2.0`, a lightweight tag, so the tag is the commit `ce6bd05578a7a3e3cafa0cfa1e9a2cca8a5f171f` (Warden 0.16.1). The `cns` package at v2.2.0 equals v2.1.0 except its version string; the release adds a composition layer beside it that Warden does not import. Warden's code did not change. The suite was run against the installed `cns` 2.2.0.

## WHAT WORKS

Each line names the test, the CI job or the recorded run that shows it. A test file named here means the tests in it pass in CI. The CI jobs are in `.github/workflows/tests.yml`: `lint` (`ruff check .` and `mypy`), `extras` (the `ghost` extra installs and `pip check` is clean), `pytest` (one job each for Python 3.11, 3.12 and 3.13, with a skipped test counted as a failure), `circuit` (the smoke test against live siblings and the real Judge) and `assay-latest` (non-blocking: it takes ASSAY at its newest commit to show drift and gates nothing). The most recent run recorded for the previous release (0.13.9, commit `b57b81e1c98333c43d422666c89a8fcf3ae6eaca`) is GitHub Actions run 39844663962: all seven jobs concluded `success`.

- Transformation apply refuses without a grant. **VERIFIED** by `tests/test_authorization.py`.
- Ghost IDs are preserved. **VERIFIED** by `tests/test_ghost_identity.py`.
- Tag team without a grant does not write; without a drafter it only observes. **VERIFIED** by `tests/test_tagteam.py`.
- The loop cycles until the drafter runs dry, stops at the cycle limit, and notices a drafter going in circles. **VERIFIED** by `tests/test_tagteam.py`.
- The finisher runs once, only after convergence. A finishing change that breaks the suite is put back, and because the run is then not accepted, the loop's edits are put back too. **VERIFIED** by `tests/test_tagteam.py` and `tests/test_closing_false_accepts.py`.
- With `--assay-root` and `--swizzle-root`, Ghost is graded against ASSAY's answer key before anything is written; an unproven key or an ungradable specimen stops the run, and the score goes to the Judge with the floor (default 3 on the command line). **VERIFIED** by `tests/test_assay_in_loop.py`. Recorded live runs on scratch repositories: `docs/REGISTRY.json` row 3 (Ghost caught 3 of 5 known failure modes) and row 4 (5 of 7), both 2026-10-14.
- SWIZZLE's proofs failing stops the write; not configuring SWIZZLE is said out loud. **VERIFIED** by `tests/test_tagteam.py`.
- A SWIZZLE that does not declare contract 1 (`swizzle --contract`) is unmeasured and stops the write. **VERIFIED** by `tests/test_swizzle_contract.py`.
- A change that breaks the target's suite is put back; a red or empty suite means nothing is written. **VERIFIED** by `tests/test_rule7_suite_gate.py`.
- The same gate runs `cargo test` for a Rust project, reads the harness's JSON, and needs Cargo's exit status to agree; Cargo's `target/` folder is never hashed or snapshotted, and Rust manifests, `build.rs` and test files are protected. **VERIFIED** by `tests/test_rule7_cargo_runner.py`.
- Audit IDs survive reruns, are never reused, and a Fixed defect that returns is reopened under its own ID. **VERIFIED** by `tests/test_audit.py`.
- No Warden module imports Burnish, Drafter or any other repository in the stack, and none of the beautification modules remain. **VERIFIED** by `tests/test_independence.py`.
- A run that does not end accepted leaves the tree as found (rejected, not converged, suite red in a later cycle, a seat that raises or returns the wrong type). Whenever stdout takes it, the CLI prints one valid JSON document (when it cannot, see "Delivery" under LIFECYCLE). **VERIFIED** by `tests/test_closing_false_accepts.py`.
- The target cannot pose as an instrument: SWIZZLE, Ghost and ASSAY grading run in an empty directory, with absolute roots and without the current directory on the import path. Stack names (judge, assay, drafter, burnish, ghost, swizzle, ghost_tools, the warden) cannot authorize changes to Warden's own tree. **VERIFIED** by `tests/test_closing_false_accepts.py`.
- No edit, proposal or finish may touch `.git`, `.hg`, `.svn`, virtual environments, `node_modules`, `__pycache__`, `site-packages` or tool caches. A seat that changes `.git/hooks`, `.git/config` or `.git/info` is caught and the files are put back. **VERIFIED** by `tests/test_closing_false_accepts.py`.
- A Ghost id with odd characters cannot put code in a file: ids are cut down to letters, digits and `_ . : -`, on one line, 64 characters at most. **VERIFIED** by `tests/test_closing_false_accepts.py`.
- A removal a Drafter proposes is declined when the baseline suite has any skipped or xfailed test, and when the code is vendored or generated. **VERIFIED** by `tests/test_closing_false_accepts_2.py`.
- A suite that changes source files stops the run as `INCONCLUSIVE`. **VERIFIED** by `tests/test_closing_false_accepts_2.py`.
- The keep test saves the original files and the exact trap bytes outside the target and outside TMPDIR before it plants a trap. A later run restores a file only under a human grant and only if it still holds exactly the trap; a file the user changed since is left alone with a warning. Two runs on one target cannot overlap, whatever TMPDIR is, and a symlink planted at the lock, journal or state-folder name is refused. **VERIFIED** by `tests/test_closing_false_accepts_2.py`, `tests/test_round3_state_and_honesty.py`.
- A dirty git folder, a stray `.git/index.lock`, a Judge that fails, SIGTERM/SIGHUP/SIGINT, a seat shadowed from the target, stray writes to fd 1, a hung seat, and bad options are all handled with valid JSON and the tree put back, checked by running the real command on a scratch git repository. **VERIFIED** by `tests/test_cli_integration.py`.
- The suite result is pytest's exit status plus its own counts; printed text cannot forge it. **VERIFIED** by `tests/test_round3_suite_and_guard.py`.
- The protected-file list is complete, case-blind and symlink-proof, and documentation scope is true prose only. **VERIFIED** by `tests/test_round3_suite_and_guard.py`.
- Ghost gaps (missing fields, hidden baseline findings, exit 1 with nothing), the ASSAY key-proof retry and its real reason, and the honest accounting (`put_back`, `suite` unmeasured, declined proposals, empty folders, oversized trees, actor names). **VERIFIED** by `tests/test_round3_state_and_honesty.py`.
- Restores are byte for byte. CRLF files stay CRLF, and a file that is not valid UTF-8 is never edited. **VERIFIED** by `tests/test_closing_false_accepts_2.py`.
- `warden audit --authorize` will not overwrite a hand-written audit file that has no markers and will not write through a link or outside the target. **VERIFIED** by `tests/test_closing_false_accepts_2.py`.
- ASSAY's answer key arrives, or the run says why it did not. **VERIFIED** by `tests/test_assay_link.py`, including a live read when `ASSAY_ROOT` is set (CI sets it).
- Exit codes are honest: only `ACCEPT` exits 0, and each row of the table above has a test; an unknown decision never exits 0; `warden audit` exits 2 when it cannot read findings or will not write. **VERIFIED** by `tests/test_honest_exit_codes.py`.
- `unmeasured` names the instrument that was down (Ghost, suite, SWIZZLE, ASSAY) and every non-`ACCEPT` result has a one-sentence `reason`. **VERIFIED** by `tests/test_honest_exit_codes.py`.
- SWIZZLE, Ghost and ASSAY output is read strictly, a hung Ghost times out as unavailable, and garbled Ghost output after an edit puts the tree back. **VERIFIED** by `tests/test_honest_exit_codes.py`.
- The seat handshake (`requires_contract`: a mismatch or a missing declaration is refused, and the output names the `contract` and `versions`), a missing or non-folder target, an empty reason, a no-op proposal and an out-of-scope proposal are handled as described above. **VERIFIED** by `tests/test_honest_exit_codes.py`.
- `--stack` fills every root and seat from one folder, case-blind, refuses a folder with a part missing or two parts differing only by case, lets an explicit option win, and still refuses a seat inside the target; the grant's scope reaches a Drafter and a Finisher before their first call, a seat without a `scope` attribute is left alone, and one that will not take it is noted. **VERIFIED** by `tests/test_stack_option.py`.
- The whole circuit, all seven live (Ghost, SWIZZLE, ASSAY, Drafter, Judge, Burnish, through `--stack`), on a scratch repository with a dead function, a trailing-whitespace line and a stale README count: under a `code` grant the function was commented out, the whitespace tidied and the README given its generated facts section, 3 changes, Judge ACCEPT, exit 0; under a `documentation` grant the Drafter skipped the dead code with a reason and only the README changed, again ACCEPT, exit 0. Run by hand on 2026-10-14 and recorded in `docs/REGISTRY.json`; not a recorded test.
- A Judge cannot waive the ASSAY floor, the unmeasured list or the verdict's shape: a rubber-stamp ACCEPT under `--assay-floor 7` is `REJECT`, an ACCEPT with no reasons or a string return is `ERROR`, and no `--swizzle-root` is `ACCEPT_UNVERIFIED` under either scope. **VERIFIED** by `tests/test_judge_independence.py`.
- SWIZZLE attacks on the governor that could not run hold the run (`swizzle_attacks` in `unmeasured`). **VERIFIED** by `tests/test_judge_independence.py`.
- The horsemen interface, end to end: a governed run becomes a production receipt through `AssayAdapter`, `GhostToolsAdapter`, `SwizzleAdapter` and `HorsemenWorkflow`, from the library and from `warden tagteam --receipt`; an unreadable answer key is `UNKNOWN`, never "no specimens"; a SWIZZLE result Warden does not know is not a pass. **VERIFIED** by `tests/test_horsemen_circuit.py` and `tests/test_assay_link.py`.
- The target's suite is not handed the caller's credentials (a cheap hardening, not a sandbox). **VERIFIED** by `tests/test_suite_env.py`.
- Logging goes to stderr only and never into the JSON. **VERIFIED** by `tests/test_logging.py`.
- The version, the pins, the CI gates, the exit-code page and the module table agree with the code. **VERIFIED** by `tests/test_docs.py`.
- The live circuit: the real command line against ASSAY, ghost_tools and SWIZZLE at pinned commits, in CI as the `circuit` job (`tools/circuit_smoke.py`), and by hand with `python tools/circuit_smoke.py --ghost-tools DIR --swizzle DIR --assay DIR`.
- ASSAY's answer key needs numpy and matplotlib installed normally, with matplotlib's own dependencies (Pillow,
  `packaging` and the rest): `pip install numpy matplotlib`, pinned as in the CI `circuit` job. Installed with
  `--no-deps`, only 56 of the key's 60 claims are proven (one fails with `No module named 'packaging'`), ASSAY says the
  key is NOT PROVEN, and Ghost is not graded.
- The finisher's part in a run is recorded for the Judge: `Evidence.finisher_ran` is True when the Finisher's `finish` was called and False when none was seated, and a run that never reaches the Judge builds no Evidence. **VERIFIED** by `tests/test_finisher_ran.py`.
- The claim seat (`--claim-commit SHA`, with `--claim-repo PATH` when the target does not hold the commit, or `--claim-diff FILE` with `--claim-subject` and `--claim-author`) takes the Drafter seat with a real change, proposes it once and then nothing, and carries commit, parent, tree, the diff's sha256 and size and each file's sha256 before and after as evidence. A binary file, a symbolic link, a submodule, a rename or copy header, a mode change, a quoted path and a target that is not at the change's base are refused with a reason before anything runs (exit 2); `--claim-*` beside `--drafter` is a usage error. **VERIFIED** by `tests/test_claim_seat.py`.
- Every record carries a claim row (`claim`): origin, base and claimed commits and tree digests, subject, author, date, the diff's sha256 and size, the files by sha256 before and after with a `protected` flag, actor, authority, authorization and transformation ids, scope, the structured suite results, Ghost's counts, new and closed findings, the Judge's sentences (`rules_fired`), the Judge seat and verdict, decision, held digest, held tree digest, participants, and the Finisher's edits by file apart from the actor's; the Judge's whole `Evidence` rides beside it (`evidence`), and both are in the held file and the receipt. From the row alone a reader names the governed commit (its `diff_sha256` matches exactly one of a set of candidate commits) and sees the held tree as base plus the claimed diff plus the Finisher's edits, file by file and by fingerprint; the row round-trips through JSON. An ordinary Drafter run has a row with `claimed_commit` null and its files from the Transformation. **VERIFIED** by `tests/test_claim_row.py`.
- When the installed `cns.seat.Evidence` has a `ghost_severity` field (CNS 2.1.0), the Judge is told Ghost's own severity word beside each finding id, taken from the Ghost JSON and not from Warden's remap; `ghost_before` and `ghost_after` stay bare ids, and under CNS 2.0.0 nothing changes. **VERIFIED** by `tests/test_ghost_severity.py` with a stand-in Evidence class for each shape.
- A suite pass on a tree whose fingerprint this run already measured reuses that result and says so (a note, `suite_passes` with `reused_from` in the record, `pass` and `reused_from` on the row's suite results): six passes become three on a run with one change and one finishing edit; a one-byte change is measured again; reuse never reaches across runs; `--suite-always` runs every pass. **VERIFIED** by `tests/test_suite_reuse.py`.
- The Judge in the tested set (JUDGE 0.5.3, `62843b8`) turns a protected edit into `INSUFFICIENT`, so the run ends `ACCEPT_UNVERIFIED` and held, not `JUDGE_REJECTED`; the `circuit` job proves it against the live instruments: `tools/circuit_smoke.py --real-judge` runs a test-file edit under a `code` grant and requires the hold, the Judge's sentence about the changed test, nothing unmeasured, the tree put back, the result held by digest and the row's `protected` flag. Held by the `circuit` job (not a unit test); the pin text is held by `tests/test_docs.py::test_the_tested_set_is_the_same_everywhere_it_is_stated`.
- A claimed commit (the claim seat) that deletes a file or shrinks a code file is governed, not gated: the removal is applied, measured (suite before and after, Ghost before and after, Rule 7 unchanged), named in the claim row's `removals` (`path`, `kind` `deleted` or `shrunk`, `lines_before` and `lines_after` as non-blank lines, `protected`), and the run ends `ACCEPT_UNVERIFIED` with the result held for a named person even when the Judge says `ACCEPT` and nothing is unmeasured (the owner's ruling of 2026-10-30; the real Judge says `ACCEPT` on both a claimed deletion and a claimed shrink, so the hold is Warden's). The same removal proposed by a Drafter, or by the Finisher, meets the gate exactly as before; test material, Ghost's `.ghost_*` files and paths outside the project stay refused for the claim seat too; a claimed removal that lowers the pass count or turns the suite red is still put back. The row's `removals` round-trips through JSON. **VERIFIED** by `tests/test_claimed_removal.py`.
- An edit to a protected path (tests, test or build configuration, CI, dependency lists, git hooks) is applied under the grant, measured by the suite, named in the Judge's `judging_files_touched` and in the row's `files` as `protected`, and held for a named person; a protected edit that breaks the suite is still put back by Rule 7; test material, Ghost's `.ghost_*` files, paths outside the project and version control stay refused. **VERIFIED** by `tests/test_protected_hold.py`.
- An `ACCEPT` record's `reason` says what converged, what the Judge said and what was measured; a suite that turned red at a proposal or at the finishing change names its failing tests (ten at most) in the reason; the bytecode control test plants its `.pyc` where plain Python looks even when the suite runs under a cache prefix. **VERIFIED** by `tests/test_record_honesty.py` and `tests/test_stale_bytecode.py::test_the_control_plants_where_plain_python_looks_even_under_a_cache_prefix`.
- The chronicle (`--chronicle DIR`) appends one line per run to `DIR/<origin slug>.jsonl`, keyed by origin, base commit and claimed commit, with the promises the run opens if kept; a later run whose base tree is an earlier run's claimed or held tree settles those promises (HELD or BROKEN, with the measurement) and writes the settlement into its own line and its record's notes; `warden keep --chronicle DIR` appends who kept which digest and when; `warden chronicle DIR [--origin X]` prints the chain in order. A two-run chain settles `suite_green` HELD with identical counts; a run on an unrelated tree settles nothing. **VERIFIED** by `tests/test_chronicle.py`.
- Opt-in suite reuse across runs, keyed by the chronicle: with `--chronicle DIR --reuse-chronicle-suite`, the first suite pass ("cycle 1 before") takes the result an earlier run's line recorded for this run's base tree (that line's claimed or held tree digest equals the base tree digest) when the result is green (no failures, no errors, a pass, exit status 0, recorded green) and the environment key is equal on every field (Python version, pytest version, Warden version, platform, suite runner, suite command); the record's `suite_passes` and the row's `suite_before` say `reused_from` `chronicle:<run id>`, and a note says "suite pass cycle 1 before: reused the result of chronicle run <id>, tree digest <d> identical". Otherwise the suite is run, and a note says no line matched. Nothing is reused when the digest, any environment field, the runner or the green flag differs, when any line recorded a red result for the same tree and environment, for a line written before these fields existed, or for a Cargo suite; the flag is off by default and a usage error (exit 2) without `--chronicle` or beside `--suite-always`; a run with reuse ends with the same decision as one without it on the same data. A result taken from the chronicle does not settle the chronicle's own `suite_green` promise (it stays OPEN). Each chronicle line now records its run id, and per tree the suite result the run measured with its green flag and environment key. **VERIFIED** by `tests/test_chronicle_suite_reuse.py`.
- The README's named tests exist, its ledger names only releases the CHANGELOG has (on the same date), it uses none of the marketing words, and the numbers it states about the code and `docs/REGISTRY.json` are the real ones. **VERIFIED** by `tests/test_readme_ledger.py`.
- A pinned manifest may release the Drafter repository and Burnish from `--stack`: with `--stack-manifest` (or `--cns`), `drafter` and `burnish` are absent only when the manifest does not name them and the folder does not hold them, and the run says so (`released_seats`, a note, and the claim row and `participants` list only seated seats). `ghost_tools`, `swizzle`, `assay` and `judge` cannot be released; a folder that holds a seat the manifest omits, and a manifest that names a seat the folder lacks, are refused, whatever `--claim-commit`, `--claim-diff`, `--drafter` or `--finisher` supply (the folder is checked against the manifest before any option is substituted); a stack with no drafter needs `--claim-commit`, `--claim-diff` or `--drafter`; an explicit `--finisher` or `--drafter` still wins; without a manifest all six are still required. **VERIFIED** by `tests/test_stack_released.py` (`test_without_a_manifest_each_of_the_six_missing_is_a_usage_error_naming_it`, `test_burnish_alone_may_be_released_and_the_run_has_no_finisher`, `test_drafter_alone_may_be_released_when_a_claim_proposes`, `test_both_may_be_released_and_both_are_recorded`, `test_a_stack_without_a_drafter_and_without_a_proposer_is_a_usage_error`, `test_the_instruments_and_the_judge_cannot_be_released`, `test_a_folder_holding_a_seat_the_manifest_omits_is_refused_as_unnamed`, `test_a_manifest_naming_a_seat_the_folder_lacks_is_refused`, `test_a_drafter_checkout_the_manifest_omits_is_refused_whatever_option_supplies_the_seat`, `test_a_burnish_checkout_the_manifest_omits_is_refused_with_an_explicit_finisher`, `test_both_checkouts_the_manifest_omits_are_named_together_whatever_supplies_them`, `test_a_drafter_checkout_the_manifest_names_runs_with_a_claim`, `test_a_manifest_naming_a_seat_the_folder_lacks_is_refused_even_with_an_explicit_option`, `test_an_explicit_finisher_wins_over_a_released_burnish`, `test_an_explicit_drafter_wins_over_a_released_drafter`).
- The claim row's `new_findings[].severity` is Ghost's own word (critical, major, minor, informational), the same word the Judge receives in `evidence.ghost_severity`; Warden's remapped word is `warden_severity` in the same entry. **VERIFIED** by `tests/test_ghost_severity.py::test_the_claim_rows_new_finding_carries_ghosts_word_and_the_judge_sees_the_same_word`.
- No document tells a reader to `pip install` a bare name from this stack. **VERIFIED** by `tests/test_docs.py::test_no_document_tells_a_reader_to_install_a_bare_name_from_pypi`.

## WHAT DOES NOT WORK / NOT PROVEN

- **Warden makes no change by itself.** With no Drafter it cannot propose anything, and without a Judge a run is never a plain `ACCEPT`.
- **The loop has not been run live on a repository outside the circuit.** `docs/REGISTRY.json` records runs on scratch repositories built for the run (rows 1 to 4) and two rows (5 and 6) in which `warden tagteam --stack` governed fresh clones of the circuit's own repositories (see SELF-HOSTING). These are self-reported rows written by the people who ran them, not independent records, and none is a third-party repository. A live `ghost-buster` + `warden tagteam` + `swizzle prove` run on a corpus repository outside the circuit is not recorded.
- **A plain `ACCEPT` does not mean Ghost ran every check.** Checks the caller declines are listed under `ghost_scan.declined` and change nothing by design. On 2026-10-22 a governed run against ghost_tools 5a9154d ended a plain `ACCEPT`, exit 0, `unmeasured` empty, with seven declined checks (`mutate`, `kernel`, `structure`, `tests`, `project`, `secrets`, `correlate`). Read with `cns.run.RunRecord`, that record has seven `gaps()` and is not `clean`. A reader who looks only at `decision` and `unmeasured` is told "nothing missing". Since ghost_tools 1.10.11 a governed run declines eight checks, not seven (the same seven plus `ledger`), because ghost_tools lists the ledger as declined when Warden calls it with `--no-ledger`; Warden did not decline a new check. The seven above are the 2026-10-22 record and stay as recorded.
- **A Rust project has no recorded live run.** The `cargo test` gate is held by `tests/test_rule7_cargo_runner.py` and nothing else.
- **No run on macOS or Windows.** CI uses `ubuntu-latest` only.
- **No recorded run in which a real Judge reads `finisher_ran`.** Warden fills the field and `tests/test_finisher_ran.py` holds that with a stand-in Judge; the JUDGE version in the tested set does not use it yet.
- **SWIZZLE's attacks on the governor have been reported as "not run" under heavy machine load.** The cause was not found and no test here reproduces it. What Warden does when they do not run is held: the run is `ACCEPT_UNVERIFIED` (`tests/test_judge_independence.py::test_attacks_on_the_governor_that_did_not_run_hold_the_run`). The count of occurrences comes from audit notes kept outside this repository and is not verified here.
- `WARDEN_AUDIT.md`'s design analogy, layer map and invariants are written by a person; Warden leaves them `UNKNOWN` rather than invent them.
- Beauty is not scored here or anywhere in the corpus.
- **The claim seat expresses a change as writes and deletes of UTF-8 text.** Renames, binary files, symbolic links, submodules, mode changes and a target not at the change's base are refused before anything runs. The reading of `--claim-diff` is Warden's own small unified-diff applier: context must match exactly, nothing is fuzzed.
- **Suite reuse trades one kind of information for time.** A pass that reuses an earlier result on an identical tree cannot notice a test that fails one time in thirty on an unchanged tree (the falsifier's run 07 was such a case). `--suite-always` buys that information back at the old cost. The same holds for `--reuse-chronicle-suite`, which extends reuse across runs.
- **`--reuse-chronicle-suite` trusts the chronicle file, and the file is not protected.** The chronicle is an ordinary unsigned text file, so whoever can edit it can make this flag skip a suite run: a line that says a tree was green under a matching environment key is taken at its word, and nothing here checks that the suite ever ran. Use the flag only where that person is trusted. Warden adds no signing and no tamper detection to the chronicle. The environment key names the interpreter and pytest versions, Warden's version, the platform, the runner and the command; it does not cover the target's own dependencies, plugins or configuration, so a result recorded under one set of those is reused under another that differs. Only a pytest suite is reused; a Cargo suite is always run.
- **The chronicle settles only trees with identical fingerprints, and only when a later run happens.** A kept result opens promises that stay OPEN until a run is made on that tree; a declined check is OPEN until it is measured or 90 days pass. Settlement needs this run's first suite pass and first Ghost scan: without Ghost the finding promises stay OPEN. Nothing is signed or anchored; a chronicle file is as trustworthy as the folder it sits in.
- **`claim`, `evidence`, `suite_passes` and `chronicle` are written as keys of the `cns.run/1` record.** The pin is `v2.2.0`, which types `claim` and `evidence` (`RunRecord.claim`, `RunRecord.evidence`); `suite_passes` and `chronicle` stay extra keys, which every CNS version allows and ignores. `Evidence.ghost_severity` is filled only when the installed CNS has that field, which 2.1.0 and later do and 2.0.0 does not.
- **What is still not governed about removals.** The hold on a claimed removal is Warden's alone; no Judge rules on removals, and the one probed (2026-10-30, the real Judge on a throwaway repository, Warden's gate stepped over for the probe only) says `ACCEPT` on a claimed deletion and on a claimed shrink. A shrink is counted in non-blank lines of the whole file, so a commit that deletes a function and adds a comment or code of the same length in the same file is not a shrink and is not named; a deletion of a prose file is a removal, a shrink of a prose file is not. A removal by a Drafter still goes through the keep test and is commented out, never deleted, and one by a Finisher is refused; neither is held as a removal. The Judge's own `changed` list shows a deletion as kind `delete` and a shrink as a plain `write`, so a Judge cannot tell a shrink from any other edit without reading the row.
- **ASSAY stays a required instrument.** `--stack` cannot release `assay` (nor `ghost_tools`, `swizzle` or `judge`): the Judge uses ASSAY's grade of Ghost, and what an ungraded Ghost should mean is a Judge ruling not made here.

## KNOWN DEFECTS

Open ones only. Where a line says "Reproduced", it was run on 2026-10-22.

- **The dirty check sees what git reports for tracked and not-ignored files, and nothing else.** A file in a seat or instrument checkout that git ignores (a pattern in the repository's `.gitignore`) or that `.git/info/exclude` lists is not seen, so a checkout can be clean and at its pinned commit while it holds such a file. The check turns off the user's and the system's git configuration, but `.git/info/exclude` lives in the repository and git reads it. Reproduced: a repository with `planted.py` listed in `.git/info/exclude` and an untracked `planted.py`: `warden.gitstate.is_dirty` returned `False`. The class is any ignored or excluded file that Python imports or executes, or that a seat reads or starts: a `.py` the checkout does not track, a compiled extension, a data file, an executable. The easiest member, an unchecked-hash `.pyc` planted in an ignored `__pycache__`, is closed since 0.13.10 (see Bytecode under LIFECYCLE); the rest of the class is open. A `.pyc` with no `.py` beside it (a sourceless module) is also not covered by the bytecode fix. No test, because the behaviour is not fixed.
- **Warden's own modules, and `cns`, are imported before the private bytecode cache exists.** `python -m warden.cli` loads `warden.*` and `cns.*` before `main` runs, so a planted `.pyc` in Warden's own checkout or in the environment's `cns` is read as before. The governor is the trusted part, and this is a description of the edge of the fix, not a case anyone reproduced.
- **The neutral git configuration has two costs.** A folder owned by another user is reported unreadable (the run is refused) because `safe.directory` is no longer taken from the user's configuration (reproduced: `tree_state` returned `unknown` for a folder owned by `nobody`). A filesystem that cannot hold the executable bit shows as dirty (stated in the 0.13.8 change; not reproduced here). No test of either.
- **`ghost_scan.gaps` is cut at 10 entries and `declined` at 20** (`warden/tagteam.py`). The count of the unlisted gaps is in `gaps_not_shown`, which `cns.run.RunRecord.gaps()` does not read, so a record with more than ten gaps lists ten.
- **`versions.seats.*` has `commit` and `dirty` null for a seat that is not in a git checkout of its own** (a stand-in seat in a temporary folder, an installed copy). Null means unknown, and `RunRecord.dirty_parts()` does not count a null as dirty. No test.
- **Without a Judge, the printed record does not say whether the Finisher was called.** Since 0.14.0 the record carries the Judge's `Evidence` whole (`evidence`, `finisher_ran` included) whenever a Judge was seated. With no Judge no Evidence is built, and the record carries `finished` (whether a finishing change stands) and `versions.seats.finisher` (whether one was loaded), so "loaded and had nothing to do" and "loaded and never reached" look the same to a reader of that record.
- The target's own test suite still runs inside the target, with the target's code. A hostile suite can do anything the user can do. Warden notices a suite that rewrites source files, but not one that does something else. Two cheap hardenings exist and are all there is: the suite has a time limit (`--suite-timeout`, killed as a process group) and is not handed credential-named environment variables (`warden.isolation.suite_env`; `PYTHONPATH` and the rest of the environment are kept, and `WARDEN_SUITE_ENV_PASSTHROUGH=1` turns it off). It is not sandboxed: it can still read files, use the network, and read credentials from disk.
- The tree watch around each seat compares bytes for source files and name, size and time for files under `.venv`, `venv`, `env` and `node_modules` (a write there is reported and the run is `REJECT`ed; a file added there is removed, but a file changed there is not put back, since those folders are watched, not copied). Pure caches (`__pycache__`, `.ruff_cache`, `.pytest_cache`, `.mypy_cache`) are not watched at all. The suite never reads `__pycache__` from the tree (it runs with `PYTHONPYCACHEPREFIX` elsewhere), so a planted `.pyc` cannot change a suite result, but a later run by the user could pick one up.
- The instrument root check is made just before each instrument is started, not while it runs, and it cannot see inside an instrument that starts another: Ghost and ASSAY, when SWIZZLE grades one against the other, are checked by Warden for their root, package, location, commit and version but are loaded by SWIZZLE's own path rules. With `--swizzle-root` and `--assay-root` but no `--ghost-root`, SWIZZLE grades whichever Ghost it finds by its own rules (`$GHOST_TOOLS`, a sibling checkout, an installed `ghost_buster`), and Warden does not check that one: it names no Ghost root, so it runs no Ghost scan and `ghost` is unmeasured, which keeps the run from being a plain `ACCEPT` (at best `ACCEPT_UNVERIFIED`). The root has to be a real directory: a package that is a link to a copy elsewhere resolves outside the root and is refused. `audit --ghost-root` has no `--allow-uncommitted-instruments`: a Ghost it cannot name is always refused there.
- An instrument checkout (`--ghost-root`, `--swizzle-root`, `--assay-root`, or one found by `--stack`) that is the governed folder, lies inside it, or contains it (the target is a subfolder of the instrument's checkout, such as SWIZZLE's package folder) is refused before anything runs (`SEAT_NOT_LOADED`, exit 2), like a seat loaded from inside the target: the run could edit the thing measuring it. A seat is checked in the one direction that matters for it, its code being inside the target. Govern a clone of an instrument's repository, with the instruments seated from another checkout.
- The seats run inside Warden's own process. The watch catches a seat that writes the tree; it cannot catch a seat that changes Warden's own objects in memory. A seat is trusted code that is checked, not sandboxed.
- Only the keep test is protected from SIGKILL by the journal. If Warden is killed that way at another moment, edits it had already applied stay on disk, and the next run does not know about them (in a git folder they show as uncommitted changes, so the next run is refused until you deal with them). SIGTERM, SIGHUP and SIGINT are handled.
- The seat timeout uses a timer signal in Warden's main thread, so it interrupts Python code and most waits, but a seat stuck inside a C call that never returns to Python can still outlast it.
- The lock is advisory and works on one machine. It stops two Warden runs, not a person editing at the same time (a dirty git folder is refused at the start, but a person can still edit during a run).
- A tree over 200 MB cannot be snapshotted, so Warden refuses to write to it (`INCONCLUSIVE`) rather than risk leaving a failed run's edits behind.
- The forbidden, vendored and fixture directory lists go by folder name. A real source folder named `env`, `gen`, `build`, `vendor`, `corpus`, `golden` or `fixtures` will not be edited. Fixture folders (`fixtures`, `specimens`, `testdata`, `golden`, `snapshots`, `corpus`) are refused even for a whitespace-only tidy: the circuit once reformatted ASSAY's own specimens, and only the suite's recorded hashes caught it.
- A suite with skipped or xfailed tests blocks every removal a Drafter proposes, even for code those tests do not touch (a claimed commit is not blocked by it: it is applied and held). That is on purpose: Warden cannot tell which code they would have covered.
- Files that are not valid UTF-8 are reported at most by Ghost and are never edited.
- Ghost Tools does not flag a documented test count larger than the suite;
  `doc_test_count_drift` only reports a count the suite has grown past.
- Ghost reports how many files it scanned only on its error stream (`scanning N file(s)`), not in its JSON. Warden reads that line; if Ghost stops printing it, Warden cannot tell a clean tree from an empty one, except when Ghost itself exits with an error.
- A run whose only proposals were all declined as out of scope ends as `ACCEPT` or `ACCEPT_UNVERIFIED` with nothing changed; the cycle records say `DECLINED`, and the Judge sees them.
- `versions` reports what it can read from files (`.git`, `pyproject.toml`, installed package metadata). A checkout that is not a git folder, or a seat installed without version information, shows `null` for that field. SWIZZLE finds Ghost and ASSAY itself (`$GHOST_TOOLS`, `$ASSAY`, a sibling folder) when Warden does not pass them; in that case Warden does not know which copy SWIZZLE used.
- A seat is loaded by putting its folder on `sys.path` inside Warden's own process (`warden.cli`), after `''` and the target are taken off it. That is the in-process seat limit above, not a sandbox.
- The live Ghost scan shells out to `python -m ghost_buster.cli`. That is a process boundary, not a typed import, because Warden must not become Ghost Tools.
- `docs/PHASE0_INVENTORY.json` and the first registry row describe the pre-split Warden. They are history and say so.
- The full local suite takes minutes because most tests start real `pytest` and `warden` processes.

## WHAT BROKE AND HOW IT WAS FIXED

Newest first, from `CHANGELOG.md`, `git log` and the tests. "Prevented by" names the test that fails if the defect comes back; "no test yet" means none exists. The CHANGELOG does not always say how a defect was found, so this section says it only where the CHANGELOG or a commit message does. Three entries (0.13.4, 0.13.6, 0.10.1) record a fix that was incomplete, reversed or described wrongly the first time.

- **0.16.2 (2026-10-30), a folder holding a seat the manifest omits was accepted when an option supplied the seat.** Found by the Stage 2 run: with a manifest that omits `drafter`, a `--stack` folder that still held a drafter checkout was refused on a bare `--stack` but accepted with `--claim-commit`, `--claim-diff` or `--drafter` (and the same for `burnish` with `--finisher`), although the text above says it is refused. The folder was compared with the manifest only for a seat whose option was still unset, and those options had already set it. Now the comparison is made before any option is substituted. A manifest that is not one this Warden accepts (wrong schema or contract, or no repositories) is treated as no manifest for this comparison, so its own problem is the one reported. The governed target itself is not counted as a held seat, as everywhere else. Prevented by `tests/test_stack_released.py::test_a_drafter_checkout_the_manifest_omits_is_refused_whatever_option_supplies_the_seat` and `::test_a_burnish_checkout_the_manifest_omits_is_refused_with_an_explicit_finisher`.
- **0.15.0 (2026-10-29), the claim row said "medium" where the Judge saw "minor".** Found by the 2026-10-28 proof run: the row's `new_findings[].severity` carried Warden's remapped word (critical, high, medium, low) while the Judge received Ghost's own word in `evidence.ghost_severity`, so one finding had two names in one record. The row now carries Ghost's word as `severity` and the remapped word as `warden_severity`. Prevented by `tests/test_ghost_severity.py::test_the_claim_rows_new_finding_carries_ghosts_word_and_the_judge_sees_the_same_word`.
- **0.14.0 (2026-10-28), the held record could not name the change it held.** Found by the falsifier's held runs (sim9/A_CLAIM_ROW.md): `held_digest` covers every file of the tree, the receipt's before and after revisions were both the parent, and `files_changed` mixed the actor's files with the Finisher's, so a stranger with the record could not say which commit was governed. The record now carries the claim row and the Judge's Evidence. Prevented by `tests/test_claim_row.py::test_the_diff_digest_names_exactly_one_of_the_candidate_commits` and `::test_the_held_tree_is_base_plus_the_claimed_diff_plus_the_finishers_edits`.
- **0.14.0, a red suite's record did not name the failing test.** Found by the falsifier's run 07 (one failed test in the sixth of six passes on an unchanged tree; the record said only "1 failed"). The pytest plugin now reports the first ten failing ids and the INCONCLUSIVE and FINISH_REJECTED sentences carry them. Prevented by `tests/test_record_honesty.py::test_a_red_suite_at_a_proposal_names_the_failing_test_in_the_reason` and `::test_a_finishing_change_that_breaks_the_suite_names_the_failing_test`.
- **0.14.0, the bytecode control test proved nothing under a cache prefix.** Found by self-hosting run 3: when this suite runs under Warden's own `suite.py`, `PYTHONPYCACHEPREFIX` is set, `cache_from_source` sent the planted `.pyc` under the prefix, and the control test (plain Python loads the planted file) failed for a reason unrelated to the fix. The control now plants where plain Python looks and gives its subprocess an environment without the prefix. Prevented by `tests/test_stale_bytecode.py::test_the_control_plants_where_plain_python_looks_even_under_a_cache_prefix`.
- **0.13.10 (2026-10-24), a planted `.pyc` in a vetted seat ran inside a governed run.** Found by the round-6 audit (2026-10-23 and 24). An unchecked-hash `.pyc` placed in the ignored `__pycache__` of a clean stack checkout of JUDGE is loaded by Python in place of the source; `git status` stayed clean, the dirty check passed, the tampered code ran, and the run ended `ACCEPT`. Now `main` runs inside a fresh private bytecode directory and instruments are started with one (see Bytecode). The wider hole stays open (see KNOWN DEFECTS: any other ignored or excluded file Python imports or executes). Prevented by `tests/test_stale_bytecode.py::test_warden_runs_the_source_not_the_planted_pyc_in_a_vetted_seat` and `::test_an_instrument_subprocess_does_not_read_a_planted_pyc`, which build a real tampered `.pyc` with `py_compile` in a folder they create.
- **0.13.10, the record named an older installed copy of a seat.** Found by the 2026-10-23 self-hosting runs and the round-6 audit. `versions._installed` preferred pip's install record over the checkout the module was loaded from, so a venv that still held an older JUDGE or Burnish made the record name the old release (the first self-hosting run named an older finisher than the one that ran). The record now names the checkout. Prevented by `tests/test_versions_precedence.py::test_a_seat_in_a_stack_checkout_reports_the_checkout_not_the_older_installed_copy`.
- **0.13.10, a gone reader of stdout gave a traceback and the wrong exit code.** Found by the round-6 audit: `warden tagteam DIR | head -c0` printed a `BrokenPipeError` traceback and exited 1 where the run had earned 6, or 120 when buffered. Prevented by `tests/test_report_delivery.py::test_a_reader_that_left_keeps_the_earned_exit_code`.
- **0.13.10, statements that were not true.** Found by the round-6 audit. Comments and documents called the sibling pins "the head of" a repository's `main` or branch (JUDGE `e5c3f98` is not the head of JUDGE's `main`), the README said no CNS status page was known to exist and recorded no fresh self-hosting run, and it gave an unmeasured run time. Prevented by `tests/test_readme_ledger.py::test_no_document_calls_a_pin_the_head_of_a_main_or_a_branch` and `::test_the_self_hosting_paragraph_cites_the_cns_record_and_its_numbers`.
- **0.13.8 (2026-10-22), a manifest that named only some of the stack.** `--stack` uses every one of its folders as an instrument root or a seat, but the manifest check looked only at the names the manifest listed. A manifest `{"DRAFTER": sha}` with a modified, unpinned JUDGE seat ended `ACCEPT` and the modified Judge ran. Now a stack run exits 2 when a folder it uses is not named, is at another commit, or has uncommitted changes. The same release stopped a clone of the target at the same commit as a stack member from skipping that member's dirty check. Prevented by `tests/test_stack_option.py::test_a_manifest_that_does_not_name_a_used_folder_runs_nothing`, `::test_a_dirty_seat_is_refused_even_when_the_manifest_covers_it_and_the_commit_matches` and `::test_a_clone_of_the_target_at_the_same_commit_is_skipped_as_a_join_but_still_vetted`.
- **0.13.8, the dirty check depended on who asked.** `git status --porcelain` honours the user's git configuration and index flags, so `git update-index --assume-unchanged` or `--skip-worktree` on a modified seat file, a global `status.showUntrackedFiles=no`, a global `core.excludesFile`, or `core.fileMode=false` each made a tampered seat look clean. Warden now runs git with no user or system configuration and refuses a file flagged `assume-unchanged` or `skip-worktree`. Prevented by `tests/test_gitstate_strict.py::test_assume_unchanged_hides_an_edit_from_git_and_not_from_warden`, `::test_skip_worktree_hides_an_edit_from_git_and_not_from_warden`, `::test_a_global_show_untracked_files_no_does_not_hide_a_planted_file`, `::test_a_global_excludes_file_does_not_hide_a_planted_file` and `::test_file_mode_false_does_not_hide_a_chmod`. Not closed: `.git/info/exclude` (see KNOWN DEFECTS).
- **0.13.8, a target inside an instrument checkout was accepted.** Only the other direction (an instrument inside the target) was refused. Prevented by `tests/test_cli_integration.py::test_a_target_inside_an_instrument_checkout_is_refused_before_anything_runs`.
- **0.13.8, a file written by rename could replace a special file.** `--receipt` is written under a temporary name and renamed into place, so naming a pipe, a device node or a folder would have replaced it; `warden audit --authorize` blocked on a pipe. Now refused before anything runs. Prevented by `tests/test_horsemen_circuit.py::test_a_receipt_named_as_a_special_file_is_refused_before_anything_runs` and `::test_a_fifo_named_as_the_audit_file_is_refused_not_waited_on`.
- **0.13.8, the documents overstated a red suite.** README and `docs/EXIT_CODES.md` said a suite that is red from the start is `INCONCLUSIVE`, exit 6. That is true only when the Drafter proposes; with nothing to propose the run ends `FINISH_REJECTED` or `JUDGE_REJECTED`, exit 1. No code changed. Prevented by `tests/test_red_suite_from_the_start.py::test_the_documents_say_what_the_code_does_about_a_red_suite`.
- **0.13.7 (2026-10-21), a stack manifest pin could be a prefix.** A pin of 7 or more characters was accepted, so a manifest that pinned ghost_tools to `c2ada82` ended `ACCEPT`. Now the pin must be the full 40 lowercase hex characters and equal the checkout's commit. Prevented by `tests/test_stack_option.py::test_a_manifest_pin_must_be_the_whole_commit_exactly`.
- **0.13.7, a dirty joined checkout was accepted.** A modified JUDGE seat that wrote a marker file still ended `ACCEPT`, with `judge.dirty: true` recorded and ignored. Prevented by `tests/test_stack_option.py::test_a_joined_checkout_with_a_modified_tracked_file_is_refused`.
- **0.13.7, documents.** The README named `v0.11.4` as the newest tag while `v0.12.0` existed; STACK.md left a code fence open through the paragraph after its command; the CI workflow had no `permissions:` block; the ASSAY dependency note was missing (installed with `--no-deps`, 56 of the key's 60 claims hold and the key is not proven). Prevented by `tests/test_docs.py::test_the_tags_are_described_without_claiming_a_release_that_is_not_tagged`, `::test_the_markdown_code_fences_are_balanced_and_a_fence_ends_where_its_commands_end`, `::test_the_workflow_token_is_read_only` and `::test_the_docs_say_assay_needs_matplotlibs_dependencies_installed`.
- **0.13.6 (2026-10-21), the CNS pin changed spelling twice in two releases.** 0.13.5 kept CNS as a full commit SHA and said pip would not resolve a tag URL together with a SHA URL; 0.13.6 switched to the tag `v1.9.0` because the circuit settled on one spelling that CNS's `seat_pins` check compares as text. The same two releases repointed the ASSAY pin twice: ASSAY's work was squash-merged, so the first pin was no longer on ASSAY's `main`. Prevented, for the spelling and for the pins agreeing with each other, by `tests/test_docs.py::test_the_tested_set_is_the_same_everywhere_it_is_stated`. No test yet checks that a pinned sibling commit is reachable from that sibling's `main`.
- **0.13.4 (2026-10-21), an installed copy could still be named as an instrument root.** 0.13.2 had closed the case of a missing or wrong root; `--ghost-root $VENV/lib/python3.13/site-packages` (a real `ghost_buster` inside) still ended `ACCEPT`, exit 0, with `commit` and `version` null. A root is now also refused when it is, or lies inside, `site-packages` or `dist-packages` or the interpreter's own folders, and when Warden cannot name it (no commit of its own or no readable version). Prevented by `tests/test_instrument_roots.py::test_the_audits_run_with_site_packages_as_both_roots_is_not_an_accept`.
- **0.13.4, smaller ones.** `swizzle_sound` was null when Ghost failed after SWIZZLE's proofs had held (`tests/test_instrument_roots.py::test_a_bad_ghost_root_beside_a_good_swizzle_still_says_whether_the_proofs_held`). Reasons were cut mid-word (`tests/test_messages.py::test_a_long_reason_is_cut_at_a_word_with_a_marker_never_mid_word`). A garbage `--from-ghost` file gave "Warden failed with JSONDecodeError" (`tests/test_messages.py::test_a_findings_file_that_is_not_json_is_named_and_explained`).
- **0.13.3 (2026-10-21), the circuit smoke job failed in CI and passed locally.** `tools/circuit_smoke.py` runs Warden from a temporary folder, so the relative roots the CI job passed (`_circuit/ghost_tools` and the like) pointed nowhere. Fixed by resolving the roots when the arguments are parsed. Prevented by `tests/test_circuit_smoke_args.py::test_relative_roots_become_absolute_when_the_arguments_are_parsed`.
- **0.13.2 (2026-10-17), an installed copy stood in for a missing root.** With Ghost Tools installed, `--ghost-root /nonexistent` still scanned, and with SWIZZLE installed `--swizzle-root /nonexistent/swz` reported "12 of 12 proofs hold" with `swizzle_sound` true. Dropping `PYTHONPATH` (0.10.0) had not been enough because site-packages stays importable. Prevented by `tests/test_instrument_roots.py::test_a_bad_root_is_refused_although_the_package_is_installed`.
- **0.13.2, a skipped test could not turn CI red.** Tests skip when the real Judge, the live ASSAY registry or `cargo` is absent, and CI did not install the Judge, so the Judge-seat tests skipped there and a break in that link could go unseen. CI now installs the pinned Judge and `WARDEN_FAIL_ON_SKIP=1` makes a skip fail the job. Prevented by `tests/test_skip_policy.py::test_a_skip_fails_the_run_when_enforced_and_names_the_test_and_why`.
- **0.13.2, `versions.assay.version` was null** because ASSAY's version is dynamic and Warden read only a static one. Prevented by `tests/test_versions.py::test_a_dynamic_attr_version_is_read_from_the_module_like_assays`.
- **0.13.1 (2026-10-17), an unconfirmed SWIZZLE was read anyway.** Warden now asks `swizzle --contract` and requires `name` `swizzle` and `contract` 1 before reading anything else; a SWIZZLE that cannot answer leaves the proof gate unmeasured. Prevented by `tests/test_swizzle_contract.py::test_a_run_against_an_unconfirmed_swizzle_writes_nothing_and_says_why`.
- **0.13.0 (2026-10-17), a Judge's ACCEPT could waive Warden's own checks.** A stub Judge returning ACCEPT left changes standing under `--assay-floor 7`; a verdict with no reasons was accepted; SWIZZLE attacks that did not run did not hold the run; the target's suite received the caller's credentials; the Four Horsemen `SwizzleAdapter` counted an unknown result as a pass; and `try_import_shared_contracts` imported a module that does not exist. Prevented by `tests/test_judge_independence.py::test_a_floor_the_score_does_not_meet_is_enforced_by_warden_not_the_judge`, `::test_a_verdict_with_no_reasons_is_an_error_whatever_its_label`, `::test_attacks_on_the_governor_that_did_not_run_hold_the_run`, `tests/test_suite_env.py::test_a_real_suite_never_sees_the_callers_token`, `tests/test_horsemen_circuit.py::test_a_swizzle_result_warden_does_not_know_is_not_a_pass` and `::test_the_dead_shared_contracts_stub_is_gone`.
- **0.13.0, a wrong number in the README.** It stated 535 tests while 571 passed. The README no longer states a test count. Prevented by `tests/test_docs.py::test_the_readme_states_no_test_count_that_could_drift`.
- **0.11.2 (2026-10-15), two refusals the circuit's first run on its own repositories showed were missing.** Warden refused a seat loaded from inside the target but not an instrument root (SWIZZLE ran on itself in place), and Burnish's whitespace tidy reformatted ASSAY's specimen files, which only the suite's recorded hashes caught (`docs/REGISTRY.json` row 5). Prevented by `tests/test_cli_integration.py::test_an_instrument_checkout_inside_the_target_is_refused_before_anything_runs` and `tests/test_seams.py::test_a_whitespace_tidy_of_a_fixture_is_refused_even_though_it_is_format_only`.
- **0.10.1 (2026-10-12), a tag that did not match its tree.** The `v0.10.0` tag points at a tree whose `__version__` is `0.9.0`. The commit that set the version to 0.10.1 said the opposite ("the v0.10.0 tag reports 0.10.0 in its code"); the tree says otherwise, and the README and CHANGELOG now say what the tree says. No test of tag against tree; `tests/test_docs.py::test_the_tags_are_described_without_claiming_a_release_that_is_not_tagged` holds the sentence only.
- **0.10.0 (2026-10-12), a failed save of a held result left the changes standing.** If saving an `ACCEPT_UNVERIFIED` result failed, the run returned early with the proposed edits on disk. Now the restore is still attempted and a failure of either ends the run as `ERROR`. Prevented by `tests/test_held_results.py::test_a_failed_held_save_still_puts_the_tree_back_and_is_an_error`.
- **0.10.0, a missing instrument root fell back to a sibling.** Inherited `PYTHONPATH` entries let a sibling checkout on the caller's path stand in for a root that was missing, and the result was reported as if it came from the root named; five tests failed under the full environment because of it. Instruments now get only their named roots. This fix was incomplete (see 0.13.2). Prevented by `tests/test_instrument_roots.py`.
- **0.9.0 (2026-10-10), round 3 red-team holes.** A dirty folder was not refused, a suite's printed text could forge a pass, the protected-file guard and the keep-test journal had gaps, and the Judge's handling and the seat checks were loose. Prevented by `tests/test_round3_state_and_honesty.py` and `tests/test_round3_suite_and_guard.py`.
- **0.8.0 (2026-10-09), eleven false accepts.** A red-team round found eleven ways a run could end `ACCEPT` wrongly; they were closed together. Prevented by `tests/test_closing_false_accepts.py` and `tests/test_closing_false_accepts_2.py`.

## SELF-HOSTING

`docs/REGISTRY.json` rows 5 and 6 record the circuit governing fresh clones of its own repositories with `warden tagteam --stack`. Row 5 is dated 2026-10-14: a `ACCEPT` for JUDGE, BURNISH and DRAFTER, held `ACCEPT_UNVERIFIED` results for SWIZZLE and WARDEN, ASSAY `FINISH_REJECTED` and then held, and ghost_tools `INCONCLUSIVE` twice and then held. Row 6 follows the CHANGELOG's 2026-10-15 for Warden 0.11.2 (the row's own text says 2026-10-14): with every sibling joined for Ghost, WARDEN ended `ACCEPT` and SWIZZLE, ASSAY and ghost_tools were held. The clones' changes were not kept. Both runs were made by the people who wrote the code, both predate Warden 0.13.0, and the refusals added since (full-commit manifest pins, dirty stack folders, the strict dirty check, instrument roots that must be real checkouts) did not exist then. They do not describe the current rules.

A fresh run is recorded in the [CNS repository](https://github.com/wking53214/CNS), in `docs/evidence/SELFHOSTING_2026-10-23.md` (with the raw records beside it and the summary in `docs/STATUS.md`; both are on the CNS branch `claude/horsemen-production-status-5wsndb` until it is merged). It covers 2026-10-22 to 2026-10-23, the circuit over each of its own eight repositories at their final commits. For this repository (WARDEN 0.13.9, commit `b57b81e`) it is one run: decision `ACCEPT`, exit 0, 4165 seconds, a suite of 953 passed and 2 skipped before the change (the two skips are the live ASSAY checks, because `ASSAY_ROOT` was not set), Ghost reporting 93 findings at the start and 93 at the end with none new, and seven gaps, the same seven declined checks (`mutate`, `kernel`, `structure`, `tests`, `project`, `secrets`, `correlate`). It ran under Burnish 0.3.11 and was not re-run under 0.3.12; the README section Burnish wrote (23 lines) was kept in the throwaway clone and no person reviewed it.

What that record does not mean: an `ACCEPT` here carries seven gaps. It does not mean there are no secrets, no weak tests, no mutation survivors and no structural problems, because those checks did not run, and it does not mean Ghost's 93 standing findings were looked at. It describes WARDEN 0.13.9, not this version. The same audit found one defect in this repository's record: in SWIZZLE's second run the record named the finisher from the pip install record (Burnish 0.3.11) although 0.3.12 was the code that ran. That is fixed in 0.13.10 (see the ledger).

## CEILINGS CODE CANNOT FIX

- **Young.** The first commit is dated 2026-10-04 (`git log --reverse`), under the name Elegant; the rename to Warden is 2026-10-08.
- **One human maintainer**, William King. A large share of the commits are authored by an AI assistant (`git shortlog -sn --all` shows the split). Nobody else is recorded as having reviewed the code.
- **No outside users are known.** Nothing in this repository records anyone using it besides the owner.
- **Releases are tagged by the owner**, not by CI and not by a change. Check the repository's tags and releases on GitHub for what exists.
- **Every pin is a snapshot.** The sibling commits in [STACK.md](STACK.md) are the last set this repository's CI tested on its own, not the heads of anything, and CNS is pinned by the tag `v2.2.0`. Whether the landing set works together is checked by the `stack` job in the CNS repository.
- **The registry rows are self-reported** by the people who ran them (see SELF-HOSTING).

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
- The human authorization boundary (`UNKNOWN` is not `APPROVED`; Warden cannot authorize itself)
- Rule 7, the test gate: the target's own suite before and after every write
- Rule 9, the audit file: `WARDEN_AUDIT.md`, Ghost findings under IDs that never change meaning
- The SWIZZLE proof gate: SWIZZLE's own proofs must hold before anything is accepted
- The tag-team loop that *calls* Ghost Tools, SWIZZLE, a Drafter and a Finisher without becoming any of them
- The Four Horsemen interface: typed handoffs between ASSAY, Ghost Tools, SWIZZLE and Warden. Warden's own command line drives it through `--receipt`; ASSAY's tests import `AssayAdapter`; Judge, Drafter and Burnish do not import it (they import `warden.models`, `warden.roles` and `warden.authorization` only)

## WHAT IT DOES NOT OWN

- Which fix to propose (Drafter), and the beautifying and final README (Burnish)
- Forensic detectors, ledgers, mutation (Ghost Tools)
- Independent oracles and ground truth (SWIZZLE)
- Row shapes and interoperability contracts (CNS), which Warden never modifies
- Live admission, decision, conservation, execution, custody
- A numeric elegance score

## ARCHITECTURAL STORY

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
| `warden.runstate` | the per-target lock and the keep-test journal, kept in the repository's own git folder (or a private per-user state folder), never in TMPDIR and never through a symlink; also the SIGTERM/SIGHUP/SIGINT handlers, the seat timer and the fd 1 redirect |
| `warden.gitstate` | read-only questions to git: is the folder dirty, where is its git folder, what is `core.hooksPath` |
| `warden.guard` | what an edit may touch: the protected-file list, prose-only documentation scope, symlink resolution, and the snapshot that undoes a seat that wrote |
| `warden.textio` | byte-faithful reads and writes: line endings kept, non-UTF-8 files refused |
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

## LIFECYCLE / EXECUTION MODEL

CLI over a git work tree. Default is read-only. Writes require
`--authorize ACTOR --reason TEXT`.

`warden tagteam PATH --drafter MODULE:FACTORY --finisher MODULE:FACTORY --judge MODULE:FACTORY --ghost-root GHOST_TOOLS --swizzle-root SWIZZLE --assay-root ASSAY --assay-floor N [--allow-uncommitted-instruments]`
runs the whole loop and the hand-off (`--max-cycles`, default 10). Without
`--drafter` it can only observe (`INCONCLUSIVE`). Without `--finisher` it stops
when the loop converges.

**The whole circuit in one command.** `--stack DIR` names a folder that holds checkouts of
the other six repositories, `ghost_tools`, `swizzle`, `assay`, `drafter`, `judge` and
`burnish` (folder names matched without regard to case, so `SWIZZLE` and `swizzle` are the
same), and fills `--ghost-root`, `--swizzle-root`, `--assay-root`, `--drafter`
(`drafter.seat:Drafter`), `--judge` (`judge.seat:Judge`) and `--finisher`
(`burnish.finisher:Burnish`) from them. An option you give explicitly wins over the folder's
copy. There are two modes. **`--stack DIR` alone:** all six must be there; a missing one is a
usage error (exit 2) that names it. **`--stack DIR --stack-manifest FILE` (or `--cns DIR`):** the
pinned manifest says which checkouts the circuit consists of. `ghost_tools`, `swizzle`, `assay`
and `judge` must be named by the manifest and present (a manifest that omits one, or a folder that
lacks one the manifest names, is a usage error naming it). `drafter` and `burnish` are
releasable: if the manifest does not name them and the folder does not hold them, the run
proceeds without them and says so. A folder that holds one the manifest does not name is refused
as an unnamed seat, and a manifest that names one the folder lacks is refused, whatever
`--claim-commit`, `--claim-diff`, `--drafter` or `--finisher` supply: the folder is checked against
the manifest before any option is substituted (exit 2, naming the seat). A
circuit quietly run without a seat would read as the circuit, so a seat is absent only when the
pinned manifest and the folder agree it is absent, and the record says so. A stack without a
`drafter` needs a proposer: `--claim-commit`, `--claim-diff` or an explicit `--drafter`;
otherwise it is a usage error. A stack without `burnish` runs with no finisher
(`evidence.finisher_ran` is false); an explicit `--finisher` still wins. The record carries
`released_seats` (for example `["burnish", "drafter"]`) and a note `released seats not seated: ...`;
the claim row and its `participants` list only seats that were seated. Two folders that differ only by
case are refused rather than guessed between. The seats are imported from the folder's
checkouts ahead of any other copy, and a seat that turns out to live inside the target is
still refused. With a clone of each repository beside the others:

**Across repository boundaries.** A target that imports a sibling repository is, to Ghost, a
single-repository scan with a gap: both sides of the boundary are blind, and Warden holds the
result as `ACCEPT_UNVERIFIED` (`ghost_partial`) rather than accept what it could not measure.
`--join PATH` (repeatable) names a sibling checkout Ghost may read beside the target; the gap is
then measured instead of reported. A joined checkout is read, never imported, and must lie wholly
outside the target. `--stack-manifest FILE`, with `--stack`, does this from a pinned list: a JSON
file `{"schema": "warden-stack/1", "contract": "1", "repos": {name: commit}}` naming the circuit's
checkouts and the commit each must be at, each a full 40-character lowercase commit (a short prefix or any other
spelling is refused). Every named checkout is verified against the folder
(wrong commit, missing folder, not a git checkout, uncommitted changes in it: usage error, nothing runs; ignored
files do not count) and joined for Ghost,
the target itself excepted (a clone of the target at the same commit is verified like the others but not joined,
since it is the same repository). **Every stack folder the run uses is vetted.** The folders a run uses are the ones
`--stack` fills in: the three instrument roots and the three seats, except any whose option you gave explicitly.
With a manifest, each of them must be named by it (a folder the manifest does not cover has no pinned commit, so
the run refuses and names it), at the pinned commit, and with no uncommitted changes. Without a manifest,
each must have no uncommitted changes (a folder that is not a git checkout cannot be asked and is let through). A
tampered `JUDGE` or `DRAFTER` seat therefore cannot ride along because the manifest listed only the others. The
governed target is excluded, as before; its own dirty policy applies. `--cns DIR`, a checkout of CNS, reads the same manifest from the hub at `contracts/warden-stack.json`
(CNS 1.5.0, `cns.stack` is its shape); CNS is read, never written. The manifest is what CNS holds for
the circuit: which versions belong together, decided outside any repository under test. The output's `versions`
object lists every join with its path, commit and version.

    warden tagteam PATH --stack .. --authorize "Your Name" --reason "why" --scope code

**The grant's scope reaches the seats.** A Drafter or Finisher that keeps a `scope`
attribute is told the grant's scope (`documentation` or `code`) before it is first asked;
Drafter and Burnish both do. So under the default `documentation` grant the Drafter leaves a
code fix unproposed (and says why in `drafter_skipped`) instead of having it declined, and
under `--scope code` Burnish includes its code tidy, which it used to leave out because it
could not see the grant. A seat with no such attribute is asked as before, and a seat that
will not take the value is noted; the grant checks every proposal either way. The seat
contract stays `"1"`.
Without `--authorize` it proposes and writes nothing (`REFUSED`). `--reason` must
not be empty. If SWIZZLE's own proofs do not hold, nothing is written and the
command exits 2. The same happens when the SWIZZLE cannot be identified (see "Reading the instruments"). The target path must be an existing folder, or the command exits 2
at once. Without
`--swizzle-root` the notes say `SWIZZLE proofs NOT RUN`, the adversary is
uncalibrated, `swizzle` is in `unmeasured`, and the run ends `ACCEPT_UNVERIFIED` (exit 3) under either scope, whatever
the Judge says (`tests/test_judge_independence.py`).

**A dirty folder is refused.** If the target is inside a git work tree and
`git status --porcelain` shows anything (modified, staged or untracked files; files ignored by the repository's own
`.gitignore` do not count), the run does not start: decision `REFUSED`, exit 5, a reason that tells you to commit
or stash first, and nothing is written. The same goes for a stray `.git/index.lock`. This is
checked for every `tagteam` run, with or without `--authorize`, so Warden's changes can always be
told apart from your own work. **The question is asked the same way whoever asks.** Warden runs git with no user or
system git configuration (an empty global file, no system file), lists every untracked file, does not ignore
submodules, and always compares file mode bits, so a global `status.showUntrackedFiles=no`, a global
`core.excludesFile` (or `$XDG_CONFIG_HOME/git/ignore`) and `core.fileMode=false` cannot hide anything. A tracked file
whose index entry says `assume-unchanged` or `skip-worktree` (`git ls-files -v` shows a lowercase letter or `S`) counts
as uncommitted work even when its content matches, because git would not show its next edit; clear the flag with
`git update-index --no-assume-unchanged` or `--no-skip-worktree`. The same check backs the stack-folder rule above.
Two consequences: git's ownership check (`safe.directory`) is no longer taken from your own git configuration, so a
folder owned by another user is reported as unreadable (refused) rather than trusted; and a repository on a
filesystem that cannot hold the executable bit shows as dirty. A folder that is not a git repository is allowed, with a note that
the start snapshot is the only way back. `warden audit` prints and exits as before; only
`warden audit --authorize`, which writes `WARDEN_AUDIT.md` into the target, follows the same rule
(it exits 2 and writes nothing in a dirty folder), except that `WARDEN_AUDIT.md` itself being new
or modified does not count, so the audit can be rerun to update its table.

**Logs and receipts.** Stdout is one JSON document, whenever it can be delivered (see Delivery below). Logs go to stderr only, through the standard
library's `logging` (`warden.log`): `-v` logs one line per seam (each seat loaded, each instrument run and how it
exited, the suite, the verdict and the exit code, the put-back), `-vv` adds commands and detail, and
`WARDEN_LOG_LEVEL` (`DEBUG`, `INFO`, `WARNING`, ...) sets the level by name. The default is `WARNING`, which is quiet
on a normal run. `--receipt FILE` writes the horsemen production receipt for an authorized run: the ASSAY specimens
read by `AssayAdapter`, the Ghost findings before and after, SWIZZLE's proofs and attacks as a verdict handoff, the
proposal, the scoped human grant, the files changed and the final verdict. An answer key that cannot be read, a
check that was not measured and changes that were put back are recorded as `UNKNOWN`, and a receipt never claims CNS
readiness. The file must lie outside the target. It is written under a temporary name and renamed into place, so a file that
already exists and is not a regular file (a named pipe, a device, a folder, or a link to one) is refused before
anything runs (exit 2, "Nothing was run"): the rename would swap it for a plain file, and run as root that could
replace a device node. An existing regular file keeps its permission bits when it is replaced. The same rule covers
`warden audit --authorize`, which refuses a `WARDEN_AUDIT.md` that is not a regular file (exit 2, nothing written).
A receipt that cannot be written for another reason (a folder that does not exist, say) is said on stderr and does
not change the run's exit code. A run with no human grant has no receipt.

**Delivery.** The result on stdout is the output, so a result that was not delivered is not an approval. If the reader of
stdout leaves (a broken pipe, `warden tagteam DIR | head`), nothing more is printed and the exit code the run earned
stands. If stdout is closed, or a write fails for another reason such as a full device, one line on stderr says so, no
traceback is printed, and a run that earned 0 exits 1 (a non-zero code is kept). The same holds with and without
`PYTHONUNBUFFERED=1`. A closed or broken stderr loses that one line only. Held by `tests/test_report_delivery.py`, which
uses a pipe whose reader is gone, a closed descriptor and a stream that raises `ENOSPC`, and opens no device node.

**Time limits.** `--suite-timeout` (default 900 seconds) limits one run of the target's suite;
`--seat-timeout` (default 3600) limits each seat call (Drafter, Finisher, Judge, and building a
seat). A suite past its limit counts as not run; a seat past its limit ends the run as `ERROR`
and the tree is put back. `--ghost-timeout` is unchanged.

**`--assay-floor`.** A whole number. Below 0 is a usage error. `0` is the one explicit way to
skip enforcement: the score is still recorded, the notes say the floor was not enforced, and the
Judge is told the floor is 0. The default is 3 **on the command line only**: `TagTeam(assay_floor=...)` in the
library defaults to `0` (`warden.tagteam.LIBRARY_ASSAY_FLOOR`), so a library caller that does not pass it
enforces no floor, and one that wants the command line's behaviour passes `assay_floor=3`
(`warden.cli.CLI_ASSAY_FLOOR`). Nothing about either default changed; the difference is documented in
[docs/EXIT_CODES.md](docs/EXIT_CODES.md) and pinned by `tests/test_docs.py`.

**Cut short.** SIGTERM, SIGHUP and SIGINT stop the run in an orderly way: the keep-test trap is
removed, the whole tree is put back, valid JSON is printed (`decision` `INTERRUPTED`) and the exit
code is 7. SIGKILL cannot be caught; see the journal below.

A run that does not end `ACCEPT` leaves the tree as it found it. An `ACCEPT_UNVERIFIED`
run is put back the same way, but its final state is first saved as a held result
(see below). Warden takes a snapshot at the start of every run, and if the run
ends any other way (rejected, not converged, suite red, a seat failed) after
changes were made, the whole tree is restored and the notes say so. The
proposals stay in the cycle records so a person can see what was tried. Folders an
applied change created are removed again when it is put back. A tree over 200 MB cannot be
snapshotted, so Warden will not write to it at all: the run ends `INCONCLUSIVE` with a reason,
before any seat is asked.

Exit codes for `tagteam` (the same table is in `warden tagteam --help` and, generated from the code, in [docs/EXIT_CODES.md](docs/EXIT_CODES.md)). Only 0 means
the change was accepted, so a CI job can trust the exit code alone:

| code | decision | what it means |
|---|---|---|
| 0 | `ACCEPT` | Measured, judged, and standing. The only success. |
| 1 | `REJECT`, `JUDGE_REJECTED`, `NOT_CONVERGED`, `FINISH_REJECTED` | The change was rejected, did not settle, or the finishing step was refused. Anything else that is a rejection also exits 1. A graded ASSAY score below `--assay-floor` is a `REJECT` decided by Warden itself, whatever the Judge said. |
| 2 | (usage error, seat not loaded, or SWIZZLE unsound) | The command was used wrongly (an unknown or bad option prints JSON with `decision` `USAGE_ERROR`; so does a target folder that does not exist), a seat could not be loaded, asked for a different contract, or was found inside the folder being governed, or SWIZZLE's own proofs do not hold (the JSON says `INCONCLUSIVE` and `swizzle_sound` false; the exit is still 2, whether the proofs failed before the loop or after it). Nothing was written. |
| 3 | `ACCEPT_UNVERIFIED` | A check did not run or the Judge could not decide. The changes were put back and saved as a held result under a digest (`held_digest` in the JSON). Nothing stands until a person approves that exact digest with `warden keep`. |
| 4 | `ERROR` | A seat failed, timed out, or gave the wrong kind of answer. A Judge that raises, returns a type that is not a verdict, or returns a label other than `ACCEPT`, `REJECT` or `INSUFFICIENT` is this. Nothing was approved and the tree was put back. |
| 5 | `REFUSED` | No human authorization (or an empty reason, or a name Warden will not accept), or the folder has uncommitted git changes. A proposal may have been shown. Nothing was written. |
| 6 | `INCONCLUSIVE` | A needed measurement could not be made: Ghost is down or timed out, the suite was red when the loop was about to apply a proposed change (see below), the ASSAY key could not be used, another run holds the target, or the folder is too big to put back. Nothing was written. |
| 7 | `INTERRUPTED` | SIGTERM, SIGHUP or SIGINT arrived. The tree was put back as it was found. |

**A suite that is red from the start does not always end the same way.** Warden measures the target's own suite
just before it writes anything, so what a red suite ends as depends on what was about to be written:

- The Drafter proposes a change: the run ends `INCONCLUSIVE`, exit 6, "Cycle N: the suite is not green (the counts
  and the failing test ids, ten at most); nothing was written".
- The Drafter has nothing to propose and the Finisher proposes a change: the finishing change is refused at the same
  measurement and the run ends `FINISH_REJECTED`, exit 1, "Finishing: SUITE_RED (the counts and the failing test
  ids). The finishing change was put back".
- Nobody proposes anything: no write is attempted, so the red suite is not measured before one. The Judge is shown
  the suite's final state and rejects it (`JUDGE_REJECTED`, exit 1); without a Judge the run cannot be a plain
  `ACCEPT` at all.

Every one of these writes nothing and none exits 0. (`tests/test_red_suite_from_the_start.py`.)

### Held results and `warden keep`

An unverified result is never left standing by a run. When `tagteam` ends
`ACCEPT_UNVERIFIED`, Warden saves the exact final state in a private folder under
the target's state directory, puts the tree back, and prints a `held_digest`. The
saved state is checked against that digest every time it is read.

To keep it, a named person approves the digest:

    warden keep <folder> --digest <held_digest> --authorize "<name>" --reason "<why>"

That approval only applies when all of these hold: the grant is for the
`keep_unverified` operation, it names this folder and this exact digest, the actor is
not a part of the stack, the folder is back at the state the run started from, and
the saved state still matches its digest. Warden then writes the saved state into
the folder and checks the result. The checks the run lacked are recorded with the
held result and are not run again; approving a held result accepts that they are
unmeasured. Nothing here is a substitute for those checks.

A decision the code does not know exits 1, never 0.

**What a Judge cannot waive.** Warden enforces three things itself, whatever the Judge says. The unmeasured list: a
Judge's ACCEPT on a run with `unmeasured` entries other than `judge` is `ACCEPT_UNVERIFIED`. The ASSAY floor: a graded
score below `--assay-floor` is `REJECT`, with or without a Judge. A readable verdict: a Judge that returns anything but
a verdict (a string, `None`), a label other than `ACCEPT`, `REJECT` or `INSUFFICIENT`, or a verdict whose reasons are
empty or blank ends the run as `ERROR` and the tree is put back. Stub Judges that rubber-stamp each of these are in
`tests/test_judge_independence.py`. The JSON always has `decision`,
`notes`, `unmeasured`, and `reason`. `reason` is one plain sentence saying why the run
ended as it did; for a plain `ACCEPT` it says what converged, what the Judge said and what was
measured (the suite's counts before and after, Ghost's counts), and for a run the suite turned
red (`INCONCLUSIVE` at a proposal, `FINISH_REJECTED` at the finishing change) it names the failing
tests, ten at most. `unmeasured` is true: it names `ghost`
when Ghost was down, timed out, scanned nothing or gave unreadable output, `suite`
when the suite was never run, `swizzle` when its proofs failed or could not run, and
`assay` when the answer key was unusable, `swizzle_attacks` when SWIZZLE's proofs held but its attacks on the governor could not be run or read, and `ghost_partial` when Ghost ran but
could not look at everything it should have (see below). `warden audit` exits 2 when it cannot read
the findings or will not write; it never prints a clean-looking report for a Ghost
that looked at nothing.

**Old and new Ghost.** Warden reads both. Old Ghost prints a bare list of findings. New
Ghost prints an object with `status`, `scan` counts and an `unmeasured` list, and exits
0 clean, 1 findings, 2 did not start, 3 crashed. Exit 3 ends the run as `INCONCLUSIVE`
with a reason that says Ghost crashed (a fault in Ghost, never a finding and never a
clean scan); exit 2 is reported as Ghost not starting. The output JSON gains
`ghost_scan` (status, file counts, `gaps`, `declined`; null for old Ghost) and
`drafter_skipped` (the Drafter's own reasons for leaving findings alone, from
`describe_skipped()` when it has one; at most 20 lines of 200 characters, cleaned of
control characters; information, never a gap).

**What counts as a gap.** Only an `unmeasured` row that Ghost does not mark as asked for
(`by_request` true; `requested` is read as the same thing). Checks the caller declined
(`--no-tests` and the like, which Warden passes on purpose) and opt-in checks nobody
requested (`mutate`, `kernel`) are listed under `declined` and change nothing, so a
clean default run can still be a plain `ACCEPT`. Everything else is a gap: unparsable
files, a detector that raised, git missing when Ghost needs it, a row that does not say
who asked for it, `status: incomplete` with no reason, an object that leaves out `status`,
`scan` or `unmeasured`, a `baseline` with `suppressed` above 0 (findings Ghost hid), a
`suppressed` that is not a whole number, or Ghost exiting 1 ("found something") with an
empty list. A gap puts `ghost_partial` in
`unmeasured`, so the Judge sees it and the run ends `ACCEPT_UNVERIFIED` at best, never
a plain `ACCEPT`. (A target that is not a git repository is such a gap: Ghost's
`branches` check cannot run there.)

**Old Ghost cannot say what it left out.** A bare list of findings is still accepted as
clean, as before, but the JSON then carries `informational: ["ghost_version_unverified"]` and a
note, so a reader can tell it from a complete answer. Ghost's `baseline` object
(`{"path": str or null, "suppressed": int}`) is read tolerantly: absent is fine, and it is
copied into `ghost_scan.baseline`. It is also handed to the Judge as the optional Evidence fields
`ghost_baseline_before` (first scan) and `ghost_baseline_after` (last scan), and shown in the output as
`ghost_baseline: {before, after}`. A report Ghost did not give, or whose count is not a whole number, is
passed as null so the Judge says "unknown" instead of being told zero. The seat contract stays "1".

**The finisher.** The Judge's Evidence carries `finisher_ran`, a field CNS 2.0.0 added. It is True when the Finisher's
`finish` was called after the loop converged, even if it had nothing to finish (the Evidence's `changed` list says what
was written), and False when no Finisher was seated. Warden never sends None for it. A run that ends before the finishing
step (refused, not converged, SWIZZLE failing after the loop, a finish that was rejected) hands the Judge no Evidence at
all. Held by `tests/test_finisher_ran.py`.

**Ids.** Warden compares Ghost ids only within one run, so the one-time id change in
new Ghost does not disturb the loop unless `--from-ghost` findings from old Ghost are
mixed with a live scan from new Ghost (do not). `warden audit` keeps its human ids
across the change: a row whose Ghost id is gone adopts the new id of a finding with the
same detector, summary and line whose path is the old path with folders in front, only
when that match is unique both ways. Anything else becomes a new row, as before.

**Reading the instruments.** Warden believes an instrument only when it is exact.
Before it runs anything else in SWIZZLE it asks `python -m swizzle.cli --contract` (SWIZZLE's
`docs/CONTRACT.md`) and requires a JSON object with `name` `"swizzle"` and `contract` `1`. A SWIZZLE with no
such flag (older than 0.8.0), another contract number, another tool answering as SWIZZLE, or output that is not
that JSON is not read at all: the proof gate is unmeasured (`swizzle_sound` false, `swizzle` in `unmeasured`),
ASSAY grading, which runs through SWIZZLE, is not run, nothing is written, the run is `INCONCLUSIVE` (exit 2) and
the reason is in `reason` and `notes`. It is never a plain `ACCEPT`. A matching SWIZZLE changes nothing in the
record (`tests/test_swizzle_contract.py`).
`swizzle prove` must exit 0 and print a whole line `N of M proofs hold` with N equal
to M and M at least 1 (`0 of 0` and `1 of 12` are not sound). SWIZZLE's governor
report counts only if it exited 0 or 1 and every item has text for `scenario`,
`severity` and `status`, with the status exactly `held` or `violated`; otherwise the
whole report is "not measured" and the note says why, with the end of SWIZZLE's own
error text. The ASSAY card must hold a list of records with at least one failure-mode
specimen and only outcomes Warden knows. Ghost gets a time limit (`--ghost-timeout`,
default 600 seconds), must return a list of records whose ids are text, and counts as
not measured if it says it scanned nothing.

**The handshake with the other repositories.** Judge, Drafter and Burnish build
against Warden's shapes (`Evidence`, `Verdict`, `Facts`, `Transformation`). Warden
exposes `warden.CONTRACT` (now `"1"`) and raises it only when one of those shapes
changes in a way that breaks a seat written for the old shape. Every seat must declare
`requires_contract = "1"` (a class or instance attribute). When it names any other
version, or declares nothing, `warden tagteam` refuses to run, says which, and exits 2
with `SEAT_NOT_LOADED`. Nothing is run and nothing is written. There is no switch to
skip the check: Judge, Drafter and Burnish all declare it, so it would only let an
unchecked seat govern a run. The JSON names the contract Warden checked
(`contract`) and the versions that took part (`versions`: Warden's version and
contract; the commit and `pyproject.toml` version of each of `--ghost-root`,
`--swizzle-root` and `--assay-root` that was given; and for each seat that was loaded
its `spec`, declared `requires_contract`, and the `version`, `commit` and `dirty` flag of the code that was loaded: when the seat's module sits in a git checkout of its own (the `--stack` case) those come from that checkout, whatever older copy pip also installed (a checkout whose version cannot be read says `null`, not the installed copy's); only a seat installed in site-packages reports its install record). Every root also has
a `dirty` flag (uncommitted work in that checkout; `null` when it is not a git checkout of its
own). A commit is read only from the thing's own checkout or install record, never from a
repository that merely contains it: a folder inside the target's repo, or a seat that lives
inside the target, reports `null`, not the target's commit. A value that cannot be found is `null`.
A Judge verdict with no judge name or with extra fields is reported in the notes
and does not crash the run.

**Releasing, and the seats' pins.** Judge, Drafter and Burnish each depend on one exact Warden
full commit SHA, not on `main`. After a Warden change that seats must pick up (any change
to `CONTRACT`, or to what a seat is checked for), the owner tags the merge commit `vX.Y.Z` (matching
the version in `warden/__init__.py`, which `pyproject.toml` reads), then one pull request per seat moves its pin
(see "Bumping the Warden pin" in each seat's README). Tagging is the owner's decision; this repository's release tags
run up to `v0.12.0` (see the top of this README). Merge seats before the Warden change that
needs them: this release makes a seat without `requires_contract` refuse to load, so the seats
must declare it first.

**How the suite is read.** Warden runs `python -m pytest` in the target with a small plugin of
its own that counts every outcome and writes pytest's exit status and the counts to a private
file. Green means exit status 0, at least one test passed, and no failure or error in the
counts. Text the suite prints (at the end, at exit, or anywhere) is never read, so a forged
`5 passed` line cannot turn a failing run green, and a harmless `2 failed uploads` line cannot
turn a green one red. A suite that forces exit 1 with every test green is not green, and the
description says `pytest exited 1`.

**Rust projects.** A target with a `Cargo.toml` and no Python test setup (no `pytest.ini`,
`conftest.py`, `tox.ini`, `setup.cfg`, `setup.py`, `pyproject.toml`, and no `test_*.py` file) is
measured with `cargo test` instead; `--suite-runner pytest|cargo` overrides the choice, and
Python wins when both are present. Warden asks the test harness for its JSON summary
(`--format json`, which needs `RUSTC_BOOTSTRAP=1` on a stable toolchain, set for that one run
only) and requires Cargo's exit status to agree with it. Build output goes to a fresh temporary
folder per run, `--locked` keeps `Cargo.lock` as it is, and tests run one at a time so timing
tests are not measured under self-inflicted load. Unit, integration and example targets are
built; documentation tests are not run. Differences from the pytest path, stated plainly: there
is no private file with a one-time code, so a test that writes forged JSON straight to the process
output can inflate the pass count (it cannot turn a failing run green, because a failure makes
Cargo exit non-zero and is counted); and a Rust source file edited by the suite is noticed the
same way a Python one is. `Cargo.toml`, `build.rs`, `rust-toolchain*`, `.cargo/`, and test files
and folders are in the protected list. Ghost Tools analyses Python, so on a Rust project the
Rule 7 gate is the only behavior check.

**What a proposal may touch.** Never: anything outside the target, version control and
environments, test material (`fixtures`, `specimens`, `testdata`, `golden`, `snapshots`, `corpus`
folders, not even their whitespace), and Ghost's own `.ghost_*` files. The files that judge or build
the work are protected, which since 0.14.0 means named, not refused: test files and folders (`tests`,
`test`, `testing`, `tests.py`), `conftest.py`, every pytest/tox/setup/nox/make/pyproject
config, CI configs (`.github`, `.circleci`, `.gitlab-ci.yml`, `Jenkinsfile`,
`azure-pipelines.yml` and the like), git hooks (`.githooks` and any `core.hooksPath` folder),
`.gitmodules`, lockfiles, `requirements*.txt` / `constraints*.txt` / `Pipfile`, Docker and
compose files. An edit to one of them is applied and measured like any other, every such path is
named in the Judge's `judging_files_touched` and in the claim row's `files` (`protected` true), and
the Judge decides; the machine does not approve it, so the run ends held (`ACCEPT_UNVERIFIED`) by
digest for a named person to keep or drop with `warden keep` (the owner's ruling, 2026-10-28; a Judge
older than that ruling says REJECT instead and the whole tree is put back). Names are compared
without regard to case. A symlink is judged by where it really points, before the check: a link that
points at a protected file is that file, and one that points outside the target is an escape. In the
default `documentation` scope only real prose is editable: `.md`, `.rst` and `.txt`, except
requirements and constraints lists, `CMakeLists.txt`, `LICENSE*`, `NOTICE*`, `COPYING*` and
similar non-prose text files, so under that scope a protected code or configuration file is declined
as out of scope and nothing is written.

**Seats.** Before a seat is loaded, `''` and the current directory (and anything inside the
target) are taken off Python's import path, and the loaded module (and the seat's class) must not
live inside the target; a `judge/seat.py` planted in the target cannot stand in for the installed
seat. While seats run, file descriptor 1 itself, not only `sys.stdout`, is pointed at stderr, so a
stray write cannot corrupt the JSON. A `.git/*.lock` file a seat leaves behind is removed and the
seat is charged with writing.

**Bytecode.** A `.pyc` in a source tree's `__pycache__` is read in place of the source, and an unchecked-hash one is never
compared with it. Git ignores that folder, so a seat or instrument checkout could be clean, at its pinned commit, and still run
planted bytecode (reproduced by the round-6 audit with a tampered JUDGE `.pyc`; the governed run ended `ACCEPT`). Since 0.13.10
`main` runs inside a fresh private bytecode directory (`sys.pycache_prefix`, a new `warden-pyc-` folder under the temporary
directory, removed afterwards), set before any seat is imported, and every instrument is started with the same directory in
`PYTHONPYCACHEPREFIX`. With a prefix set Python reads and writes bytecode only there and never looks in a tree's `__pycache__`.
What it costs: modules imported during a run (a seat's, `ghost_buster`, `swizzle`, and the libraries they import) are compiled
from source the first time in each Warden run, because nothing is kept between runs. What it does not touch: modules already
imported before `main` starts (Warden's own, `cns`), other Python processes, and the target's suite, which has run with its own
private prefix since the code was Elegant. Held by `tests/test_stale_bytecode.py`, which plants a real unchecked-hash `.pyc` built with
`py_compile` in an ignored `__pycache__` of a clean committed checkout and shows the tampered code runs under plain Python and not
under Warden, in a seat and in an instrument.

**Declined proposals.** A proposal declined without a write (out of scope, a judging file, a
failed keep test) does not use up one of `--max-cycles`; only a proposal that reaches the applier
does. At most 50 declined proposals are allowed in one run, then it ends `NOT_CONVERGED`.

**The ASSAY key proof.** When ASSAY grading exits 2, Warden reads SWIZZLE's card on stdout and
relays the real reason (for example `verify_manifest.py could not run: timed out`), not only the
last line of SWIZZLE's error text. If the reason is the known temporary kind (the verifier could
not start or timed out), the grading is run once more, exactly as before: the proof is not
weakened or skipped, and a count that disagrees (`28/29 claims hold`) is never retried. The
summary says when the second run was needed.

A proposal that changes nothing is dropped as `NOTHING_TO_PROPOSE`, not counted as
applied. A proposal that is outside the grant's scope and cites no defect is declined
(nothing is written) and the loop goes on, as long as scope is the only thing wrong
with it; asking for the same thing twice ends the run as `NOT_CONVERGED`. A proposal
that also touches a test file, CI, or a path outside the target is still `REJECT`.

`ERROR` means a seat (Drafter, Finisher, Judge) raised an exception, did not
answer in time, or gave the wrong kind of answer (for the Judge, that includes a label that is not
`ACCEPT`, `REJECT` or `INSUFFICIENT`). The notes name the seat and the kind of exception,
never a traceback, and the tree is put back.

Rule 7 is enforced on every authorized write: the suite must be green before
the change, or nothing is written; after it, no new failures and at least as
many passes, or the change is put back and the decision is `REJECT`. Both
counts are in the output.

`warden audit PATH --ghost-root GHOST_TOOLS` prints `WARDEN_AUDIT.md` with
every Ghost finding under a C/H/M/L ID. Existing IDs keep their meaning, new
findings get new numbers, and a finding that left the scan keeps its row. With
`--authorize ACTOR --reason TEXT` it writes the file. Only the table between
its markers is Warden's; every other section survives reruns untouched.

### Instrument roots

Instruments (SWIZZLE, Ghost Tools, ASSAY grading) run with only their named roots on `PYTHONPATH`, and a root is checked before anything runs. An inherited `PYTHONPATH` is dropped (`warden/isolation.py`, `instrument_env`), but the interpreter's site-packages stays importable, so dropping it alone let an installed copy stand in for a root that was missing or wrong: `--ghost-root /nonexistent` with Ghost Tools installed scanned anyway, and `--swizzle-root /nonexistent/swz` with SWIZZLE installed reported "12 of 12 proofs hold". Naming the installed copy itself was the next hole: `--ghost-root $VENV/lib/python3.13/site-packages` holds a real `ghost_buster` and ended in `ACCEPT` with a null commit and version in the record. Now each root (`--ghost-root`, `--swizzle-root`, `--assay-root`, and the folders `--stack` fills them from) must pass all of these (`verify_root`), or nothing is run:

1. It is an existing directory that holds the instrument's package (`ghost_buster`, `swizzle`, `assay_production`), and the interpreter, started the way the instrument is started, resolves that package under the root (the module file is found, not imported).
2. It is not an installed copy. A root that is, or lies inside, a folder named `site-packages` or `dist-packages`, or the interpreter's own stdlib or site folders (`sysconfig`, `site.getsitepackages()`; links are followed first), is refused whatever it holds. A root that is also installed in editable mode (`pip install -e`) is a checkout and is allowed.
3. It is a checkout Warden can name: a git commit of its own, and a version Warden can read from its `pyproject.toml` (a static `version`, or a dynamic one read from the module's source, never imported). A plain copy of the package in an ordinary folder has neither and is refused, unless `--allow-uncommitted-instruments` is given. With the flag the root runs, the record says `allow_uncommitted_instruments: true`, `instrument_provenance` is in `unmeasured`, and the run is at best `ACCEPT_UNVERIFIED`. The flag never opens an installed location (item 2).

A refused root fails closed as it does with nothing installed: Ghost is `INCONCLUSIVE` with `ghost` unmeasured, SWIZZLE's proofs are unsound (`swizzle_sound` false, exit 2), and an unusable ASSAY root leaves the key ungraded. `swizzle_sound` is the answer about SWIZZLE's proofs only; a failure of Ghost beside a good SWIZZLE is recorded in `decision`, `reason` and `unmeasured`, not by blanking it. `versions.ghost_tools`, `versions.swizzle` and `versions.assay` carry `module` (the file the package resolved to) and `module_in_root`. **VERIFIED** by `tests/test_instrument_roots.py`, which gives the interpreter an installed copy of each instrument and, for each, a root equal to site-packages, inside it, a link to it and a plain copy, with and without the flag. Before the earlier `PYTHONPATH` change, five tests failed under the full environment; they pass now.

### Tests and CI

Most tests start real `pytest` or `warden` processes, so the full run takes minutes (`pytest -n 2` helps). CI runs the suite on Python 3.11, 3.12 and 3.13, plus `ruff check .`, `mypy`, an install check of the `ghost` extra (`pip check`) and the circuit smoke test, which also seats the real Judge. Every action and every sibling repository is pinned by full commit SHA, and CNS by the tag `v2.0.0` (the tested set is in [STACK.md](STACK.md): the last set this repository's CI tested on its own, not the heads of anything); to bump a sibling, change its SHA in `.github/workflows/tests.yml` (every job that checks it out, and the `--expect` line), in `pyproject.toml` for ghost_tools, and in STACK.md, then run the whole job set. CI sets `WARDEN_FAIL_ON_SKIP=1`, so a skipped test fails the job (`tests/conftest.py`); it installs the pinned Judge and checks out the pinned ASSAY so nothing skips.

## ARCHITECTURAL DEBT

- Warden's Ghost consumer reads Ghost's JSON over a process boundary; `GhostToolsAdapter` (horsemen) is a typed reader used by the receipt, not the loop's live path.
- SWIZZLE's `TargetAdapter` for Warden lives in the SWIZZLE repository, not here.
