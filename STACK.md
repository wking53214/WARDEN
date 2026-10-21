# Stack role: Warden

**ASSURANCE (not the live decision path).**

The governor. Runs the loop and is the only part allowed to write. A named human grant, the target's suite green before and after, the attacker's proofs, the scanner's re-inspection, and a durable record. Never certifies itself.

## The circuit

Seven repositories, one loop. Warden is the only one that writes, and nothing is
written without a named human.

| # | Part | Repository | Role |
|---|------|------------|------|
| 1 | Answer key | [ASSAY](https://github.com/wking53214/ASSAY) | Known failure modes with independently known answers; the scanner is graded against it before anything is written. |
| 2 | Scanner | [ghost_tools](https://github.com/wking53214/ghost_tools) (Ghost Buster) | Finds defects; findings keep their identity across the loop; says what it could not look at. |
| 3 | Attacker | [SWIZZLE](https://github.com/wking53214/SWIZZLE) | Proves its own planted defects, scores the scanner against the answer key, attacks the governor's rules. |
| 4 | Governor | [Warden](https://github.com/wking53214/Warden) | Runs the loop; the only part allowed to write; human grant, green suite before and after, durable record. |
| 5 | Drafter | [Drafter](https://github.com/wking53214/Drafter) | Proposes one fix at a time, as data. |
| 6 | Judge | [Judge](https://github.com/wking53214/Judge) | Reads the evidence of the whole run and says ACCEPT, REJECT or INSUFFICIENT. |
| 7 | Finisher | [Burnish](https://github.com/wking53214/Burnish) | Once, after the loop: tidies the code and keeps the README's generated facts section. |

```text
CODEBASE
   │
   ▼
SWIZZLE   proves its own instrument (12 planted-defect proofs must all hold)
ASSAY     grades the scanner against the answer key (the key is proven first)
   │         nothing is written if either fails
   ▼
┌─ THE LOOP, until the Drafter has nothing left ──────────────────────────┐
│  GHOST     observe: what is wrong (ghost-* ids)                          │
│  DRAFTER   propose one change, as data, inside the grant's scope         │
│  WARDEN    human grant · suite green before · apply · suite green after  │
│  GHOST     re-inspect: nothing new, or the change is put back            │
└──────────────────────────────────────────────────────────────────────────┘
   │
   ▼
BURNISH   once: tidy the code and the README's facts section
          (applied by Warden under the same gate)
   │
   ▼
SWIZZLE   attacks the governor; every scenario must be held
   │
   ▼
JUDGE     ACCEPT (stands) · REJECT (whole tree put back) · INSUFFICIENT (held for a person)
```

Each seat imports Warden's data shapes and declares `requires_contract = "1"`; Warden
imports none of them. Warden tells the Drafter and the Finisher the grant's scope
(`documentation` or `code`) before it asks them.

**One command runs all seven.** With a clone of each repository in one folder (names matched
without regard to case):

```bash
warden tagteam PATH --stack FOLDER --authorize "Your Name" --reason "why" --scope code

A target that imports a sibling (every repository in this circuit does) is, to Ghost, a scan with a
gap, and the result is held as `ACCEPT_UNVERIFIED` rather than accepted. Join the siblings so the
boundary is measured: `--join PATH` for each, or `--stack-manifest FILE` with a pinned list
(`{"schema": "warden-stack/1", "contract": "1", "repos": {name: commit}}`, each commit the full
40 characters); every named checkout is verified at exactly that commit, with no uncommitted changes, and joined, the target itself excepted. The manifest is the shape CNS is
meant to hold for the circuit.
```

## The tested set

Warden's CI runs against these sibling commits, each a full SHA (ghost_tools, SWIZZLE and JUDGE are on their
branch `claude/horsemen-production-status-5wsndb` and are not tagged; a sibling's branch head may be ahead of its pin).
CNS is the exception: `pyproject.toml` pins it by the tag `v1.9.0`, spelled the same way in every repository of the
circuit, and its row gives the commit the tag peels to.
The ASSAY commit is the head of ASSAY's `main` (`54248be`, PR #23, whose cns extra is at the CNS v1.9.0 tag).
`pyproject.toml` pins the `ghost` extra to the same ghost_tools commit, and `tests/test_docs.py` fails if any
place that states one of them disagrees with the others.

| Repository | Version | Commit |
|---|---|---|
| ghost_tools | 1.10.1 | `5d7a38638b12a75b25c84ab3652e4774acb9aa10` |
| SWIZZLE | 0.8.1 | `8166c47f321ecfb66b8efa72c1deac5d954e8e48` |
| ASSAY | 0.11.2 | `54248beb5a36600f69de7c816cb2271dda20a879` |
| JUDGE | 0.4.3 | `50f90f47660916d99deeb11370dd57bf85922dbe` |
| CNS | v1.9.0 | `da18e411743d4e3b0e783105394d845fb1c16746` |

Exit 0 means `ACCEPT` and nothing else does. Recorded run: 2026-10-14, every seat live on a
scratch repository, `ACCEPT` under both grants; see Warden's `docs/REGISTRY.json`.

```text
Live path: Admission → OBSERVE/Keys → Locks → PERCEIVE → Decision → Conservation → Execution → Custody
Assurance: ASSAY · ghost_tools · SWIZZLE · Warden · Drafter · Judge · Burnish  (this circuit, off the live path)
```

CNS (public, github.com/wking53214/CNS) holds the interoperability contracts. No repository in the circuit modifies it.

See [README.md](README.md).
