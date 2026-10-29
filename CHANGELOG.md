# Changelog

All notable changes to Warden. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the version in `warden/__init__.py` (read by `pyproject.toml`) is the single source of truth.
The seat contract (`warden.CONTRACT`) is `"1"` throughout and has not changed.

Release tags exist up to `v0.12.0` (an annotated tag that peels to `72e5745`); the `0.13.x` releases are not tagged, and
`0.14.0` is not tagged either, nor is `0.15.0`. The
older `v0.10.0` tag does not match its tree: it points at a tree whose `__version__` is `0.9.0`. Tagging is the owner's
decision, and the satellites (Judge, Drafter, Burnish) pin Warden by full commit SHA, not by tag.

## [0.15.0] - 2026-10-29

`CONTRACT` is still `"1"`. Not tagged. This release sits on the 0.14.0 head `68f2a95`. CNS stays at the tag `v2.0.0`; no
cross-repository pin moved. Minor version: a new rule for `--stack`, a new record key and a renamed row field. No exit
code changed.

### Changed

- **`--stack` with a pinned manifest may leave out `drafter` and `burnish`** (the owner released both, and WATCHER_MCU,
  from the circuit on 2026-10-29; nothing is deleted). `--stack DIR` alone is unchanged: all six checkouts are required.
  With `--stack-manifest FILE` (or `--cns DIR`) `ghost_tools`, `swizzle`, `assay` and `judge` must be named by the
  manifest and present; `drafter` and `burnish` are absent only when the manifest does not name them and the folder does
  not hold them. A folder that holds one the manifest does not name is still refused as an unnamed seat, and a manifest
  that names one the folder lacks is still refused. A stack without `drafter` needs `--claim-commit`, `--claim-diff` or
  `--drafter` (usage error 2 otherwise); a stack without `burnish` runs with no finisher (`Evidence.finisher_ran` is
  false); an explicit `--finisher` or `--drafter` still wins. The run record gains `released_seats` and a note
  `released seats not seated: ...`; the claim row and `participants` list only seated seats. (Step W1.)
- **The claim row's `new_findings[].severity` is Ghost's own word** (critical, major, minor, informational), the word the
  Judge receives in `evidence.ghost_severity`; Warden's remapped word moves to `warden_severity` in the same entry. The
  proof run of 2026-10-28 found the row saying "medium" where the Judge saw "minor". `TagTeamResult.ghost_words` keeps the
  words, so this also holds under CNS 2.0.0. (Step W2.)
- Version 0.15.0; README entries under WHAT WORKS, WHAT DOES NOT WORK and the ledger. (Step W3.)

### Tests

- New: `tests/test_stack_released.py` (Step W1) and one test in `tests/test_ghost_severity.py` (Step W2).
- Edited under rule 5: Step W3, `tests/test_docs.py::test_the_tags_are_described_without_claiming_a_release_that_is_not_tagged`
  accepts the version `0.15.0` (the assertion about which versions the tag sentence covers). Nothing else changed in
  any pre-existing test.

## [0.14.0] - 2026-10-28

`CONTRACT` is still `"1"`. This release sits on top of the 0.13.10 commit `9ecd1124e6c1b1c4ad7daed37b17f9009662dd9d`
(the branch head `9ecd112`) and builds the four strategies of the sim9 simulations (A claim row, B severity, C chronicle,
D suite reuse) plus the owner's two rulings on the Judge. CNS stays at the tag `v2.0.0`; the new record keys are extra keys
there and typed from CNS 2.1.0. Not tagged. Minor version: new command-line options, a new subcommand, a changed guard
rule and record keys. No exit code changed.

### Added

- **The claim seat** (`warden/claim.py`): `--claim-commit SHA` (with `--claim-repo PATH`) or `--claim-diff FILE` with
  `--claim-subject` and `--claim-author` takes the Drafter seat with a real change, proposed once as writes and deletes
  of UTF-8 text and then nothing. Binary files, symbolic links, submodules, renames, copies, mode changes, quoted paths and
  a target not at the change's base are refused with a reason before anything runs (exit 2); `--claim-*` beside
  `--drafter` is a usage error. `Transformation.claim` carries the facts. (Step 1.)
- **The claim row** (`warden/claimrow.py`, `claim_row(result, authorization, versions)`): the record's `claim` key with
  the shared field names (origin, base and claimed commits and tree digests, subject, author, date, diff sha256 and size,
  files by sha256 with a protected flag, actor, authority, authorization and transformation ids, scope, suite results,
  Ghost counts, new and closed findings, `rules_fired`, judge, decision, held digest, held tree digest, participants,
  finisher edits) and the Judge's whole Evidence as `evidence`; both also in the held file (`held.attach`) and the
  receipt. `TagTeamResult` gained `held_tree_digest`, `evidence`, `finish_cycle`; each applied cycle records what landed
  by file and the tree fingerprint after the apply. (Step 2.)
- **`Evidence.ghost_severity`** is filled with Ghost's own severity word per finding id when the installed
  `cns.seat.Evidence` has the field (CNS 2.1.0); under 2.0.0 nothing changes. (Step 3.)
- **Suite reuse within a run** (`--suite-always` turns it off): a pass on a tree whose fingerprint was already measured in
  this run reuses that result, with a note and a `suite_passes` list (`reused_from`) in the record and `pass`,
  `reused_from` on the row's suite results. Six passes become three on a run with one change and one finishing edit.
  (Step 4.)
- **The chronicle** (`warden/chronicle.py`, `--chronicle DIR`, `warden keep --chronicle DIR`, `warden chronicle DIR
  [--origin X]`): one JSON line per run keyed by (origin, base commit, claimed commit) with the promises a result opens
  if kept; a later run on the same tree settles them (HELD, BROKEN, OPEN with the measurement) into its own line and
  its record's notes and `chronicle` key. (Step 7.)

### Changed

- **A protected path is applied, measured, named and held, not refused** (the owner's ruling, borderline, reviewed by the
  author). `guard.violation` no longer refuses tests, test or build configuration, CI, dependency lists and git hooks;
  the edit is applied and measured, `judging_files_touched` names it (by its own name or where a link really points) and
  the Judge decides, so the run ends held for `warden keep`. Test material and `.ghost_*` files stay refused
  (`guard.is_ghost_file`); escapes stay escapes. The pinned Judge 0.4.8 still says REJECT on such an edit. (Step 5.)
- An `ACCEPT` record's `reason` is never empty: it says what converged, what the Judge said and what was measured. A
  red suite at a proposal (INCONCLUSIVE) or at the finishing change (FINISH_REJECTED) names the failing tests, ten at
  most (`suite.PytestSuiteRun.failed_ids`). (Step 6.)
- Version 0.14.0; README entries under WHAT WORKS, WHAT DOES NOT WORK and the ledger; docs/ARCHITECTURE.md and
  docs/EXIT_CODES.md regenerated. (Step 8.)

### Fixed

- `tests/test_stale_bytecode.py`'s control plants its `.pyc` where plain Python looks even when the suite runs under a
  bytecode cache prefix, as it does under Warden's own `suite.py` (self-hosting run 3). (Step 6.)

### Tests

- New: `tests/test_claim_seat.py` (Step 1), `tests/test_claim_row.py` (Step 2), `tests/test_ghost_severity.py` (Step 3),
  `tests/test_suite_reuse.py` (Step 4), `tests/test_protected_hold.py` (Step 5), `tests/test_record_honesty.py` and one
  test in `tests/test_stale_bytecode.py` (Step 6), `tests/test_chronicle.py` (Step 7).
- Edited under rule 5 because the behaviour they assert is what a step changed: Step 4,
  `tests/test_closing_false_accepts.py::test_a_suite_that_goes_red_in_a_later_cycle_puts_the_earlier_edits_back` (the red
  third run is now the second cycle's after-pass, REJECT); Step 5,
  `tests/test_seams.py::test_the_loop_cannot_weaken_the_tests_that_judge_it`, `::test_a_finisher_cannot_plant_a_conftest`,
  `tests/test_round3_suite_and_guard.py::test_a_symlink_to_a_protected_file_is_not_a_way_in`,
  `::test_a_symlinked_folder_into_a_protected_folder_is_protected`, `::test_the_folder_git_runs_hooks_from_is_protected`,
  `tests/test_honest_exit_codes.py::test_a_proposal_that_also_touches_a_test_file_is_still_rejected`; Step 6,
  `tests/test_honest_exit_codes.py::test_0_is_accept_and_only_accept` (an ACCEPT reason is no longer empty); Step 8,
  `tests/test_docs.py::test_the_tags_are_described_without_claiming_a_release_that_is_not_tagged` (the version is 0.14.0 and
  the documents say it is not tagged). Nothing else was edited.

## [0.13.10] - 2026-10-24

`CONTRACT` is still `"1"`. This release sits on top of the 0.13.9 commit `b57b81e1c98333c43d422666c89a8fcf3ae6eaca` and
answers the round-6 audit. CNS stays at the tag `v2.0.0`. No decision changed; one exit code does: a result that could not
be delivered (below).

### Fixed

- **A seat's record named the pip install record, not the checkout that ran.** In the `--stack` case the checkout's code
  runs, but `versions.seats.<seat>` reported the version and commit of an older copy pip also installed (JUDGE 0.4.8
  beside a 0.4.10 checkout; the finisher as Burnish 0.3.11 when 0.3.12 ran). When a module's file sits in a git checkout of
  its own, version, commit and dirty flag now come from that checkout; a checkout whose version cannot be read says
  `null`. A seat in site-packages still reports its install record. Instrument roots already read their own checkout.
  (Step 1.)
- **A result nobody received was not handled.** `warden tagteam DIR | head -c0` printed a `BrokenPipeError` traceback and
  exited 1 where the run had earned 6 (120 when buffered). Everything on stdout now goes through one function that keeps
  the first failure: a gone reader keeps the earned exit code; a closed stdout or any other failed write (a full device) says so
  in one line on stderr, prints no traceback and turns an earned 0 into 1; a non-zero code is kept. A receipt is still
  written after a failed print. (Step 2.)
- **A planted or stale `.pyc` in a seat or instrument checkout could run.** An unchecked-hash `.pyc` in an ignored
  `__pycache__` was loaded in place of the source, invisible to `git status`, and the governed run still ended `ACCEPT`.
  `main` now runs inside a fresh private bytecode directory (`sys.pycache_prefix`, removed afterwards) and every
  instrument is started with the same directory in `PYTHONPYCACHEPREFIX`, so Python never reads a tree's `__pycache__`.
  Cost: modules imported during a run compile once per run. Not covered: modules imported before `main` (Warden's own, `cns`),
  sourceless `.pyc` files, and the rest of the ignored-or-excluded-file class, which stays a known defect. (Step 3.)

### Changed

- Statements made true: no pin is called "the head of" a `main` or a branch (tests.yml, STACK.md, `pyproject.toml`, README);
  the tested set is the last set this repository's CI tested on its own, and whether the landing set works together is the CNS
  `stack` job; the cited CI run is the previous release's; the unmeasured run time is gone; the paragraph on a seat's
  `version` and `commit` describes the new precedence. SELF-HOSTING cites the CNS record
  `docs/evidence/SELFHOSTING_2026-10-23.md` for this repository (ACCEPT, 4165 s, 953 passed and 2 skipped, 93 Ghost findings,
  seven gaps, under Burnish 0.3.11) and says what it does not mean. (Step 4.)
- The install pins moved to the wave-F final commits: ghost_tools 1.10.9 `3df51b374ed016b3f42def17c080700cd770e85a`, SWIZZLE
  0.8.8 `6853c92cf000c5b86c6b83090ec192b2974b70aa`, ASSAY 0.11.6 `1de36ca9b56ba51b6b1f577bf046d7270b7e6c2a` (the `ghost`
  extra, CI checkouts, `--expect` values, comments, STACK.md). The JUDGE pin (0.4.8, `e5c3f98f0f3998a8c5dac458ad0fcf4e050eb074`)
  and the CNS tag are unchanged. (Step 5.)
- Version 0.13.10. README ledger entries for the new defects. (Step 6.)

### Tests

- New: `tests/test_versions_precedence.py` (Step 1), `tests/test_report_delivery.py` (Step 2), `tests/test_stale_bytecode.py`
  (Step 3), and in `tests/test_readme_ledger.py` the self-hosting numbers (copied from the CNS record), no "head of" claims and
  the seat-record wording (Step 4).
- Edited because the behaviour they assert is what a step changed: `test_the_tested_set_is_the_same_everywhere_it_is_stated`
  expects the versions 1.10.9, 0.8.8 and 0.11.6 next to the three moved pins (Step 5). Nothing else was edited.

## [0.13.9] - 2026-10-22

`CONTRACT` is still `"1"`. This release sits on top of the 0.13.8 commit `380894f0304ef40587dd29efd41b4ceccf94a5d3`. No exit
code and no decision changed. The patch number follows this file's convention: 0.13.2 added record keys in a patch too.

### Changed

- The CNS pin is the tag `v2.0.0`: `cns @ git+https://github.com/wking53214/CNS.git@v2.0.0`, comment
  `v2.0.0 = b13e5d2f9e0e4291725f82794b89117c3d840ac1`, in `pyproject.toml`, the CI header, README and STACK.md. The suite
  passes against the installed `cns` 2.0.0 (its `direct_url.json` names the tag and that commit). Warden imports none of
  the one breaking item (`cns.stack.StackPin`). (Step 1.)
- The tested set moved to the stage-1 heads of three siblings: ghost_tools 1.10.8 `5a9154d3c76670f5bf1f46d845acadfed46d7bc8`,
  SWIZZLE 0.8.7 `3f35dad5568b590c2ee36e60533d50a35db94aa2`, ASSAY 0.11.5 `184679c06e0a636a9a08a8403efa410b375c9429` (CI
  checkouts, the `--expect` values, the `ghost` extra, comments and the STACK.md table). The JUDGE pin is unchanged
  (0.4.8, `e5c3f98f0f3998a8c5dac458ad0fcf4e050eb074`). `pip install -e ".[ghost,dev]"` resolves with no conflict and
  `pip check` is clean. (Step 2.)
- Version 0.13.9. (Step 5.)

### Added

- `Evidence.finisher_ran` (new in CNS 2.0.0) is filled. It is True when the Finisher's `finish` was called after the loop
  converged (even if it had nothing to finish) and False when no Finisher was seated. Warden never sends None: Evidence is
  built only on those two paths, and a run that ends before the finishing step builds none. Before, the Judge always
  received None. (Step 3.)

### Fixed

- `warden[ghost]` was written as an install line in the README and in a `pyproject.toml` comment, but `warden` on PyPI is
  another project. Both now say `pip install -e '.[ghost]'` from a checkout. (Step 4.)

### Documentation

- README rewritten: WHAT THIS IS, HOW TO INSTALL AND RUN, WHAT WORKS, WHAT DOES NOT WORK / NOT PROVEN, KNOWN DEFECTS,
  WHAT BROKE AND HOW IT WAS FIXED, SELF-HOSTING, CEILINGS CODE CANNOT FIX, then the behaviour description under REFERENCE.
  New open defects recorded with how each was reproduced: `.git/info/exclude` can hide an untracked file from the dirty
  check; the neutral git configuration refuses a folder owned by another user; the Ghost scan summary is cut at 10 gaps
  and 20 declined checks; the printed record does not say whether the Finisher was called. Two statements nothing records
  were dropped (a hand check dated 2026-10-09, and "live on CNS"). (Step 4.)

### Tests

- New: `tests/test_finisher_ran.py` (Step 3); `tests/test_readme_ledger.py` and
  `tests/test_docs.py::test_no_document_tells_a_reader_to_install_a_bare_name_from_pypi` (Step 4).
- Edited because the behaviour they assert is what a step changed (the step that caused it):
  `tests/test_docs.py::test_the_cns_pin_is_the_v1_9_0_tag_and_is_stated_in_stack` is renamed `..._v2_0_0_...` and asserts the
  `v2.0.0` pin text and its row in STACK.md (Step 1); `test_the_tested_set_is_the_same_everywhere_it_is_stated` reads the
  new versions of the three pins (Step 2); a comment in `test_dependencies_and_ci_siblings_are_pinned_to_full_commits` that
  named the renamed test now names the new name, no assertion changed (Step 1, committed with Step 4).

## [0.13.8] - 2026-10-22

`CONTRACT` is still `"1"`. This release sits on top of the 0.13.7 commit `1636e1a21f124eedbf6e158db95dc75344f4308d`.

### Fixed

- **A manifest that named only some of the stack still let the rest run.** `_joins_from_manifest` checked only the
  names the manifest listed, while `--stack` uses every one of its folders as an instrument root or a seat. A manifest
  `{"DRAFTER": sha}` with a modified, unpinned JUDGE seat ended `ACCEPT` and the modified Judge ran. A stack run now
  exits 2, "Nothing was run", naming the folder, when a stack folder it uses (the three instrument roots and the three
  seats that `--stack` fills in, except those given by an explicit option) is not named by the manifest in force, is not
  at the manifest's commit, or has uncommitted changes; without a manifest it must still have no uncommitted changes. The
  governed target stays excluded. The same-commit exemption (a clone of the target at the same commit as a stack member)
  also skipped the dirty check; now only the join is skipped and the member is still checked. (Step 1.)
- **The dirty check depended on who asked.** `tree_state` ran plain `git status --porcelain`, which honours the user's
  git configuration and index flags. `git update-index --assume-unchanged` and `--skip-worktree` on a modified seat file,
  a global `status.showUntrackedFiles=no`, a global `core.excludesFile` hiding an untracked file, and
  `core.fileMode=false` hiding a chmod each made a tampered seat look clean. Git now runs with no user or system
  configuration, with `-c core.excludesFile=`, `--untracked-files=all` and `--ignore-submodules=none`, comparing the mode
  bit; a tracked file that `git ls-files -v` flags lowercase or `S` is refused. Files ignored by the repository's own
  `.gitignore` are still accepted; `index.lock`, a corrupt index and missing objects are still refused. The target's own
  dirty policy uses the same check. (Step 2.)
- **A target inside an instrument checkout was not refused.** `_instrument_inside` refused only an instrument root inside
  the target. A target that is a subfolder of an instrument checkout (for example the SWIZZLE package folder) now
  exits 2 (`SEAT_NOT_LOADED`) before anything runs, as the other direction does. (Step 3.)
- **A file written by rename could replace a special file.** `--receipt` is written under a temporary name and renamed
  into place, so a root caller naming a named pipe, a device node or a folder would have it replaced. An existing
  target that is not a regular file is now refused before anything runs (exit 2, "Nothing was run"), checked again just
  before the rename, and an existing regular file keeps its permission bits. `warden audit --authorize` refuses a
  `WARDEN_AUDIT.md` that is not a regular file (a pipe used to block it). (Step 4.)

### Changed

- **Docs truth for a suite that is red from the start.** README and `docs/EXIT_CODES.md` said it is `INCONCLUSIVE`, exit
  6. That holds when the Drafter proposes a change ("Cycle N: the suite is not green"). When the Drafter has nothing to
  propose and the Finisher does, the run ends `FINISH_REJECTED` ("Finishing: SUITE_RED"), exit 1; when no one proposes
  anything the Judge sees the red suite and the run ends `JUDGE_REJECTED`, exit 1. The documents and the exit-code help
  text now say so. No code path and no exit code changed. (Step 5.)
- The tested set moved to the wave D mains: ghost_tools 1.10.6 `2d03d8e19dc5937a6f45379c429d1a3afce4ab29`, SWIZZLE 0.8.5
  `522658415b026ac3211d3fc130ba7da7c77cc400`, JUDGE 0.4.8 `e5c3f98f0f3998a8c5dac458ad0fcf4e050eb074`, ASSAY 0.11.3
  `a1732f2bf3748235661f65b96e590a6d44ace71c` (CI checkouts, the `--expect` values, the real-Judge install, the `ghost`
  extra, comments and the STACK.md table). (Step 6.)
- Version 0.13.8. (Step 7.)

### Tests

- Edited (the step that caused it): `test_a_stack_manifest_pins_every_checkout_and_joins_all_but_the_target` puts the
  stack member back before its clone run, because the run before it changes that member and it is now checked even when
  skipped as a join; its assertions are unchanged (Step 1). `test_the_tested_set_is_the_same_everywhere_it_is_stated`
  reads the new versions of the four pins (Step 6).
- New: manifests that leave out a used folder, dirty or covered seats, explicit options, the same-commit clone (Step 1);
  `tests/test_gitstate_strict.py` for each bypass and the refusals that still hold (Step 2); a target inside an
  instrument checkout (Step 3); a pipe, a folder and links to them as the receipt, the writer's own check, permission
  bits, a pipe as the audit file (Step 4); `tests/test_red_suite_from_the_start.py` (Step 5).

## [0.13.7] - 2026-10-21

`CONTRACT` is still `"1"`. This release sits on top of the 0.13.6 commit `0c1ea567f0b69586cfd735f82260774aec9552bb`.

### Fixed

- **A stack manifest pin could be a prefix.** `_joins_from_manifest` accepted any prefix of 7 or more characters, so a
  manifest that pinned ghost_tools to `c2ada82` ended `ACCEPT`, exit 0. A pin must now be the full 40 characters, lowercase
  hex as git prints it, and equal the checkout's commit. A prefix, a longer string, non-hex text, uppercase or a padded pin
  is a usage error, exit 2, "Nothing was run", naming the repository and saying a full 40-character commit is required.
  (Step 1.)
- **A dirty joined checkout was accepted.** A modified JUDGE seat that wrote a marker file still ended `ACCEPT`, exit 0,
  with `judge.dirty: true` recorded and ignored. A checkout the manifest joins that has uncommitted changes (a modified
  tracked file or an untracked file that is not ignored: what `git status --porcelain` reports, as `gitstate` reads it;
  ignored files such as `__pycache__` do not count) is now a usage error, exit 2, "Nothing was run", naming the folder and
  how many paths are dirty. A checkout whose state git cannot say is refused the same way. The governed target is still
  excluded from the joins and keeps its own dirty policy. There is no opt-out: `--allow-uncommitted-instruments` means a
  root with no commit of its own, not a dirty tree. (Step 2.)

### Changed

- The README and this file named `v0.11.4` as the newest tag. They now say release tags exist up to `v0.12.0`, that `0.13.x`
  is not tagged, that the older `v0.10.0` tag does not match its tree (it points at a `0.9.0` tree), and that tagging is the
  owner's decision. STACK.md's `bash` fence at "One command runs all seven" is closed where the command ends. The CI
  workflow has `permissions: contents: read`. README and STACK.md say ASSAY's answer key needs numpy and matplotlib
  installed normally, with matplotlib's own dependencies; with `--no-deps`, 56 of its 60 claims are proven. (Step 3.)
- The tested set moved to the current mains: ghost_tools 1.10.5 `c2ada82d2f6c0404074a668ba749c7872743aad9`, SWIZZLE 0.8.4
  `6bd88f3a6e9de1f83e64f401e13cbcb5233499fc`, JUDGE 0.4.7 `cf71fb468d483e868834c8c06b650a5d60726967` (CI checkouts, the
  `--expect` values, the real-Judge install, the `ghost` extra, comments and the STACK.md table). ASSAY stays at
  `54248beb5a36600f69de7c816cb2271dda20a879`. (Step 4.)

### Tests

- New: pin spellings refused and a full pin accepted; modified, untracked, ignored and clean joined checkouts; the target
  not asked as a join; balanced Markdown fences; the read-only CI token; the ASSAY dependency note.
- Edited because the behaviour they assert is what a step changed: the tag-sentence test in `tests/test_docs.py`
  (step 3); the versions written next to each pin in `tests/test_docs.py`, and one docstring in
  `tests/test_real_judge_loop.py` (step 4).

## [0.13.6] - 2026-10-21

No change to the behaviour of the `warden` package; `CONTRACT` is still `"1"`. This release sits on top of the 0.13.5
commit `decc3c3b5af479ad0eef3df4d66dbcb21e90897c`.

### Changed

- The CNS pin is spelled as the tag, `cns @ git+https://github.com/wking53214/CNS.git@v1.9.0`, in place of the full commit
  SHA. The tag peels to `da18e411743d4e3b0e783105394d845fb1c16746`; STACK.md's CNS row names `v1.9.0` and that commit.
  `tests/test_docs.py` now requires the exact tag spelling and that STACK.md row. This supersedes the 0.13.5 note that
  the pin stays a full commit SHA.
- The tested set's ASSAY pin moved from `01c713a316dc0513d30e566fffe4d94536888e81` to the head of ASSAY's `main`,
  `54248beb5a36600f69de7c816cb2271dda20a879` (PR #23, ASSAY 0.11.2). CI (both checkouts and the `--expect` value), the
  CI header comments and STACK.md say so.

## [0.13.5] - 2026-10-21

No change to the behaviour of the `warden` package; `CONTRACT` is still `"1"`. This release sits on top of the 0.13.4
commit `36e98433f4928b7d12905f02b56e55ee1943b56e`, which the satellites pinned, and merges `main`.

### Changed

- Merged `origin/main` (`72e5745`), which pins CNS at v1.9.0. The pin stays a full commit SHA, not the tag:
  `cns @ git+https://github.com/wking53214/CNS.git@da18e411743d4e3b0e783105394d845fb1c16746  # v1.9.0` (pip treats a tag
  URL and a SHA URL as two sources and will not resolve them together). STACK.md states the CNS pin in the tested set,
  and `tests/test_docs.py` fails if the `pyproject.toml` pin is not a full SHA with its tag, or STACK.md disagrees.
- The tested set's ASSAY pin moved from `4c415567d1c1cb2c1a9e8f343a7a11a5064258c8` to the head of ASSAY's `main`,
  `01c713a316dc0513d30e566fffe4d94536888e81` (ASSAY 0.11.2, cns extra at CNS v1.9.0). ASSAY's work was squash-merged into
  `main` as its parent `b6b1ccf1feb39993e50d38b875cd52ff0bd38039`, whose tree is identical to the ASSAY branch head
  (`023589f`); the old pin was a commit of that branch, so it no longer lay on `main`. CI (both checkouts and the `--expect`
  value), the CI header comments, STACK.md and `tests/test_docs.py` say so. ghost_tools, SWIZZLE and JUDGE are unchanged.
- Four comments in `warden/` (`roles.py`, `models.py`, `suite.py`, `epistemic.py`) said "cns 1.7.0"; they now name the
  pinned CNS, v1.9.0. Comment text only.

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

- Two older tests (`test_the_real_root_is_used_even_when_the_target_has_a_fake`,
  `test_a_scan_that_hangs_is_ghost_being_down_not_a_hang`) built their instrument root as a bare copy of the package. A root
  must now be a checkout with a commit and a version, so their fixtures make it one (`tests/gitutil.py::as_checkout`);
  what they assert is unchanged. New tests: `tests/test_messages.py`, and in `tests/test_instrument_roots.py` the audit's
  run with site-packages as the root, plain copies with and without the flag, and the editable-install checkout.

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
