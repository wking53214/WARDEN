# Verification matrix

What backs each main claim about Warden, and what does not. Written 2026-11-10 against commit `441dd9a`.
It uses four labels, and never calls something proven that was only read:

- **TESTED**: an automated test passes. Counts below are from a run on 2026-11-10 (Python 3.13).
- **INSPECTED**: someone read the code or a file. Nothing was run.
- **DEMONSTRATED**: it happened in an integrated run (`tools/circuit_smoke.py --real-judge`) with live ghost_tools, SWIZZLE and ASSAY at the pins in [STACK.md](STACK.md) and the real Judge, on a scratch project. That run passed on 2026-11-10.
- **UNVERIFIED**: no evidence here. Say so rather than assume.

Full suite on commit `427c4ff` (before later documentation-only changes): 1253 passed, 0 skipped, with `ASSAY_ROOT` set and skips treated as failures. `ruff` and `mypy` were clean. This page does not claim a re-run after that commit.

## The claims

| Claim | TESTED | INSPECTED | DEMONSTRATED | UNVERIFIED |
|---|---|---|---|---|
| Only Warden writes to the target | `test_independence` (2), `test_closing_false_accepts` (60), `test_closing_false_accepts_2` (29): a seat that writes the tree, `.git` hooks or file descriptor 1 is caught and put back | The file-writing calls in `warden/` sit in `textio`, `models` (apply), `guard` and `tagteam` (restore), plus `claim` (a throwaway folder, to fingerprint the claimed commit), the receipt and audit files in `cli`, and a private suite result file. Each call site was listed; not every path was traced | The smoke run changed only the file it was asked to change | Seats run inside Warden's own process, so the watch catches a seat that writes the tree but not one that alters Warden's objects. An instrument's own subprocess writes are not independently watched |
| A named human authorization is required | `test_authorization` (13), `test_authorization_scope` (12), `test_tagteam` (9): no grant, no write; stack names cannot grant | `warden/authorization.py` | The smoke run: observe-only exits 6 and writes nothing | The name is an unauthenticated string. Warden does not check that it is the named person |
| A failed change is restored | `test_closing_false_accepts` (60), `test_held_results` (10), `test_cli_integration` (34) | `warden/guard.py` snapshot and restore | The smoke run: a rejected run left the tree as found, and a held test edit did not stand | A SIGKILL at any moment other than the keep test; files git ignores; trees over 200 MB are refused, not restored |
| The suite must pass before and after | `test_rule7_suite_gate` (6) | `warden/suite.py` reads pytest's exit status and counts, not printed text | The smoke run measured the scratch project's suite around a change | The Rust (`cargo`) path is tested but has no recorded live run. The target's suite is not sandboxed |
| SWIZZLE challenges the governor | `test_judge_independence` (22: attacks that did not run hold the run), `test_swizzle_contract` (21), `test_assay_in_loop` (6), `test_horsemen_circuit` (19) | `warden/swizzle.py` | SWIZZLE's 12 proofs held, and a plain `ACCEPT` ended with nothing unmeasured. That means the attacks on the governor ran (INFERRED: they would otherwise be listed as unmeasured) | SWIZZLE's attacks have been reported "not run" under heavy machine load; the cause was not found (see README) |
| Judge evaluates the evidence | `test_judge_seat` (10), `test_judge_independence` (22) | Judge's own README | The real Judge returned `ACCEPT` on a clean change and `INSUFFICIENT` when a test file changed (pinned JUDGE `8f976c6`) | Judge's own correctness was not audited here. No recorded run in which a real Judge reads `finisher_ran` |
| CNS supplies the shared contracts | `test_cns_strict` (5); the pin checks in `test_docs` | Six `warden/` modules import CNS rows. `pyproject.toml` pins CNS `v2.3.0`. CNS's `contracts/cns-links.json` lists Warden two-way, checked at CNS commit `03eca66` | The smoke run used CNS `v2.3.0` end to end | CNS's own `stack` job was not run here |
| Drafter and Finisher are optional | `test_stack_released` (36), `test_claim_seat` (32) | `STACK.md` and the README | A run with no Finisher ended `ACCEPT` (the smoke run says "No finisher configured") | The smoke run uses a stub Drafter. A run with no Drafter at all, through the claim seat with live instruments, is recorded in `STACK.md` (a CNS canary at Warden 0.16.4) but was not repeated here |

## What this page does not show

- Every test passes in CI on the latest commit. That needs the repository's Actions page.
- That the circuit works on a project outside its own scratch projects. `docs/REGISTRY.json` says no such run is recorded.
- That a passing test proves its sentence. Tests were run, and each was not read line by line.
- Independent review. The author and an AI assistant wrote most of the code and documents.
