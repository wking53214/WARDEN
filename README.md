# Warden

*Formerly Elegant. Renamed in October 2026; the role is unchanged.*

The discipline of change.

**In plain words.** Warden is a command line tool for the person who owns a code project and wants a proposed change checked before it is allowed to stay. You give it a project folder, a change and the name of the person who approves it. It runs the project's own tests before and after, rescans with an inspector (ghost_tools), asks a separate judge (Judge) for a verdict, and undoes the change if anything fails. It prints one JSON record, and only exit code 0 means the change was accepted. It works on Python projects, and on Rust projects through `cargo test`. To do real work it needs checkouts of its four sibling repositories (see ROLE IN THE CIRCUIT).

Warden decides whether a change to code may be made, whether it stands once
made, and what is recorded about it. It does not decide what makes code
beautiful. That work lived in [Burnish](https://github.com/wking53214/burnish),
which plugs into Warden through one small interface; Burnish is released from the circuit by owner ruling (2026-10-29)
and still works on its own.

It is not a formatter, not a linter, not a beauty scorer, and not an automatic
rewriting bot. Nothing is written without a named human.


## WHAT THIS IS

A governor, and the only component authorized to apply changes within the assurance circuit. It runs a loop. Ghost
Tools reports what is wrong, and a change enters. The general way in is the claim seat (`--claim-commit` or `--claim-diff`): a real
change from any actor, which Warden proposes once and then nothing. A Drafter is an optional extra proposer, not a requirement.
Warden then asks, in
order: did a person grant this, are SWIZZLE's own proofs sound, is the target's
test suite green, did it stay green after the change, and does Ghost agree
nothing new appeared. Any "no" stops the change or puts it back. The loop
cycles until nothing is left to propose (or a cycle limit is
hit). A Finisher is optional and outside the circuit: Burnish was released, and nothing seats one unless you pass `--finisher`. Where one is seated, Warden then hands the code to it once, together with the facts it measured (the suite result and what Ghost still reports), so the Finisher counts and detects nothing itself. The Finisher beautifies the code and writes the final README. The Finisher's change goes through
the same gate.

The circuit is five repositories: ghost_tools (observes), SWIZZLE and ASSAY (instruments that attack the governor and grade the detector), JUDGE (decides ACCEPT, REJECT or INSUFFICIENT, which Warden reports as a hold) and WARDEN (applies, measures, refuses, puts the tree back). DRAFTER, BURNISH and WATCHER_MCU are released from the circuit by owner ruling (2026-10-29): not seats, nothing deleted, each still works on its own. CNS holds the contracts. See STACK.md.

Version `0.17.0` (seat contract `"1"`, unchanged). The history of every release is in
[CHANGELOG.md](CHANGELOG.md); the design is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and the exit codes in
[docs/EXIT_CODES.md](docs/EXIT_CODES.md). The repositories that pin Warden (Judge, and the released Drafter, Burnish and WATCHER_MCU) pin it by full commit SHA, not by
tag; each one's `pyproject.toml` names the commit. Release tags exist up to `v0.12.0`, and one more, `v0.16.5` (created 2026-11-05 on commit `8f808d9`); the `0.13.x` releases are not
tagged, and `0.14.0` is not tagged either, nor are `0.15.0`, `0.15.1`, `0.16.0`, `0.16.1`, `0.16.2`, `0.16.3`, `0.16.4`, `0.16.6` and `0.17.0`. The older `v0.10.0` tag does not match its tree (it points at a tree whose `__version__` is `0.9.0`). Tagging is
the owner's decision.

## ROLE IN THE CIRCUIT

Warden sits in an assurance circuit of five repositories. It is the governor: the only part that writes, and only after a named human approves.

| Part | Repository | Role |
|---|---|---|
| Answer key | ASSAY | Supplies known failure modes with independently known answers |
| Inspector | ghost_tools | Observes the target and reports defects |
| Adversary | SWIZZLE | Proves its own planted defects, and attacks Warden's governance rules |
| Governor | Warden | Enforces human approval, measures the test suite, requires rescan, restores rejected changes |
| Evidence evaluator | Judge | Reads the run's evidence and returns ACCEPT, REJECT, or INSUFFICIENT |

The table above matches the authoritative one in [STACK.md](STACK.md). The circuit is an assurance layer, not the live execution path. What backs each main claim, and what does not, is in [docs/VERIFICATION.md](docs/VERIFICATION.md). CNS holds the shared interoperability contracts and is not a decision-making seat. See [STACK.md](STACK.md) for the full description.

## WHAT THE HUMAN GRANT IS, AND WHAT WARDEN DOES NOT GOVERN

`--authorize NAME` is authorization supplied to Warden: a named person says "I approve this change". It is not authentication. Warden does not check that the name is really that person (any text works), so the boundary rests on who is allowed to run the command. Warden also does not sandbox anything: the target's tests and the seats run with the user's own access.

Warden does not:

- govern the live execution path of the owner's wider library (≡TACK); it is an assurance layer beside that path;
- replace CNS, which supplies shared contracts and makes no decisions;
- prove who a human is from a supplied name;
- guarantee isolation of untrusted code (the Judge can be run in its own confined program with `--isolate-seats`; the Drafter, the Finisher and the target's own suite are not confined yet);
- certify its own instruments (ghost_tools, SWIZZLE, ASSAY) or its own Judge's verdict;
- guarantee that a change that passes every check is correct (the `mutate` check is declined by design).

## WHERE THIS FITS

Warden belongs to the assurance circuit: five repositories that check changes to code. Their jobs: ASSAY is the answer key, ghost_tools is the inspector, SWIZZLE is the adversary that tests the others, Warden is the governor, and Judge is the evidence evaluator that gives the verdict.

- **Warden receives** a proposed change (through the claim seat, or from an optional Drafter), the inspector's findings from ghost_tools, the proofs and attacks from SWIZZLE, and the answer-key score from ASSAY.
- **Warden hands on** the measured evidence to Judge, and one JSON record (and optionally a receipt) to the person who ran it.
- **Place in ≡TACK.** ≡TACK is the owner's whole library of repositories. The circuit sits in its assurance layer, beside the live decision path and not on it (see [STACK.md](STACK.md)). Warden is not shared infrastructure: only the circuit uses it, and the released Drafter and Burnish still import its data shapes.

## CNS CONNECTION

CNS is the repository that holds the shared row shapes the circuit repositories agree on.

- **This repository's side:** `warden/suite.py` is the file CNS's connection list (`contracts/cns-links.json` in CNS) names for Warden. Five more modules (`swizzle`, `tagteam`, `roles`, `epistemic`, `models`) also import CNS rows. CNS is required, not optional, and is pinned at the tag `v3.0.0`.
- **CNS's side:** `contracts/warden-stack.json` in CNS carries Warden.
- **List status:** two-way (checked against CNS commit `03eca66` on 2026-11-10).
- **Built, tested, used:** the connection is built. The tests pass with CNS installed (`tests/test_cns_strict.py` and the pin checks in `tests/test_docs.py`). Every normal run uses it: each run builds a CNS suite row and reads CNS finding, attack and seat rows. The connection list does not mark Drafter, Burnish and WATCHER_MCU as released; that is CNS's to update.

## LICENSE

Apache-2.0, copyright William N. King (see `LICENSE` and `NOTICE`).

## HOW TO INSTALL AND RUN

Python 3.11, 3.12 or 3.13. The only runtime dependency is `cns`, installed from GitHub at the tag `v3.0.0`. Dated record: on 2026-10-22 (Warden 0.13.x, before the roster change of 2026-10-29) the first two blocks of commands below were run as written in a fresh virtual environment on Python 3.12 (from a clone of this repository), and `pip check` reported no broken requirements. That says nothing about later versions; CI installs the package on every push.

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

It needs the Judge installed (`pip install --no-deps` of the pinned JUDGE commit in STACK.md), and numpy and matplotlib installed normally (the versions CI uses are in `.github/workflows/tests.yml`). Install them with their own dependencies (`pip install numpy matplotlib`): ASSAY's answer key needs matplotlib's own dependencies (Pillow and the rest), and installed with `--no-deps` only 56 of the key's 60 claims are proven, so the key is NOT PROVEN and Ghost is not graded.

To run the tests, the linter and the type checker from a checkout:

```
pip install -e '.[dev]'
pip install --no-deps "git+https://github.com/wking53214/JUDGE@<the JUDGE commit in STACK.md>"
ASSAY_ROOT=/path/to/an/ASSAY/checkout WARDEN_FAIL_ON_SKIP=1 pytest -q -rs
ruff check .
mypy
```

Count the tests with `pytest --collect-only -q`; this README states no count, because a number written here goes stale. A test skips when something it exercises is absent: the live ASSAY registry (`ASSAY_ROOT`), the real Judge seat (`judge.seat`) and `cargo`. `WARDEN_FAIL_ON_SKIP=1` turns any skip into a failure, as CI does.

## THE MAIN LIMITS

The full list is in [docs/LIMITS.md](docs/LIMITS.md). The ones to know first:

- `--authorize` takes a name and does not check that it belongs to a real person. The boundary rests on who can run the command.
- The target's tests and the seats run with your own access. Warden notices some misbehavior; it is not a sandbox.
- A change that passes every check can still be wrong: the mutation check is declined by design.
- A plain `ACCEPT` does not mean every Ghost check ran. Declined checks are listed in the run record.
- The loop has been run on scratch projects and on the circuit's own repositories, not on a third-party project ([docs/REGISTRY.json](docs/REGISTRY.json)).
- One human maintainer, with a large share of commits written by an AI assistant, and no independent review recorded.

## DOCUMENTATION MAP

| Read this | To learn |
|---|---|
| [STACK.md](STACK.md) | The authoritative description of the five-seat circuit, and the tested set of sibling commits |
| [docs/VERIFICATION.md](docs/VERIFICATION.md) | What backs each main claim: tested, inspected, demonstrated, unverified |
| [docs/LIFECYCLE.md](docs/LIFECYCLE.md) | How a run works: options, the whole circuit in one command, exit codes, held results, instrument roots, CI |
| [docs/EXIT_CODES.md](docs/EXIT_CODES.md) | The exit codes (generated from the code) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | The run step by step, and the module table |
| [docs/REFERENCE.md](docs/REFERENCE.md) | Why Warden exists, what it owns and does not own, key concepts |
| [docs/WHAT_WORKS.md](docs/WHAT_WORKS.md) | Each working claim with its test or recorded run |
| [docs/LIMITS.md](docs/LIMITS.md) | What does not work, open defects, ceilings, architectural debt |
| [docs/HISTORY.md](docs/HISTORY.md) | What broke and how it was fixed, CNS pin moves, self-hosting records |
| [docs/RELEASE_1_0_CRITERIA_v1.md](docs/RELEASE_1_0_CRITERIA_v1.md) | What must be true before Warden is called 1.0.0 (a plan, nothing built yet) |
| [CHANGELOG.md](CHANGELOG.md) | Every release |
