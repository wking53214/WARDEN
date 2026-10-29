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
```

A target that imports a sibling (every repository in this circuit does) is, to Ghost, a scan with a
gap, and the result is held as `ACCEPT_UNVERIFIED` rather than accepted. Join the siblings so the
boundary is measured: `--join PATH` for each, or `--stack-manifest FILE` with a pinned list
(`{"schema": "warden-stack/1", "contract": "1", "repos": {name: commit}}`, each commit the full
40 characters); every named checkout is verified at exactly that commit, with no uncommitted changes, and joined,
the target itself excepted. The manifest must name every stack folder the run uses (the three instrument roots and
the three seats): an unnamed one is refused. Without a manifest those folders still must have no uncommitted
changes. The manifest is the shape CNS is meant to hold for the circuit.

## The tested set

Warden's CI runs against these sibling commits, each a full SHA. They are the last set this repository's CI tested on its
own; none is claimed to be the head of any repository's `main`, none is tagged, and a sibling may have moved on. Whether the
set that lands works together is checked by the `stack` job in the CNS repository, not here.
CNS is the exception: `pyproject.toml` pins it by the tag `v2.1.0`, spelled the same way in every repository of the
circuit, and its row gives the commit the tag peels to.
The ASSAY commit (`8f6ef85`, 0.11.7) has its cns extra at the CNS v2.1.0 tag.
`pyproject.toml` pins the `ghost` extra to the same ghost_tools commit, and `tests/test_docs.py` fails if any
place that states one of them disagrees with the others.

| Repository | Version | Commit |
|---|---|---|
| ghost_tools | 1.10.10 | `99f3d5209bc98657db91eea1c25e833136ea61ab` |
| SWIZZLE | 0.8.10 | `b7451ad417cd166d10d4897a6b7dbe076ec02029` |
| ASSAY | 0.11.7 | `8f6ef8599d9acb2a2672a5a78c36ec0e276fa78c` |
| JUDGE | 0.4.8 | `e5c3f98f0f3998a8c5dac458ad0fcf4e050eb074` |
| CNS | v2.1.0 | `fde931ffa89aebec95647742256ad53033bd3d02` |

ASSAY's answer key needs numpy and matplotlib installed normally, with matplotlib's own dependencies (Pillow,
`packaging` and the rest). Installing them with `--no-deps` leaves 56 of the 60 claims proven, so the key is NOT PROVEN
and Ghost is not graded: install them with `pip install numpy matplotlib` (the CI `circuit` job pins the versions).

Exit 0 means `ACCEPT` and nothing else does. Recorded run: 2026-10-14, every seat live on a
scratch repository, `ACCEPT` under both grants; see Warden's `docs/REGISTRY.json`.

```text
Live path: Admission → OBSERVE/Keys → Locks → PERCEIVE → Decision → Conservation → Execution → Custody
Assurance: ASSAY · ghost_tools · SWIZZLE · Warden · Drafter · Judge · Burnish  (this circuit, off the live path)
```

CNS (public, github.com/wking53214/CNS) holds the interoperability contracts. No repository in the circuit modifies it.

See [README.md](README.md).
