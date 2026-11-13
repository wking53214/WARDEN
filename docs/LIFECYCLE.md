# Lifecycle and execution model

How a run goes: options, the whole circuit in one command, exit codes, held results, instrument roots, tests and CI.

*Moved from the README on 2026-11-10 with the text unchanged. Where it says "the README", "above" or names a section (WHAT WORKS, KNOWN DEFECTS, LIFECYCLE and so on), it means this documentation set; the map is in [README.md](../README.md).*

## LIFECYCLE / EXECUTION MODEL

CLI over a git work tree. Default is read-only. Writes require
`--authorize ACTOR --reason TEXT`.

`warden tagteam PATH --drafter MODULE:FACTORY --finisher MODULE:FACTORY --judge MODULE:FACTORY --ghost-root GHOST_TOOLS --swizzle-root SWIZZLE --assay-root ASSAY --assay-floor N [--allow-uncommitted-instruments]`
runs the whole loop and the hand-off (`--max-cycles`, default 10). Without
`--drafter` it can only observe (`INCONCLUSIVE`). Without `--finisher` it stops
when the loop converges.

**The whole circuit in one command.** `--stack DIR` names a folder that holds checkouts of
the other six repositories, `ghost_tools`, `swizzle`, `assay`, `drafter`, `judge` and
`burnish` (the circuit is five repositories; `drafter` and `burnish` are released from it but a bare `--stack` still requires them; folder names matched without regard to case, so `SWIZZLE` and `swizzle` are the
same), and fills `--ghost-root`, `--swizzle-root`, `--assay-root`, `--drafter`
(`drafter.seat:Drafter`), `--judge` (`judge.seat:Judge`) and `--finisher`
(`burnish.finisher:Burnish`) from them. An option you give explicitly wins over the folder's
copy. There are two modes. **`--stack DIR` alone:** all six must be there; a missing one is a
usage error (exit 2) that names it. **`--stack DIR --stack-manifest FILE` (or `--cns DIR`):** the
pinned manifest says which checkouts the circuit consists of. `ghost_tools`, `swizzle`, `assay`,
`judge` and `warden` (the five circuit members) must all be named by the manifest, whatever options the run gives, and
present in the folder: a manifest that omits one, `warden` included, or a folder that lacks one the manifest
names, is a usage error naming it (exit 2, before anything is applied). The `warden` checkout is pinned to its commit
and must have no uncommitted changes, exactly like the other four. `drafter` and `burnish` are
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
spelling is refused). Every named checkout is verified against the folder: the commit it reports and the files git reports as changed
(wrong commit, missing folder, not a git checkout, uncommitted changes in it: usage error, nothing runs; ignored
files do not count) and joined for Ghost,
the target itself excepted (a clone of the target at the same commit is verified like the others but not joined,
since it is the same repository). **Every stack folder the run uses is vetted.** The folders a run uses are the ones
`--stack` fills in: the three instrument roots and the three seats, except any whose option you gave explicitly.
With a manifest, each of them must be named by it (a folder the manifest does not cover has no pinned commit, so
the run refuses and names it), at the pinned commit, and with no uncommitted changes. Without a manifest,
each must have no uncommitted changes (a folder that is not a git checkout cannot be asked and is let through). A
`JUDGE` or `DRAFTER` seat folder that the manifest does not cover is therefore refused, not let through unchecked. What
is checked is the commit the checkout reports and the files git reports as changed, read with replace refs ignored
(since 0.16.6 every git call sets `GIT_NO_REPLACE_OBJECTS=1`; `tests/test_replace_refs.py`). Grafts are not honoured by
current git; that was not separately tested. The
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

**`--isolate-seats`.** Runs the Drafter, the Finisher and the Judge, each in its own confined program (details and limits in `docs/LIMITS.md`). Off by default. On a machine that cannot confine it the run stops as `SEAT_NOT_LOADED` and nothing is run. Each isolated seat's entry under `versions.seats` carries `"isolated": true`; without the flag the key is absent. The claim seat is built by Warden and still runs inside it; a warning on standard error says so.

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
run up to `v0.12.0`, plus `v0.16.5` (see the top of this README). Merge seats before the Warden change that
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
the Judge decides. Warden applies and measures the edit and names it protected; the hold is the Judge's
ruling. With a Judge that rules it `INSUFFICIENT` (the tested one does), the run ends held (`ACCEPT_UNVERIFIED`) by
digest for a named person to keep or drop with `warden keep` (the owner's ruling, 2026-10-28); with a Judge that
returns `ACCEPT` the run ends `ACCEPT`; a Judge older than that ruling says REJECT instead and the whole tree is put back. Names are compared
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

Most tests start real `pytest` or `warden` processes, so the full run takes minutes (`pytest -n 2` helps). CI runs the suite on Python 3.11, 3.12 and 3.13, plus `ruff check .`, `mypy`, an install check of the `ghost` extra (`pip check`) and the circuit smoke test, which also seats the real Judge. Every action and every sibling repository is pinned by full commit SHA, and CNS by the tag `v3.0.0` (the tested set is in [STACK.md](STACK.md): the last set this repository's CI tested on its own, not the heads of anything); to bump a sibling, change its SHA in `.github/workflows/tests.yml` (every job that checks it out, and the `--expect` line), in `pyproject.toml` for ghost_tools, and in STACK.md, then run the whole job set. CI sets `WARDEN_FAIL_ON_SKIP=1`, so a skipped test fails the job (`tests/conftest.py`); it installs the pinned Judge and checks out the pinned ASSAY so nothing skips.
