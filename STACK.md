# Stack role: Warden

**ASSURANCE (not the live decision path).**

The governor. Runs the loop and is the only part allowed to write. A named human grant, the target's suite green before and after, the attacker's proofs, the scanner's re-inspection, and a durable record. Never certifies itself.

## The circuit

Five repositories, one loop. Warden is the only one that writes, and nothing is
written without a named human.

| # | Part | Repository | Role |
|---|------|------------|------|
| 1 | Answer key | [ASSAY](https://github.com/wking53214/ASSAY) | Known failure modes with independently known answers; the scanner is graded against it before anything is written. |
| 2 | Scanner | [ghost_tools](https://github.com/wking53214/ghost_tools) (Ghost Buster) | Observes: finds defects; findings keep their identity across the loop; says what it could not look at. |
| 3 | Attacker | [SWIZZLE](https://github.com/wking53214/SWIZZLE) | Proves its own planted defects, scores the scanner against the answer key, attacks the governor's rules. |
| 4 | Governor | [Warden](https://github.com/wking53214/Warden) | Applies, measures, refuses and puts the tree back; the only part allowed to write; human grant, green suite before and after, durable record. |
| 5 | Judge | [Judge](https://github.com/wking53214/Judge) | Reads the evidence of the whole run and says ACCEPT, REJECT or INSUFFICIENT; Warden reports INSUFFICIENT as a hold. |

Any actor's real change enters through Warden's claim seat (`--claim-commit` or `--claim-diff`);
an optional Drafter may propose one instead. There is no finisher in the loop.

```text
CODEBASE
   │
   ▼
SWIZZLE   proves its own instrument (12 planted-defect proofs must all hold)
ASSAY     grades the scanner against the answer key (the key is proven first)
   │         nothing is written if either fails
   ▼
CLAIM SEAT  a real change from any actor (--claim-commit or --claim-diff),
            or one proposal from an optional Drafter
   │
   ▼
┌─ WARDEN applies and measures ───────────────────────────────────────────┐
│  GHOST     observe: what is wrong (ghost-* ids)                          │
│  WARDEN    human grant · suite green before · apply · suite green after  │
│  GHOST     re-inspect: nothing new, or the change is put back            │
└──────────────────────────────────────────────────────────────────────────┘
   │
   ▼
SWIZZLE   attacks the governor; every scenario must be held
   │
   ▼
JUDGE     ACCEPT (stands) · REJECT (whole tree put back) · INSUFFICIENT (reported as a hold)
```

Each seat declares `requires_contract = "1"` and reads and returns the shared rows defined in
CNS; Warden imports none of them. Warden tells a Drafter, when one is seated, the grant's scope
(`documentation` or `code`) before it asks it.

**One command runs the circuit.** With a clone of each repository in one folder (names matched
without regard to case):

```bash
warden tagteam PATH --stack FOLDER --stack-manifest stack.json --claim-commit SHA --authorize "Your Name" --reason "why" --scope code
```

A bare `--stack` still requires all six checkouts (`ghost_tools`, `swizzle`, `assay`, `judge`,
`drafter` and `burnish`). Only a pinned `--stack-manifest` that omits `drafter` and `burnish`,
with a folder that lacks them, runs without them, and the run record lists `released_seats`.
Exit 0 means `ACCEPT` and nothing else does. Every run declines eight Ghost checks (mutate, kernel, structure, tests, project, secrets, correlate,
ledger) since ghost_tools 1.10.11; a record that says seven describes a dated earlier run.

A target that imports a sibling (every repository in this circuit does) is, to Ghost, a scan with a
gap, and the result is held as `ACCEPT_UNVERIFIED` rather than accepted. Join the siblings so the
boundary is measured: `--join PATH` for each, or `--stack-manifest FILE` with a pinned list
(`{"schema": "warden-stack/1", "contract": "1", "repos": {name: commit}}`, each commit the full
40 characters); every named checkout is verified at exactly that commit, with no uncommitted changes, and joined,
the target itself excepted. The manifest must name every stack folder the run uses: `ghost_tools`, `swizzle`, `assay` and `judge` always,
and `drafter` and `burnish` when the folder holds them (a pinned manifest that omits them, with a folder that lacks them,
releases them, and the record lists `released_seats`). An unnamed folder that is present is refused. Without a manifest
those folders still must have no uncommitted changes. The manifest is the shape CNS is meant to hold for the circuit.

## The tested set

Warden's CI runs against these sibling commits, each a full SHA. They are the last set this repository's CI tested on its
own; none is claimed to be the head of any repository's `main`, none is tagged, and a sibling may have moved on. Whether the
set that lands works together is checked by the `stack` job in the CNS repository, not here.
CNS is the exception: `pyproject.toml` pins it by the tag `v2.3.0`, spelled the same way in every repository of the
circuit, and its row gives the commit the tag is (a lightweight tag, so the tag is the commit).
The ASSAY commit (`11475f3`, 0.11.10) has its cns extra at the CNS v2.3.0 tag. The JUDGE commit (`8f976c6`, 0.5.5) depends on CNS at the v2.3.0 tag too; Judge is installed with `--no-deps`, so CNS there is this repository's pin. The Judge moved from 0.5.1 to 0.5.3 in this set so that Warden's own `circuit` job exercises the rulings of the Judge that ships.
`pyproject.toml` pins the `ghost` extra to the same ghost_tools commit, and `tests/test_docs.py` fails if any
place that states one of them disagrees with the others.

| Repository | Version | Commit |
|---|---|---|
| ghost_tools | 1.10.14 | `00d94d6dbd32ae3dde7f54d04219e66c814908c4` |
| SWIZZLE | 0.8.13 | `63467947f169577e1a56ccc982f057ab32af1798` |
| ASSAY | 0.11.10 | `11475f30867e1565d3614f5c059d160ee466defd` |
| JUDGE | 0.5.5 | `8f976c6875f0564b25792524f24ebc2cea7b420d` |
| CNS | v2.3.0 | `41592fb7b6735abe140f745353c09ba3eed8e7a2` |

ASSAY's answer key needs numpy and matplotlib installed normally, with matplotlib's own dependencies (Pillow,
`packaging` and the rest). Installing them with `--no-deps` leaves 56 of the 60 claims proven, so the key is NOT PROVEN
and Ghost is not graded: install them with `pip install numpy matplotlib` (the CI `circuit` job pins the versions).

## Released from the circuit

DRAFTER, BURNISH and WATCHER_MCU are released from the circuit by owner ruling (2026-10-29). They are
not seats of the circuit Warden runs. Nothing was deleted, and each still works on its own as its
README describes. CNS holds the contracts and records the ruling in `docs/RELEASED_SEATS.md`. An
earlier recorded run (2026-10-14, every seat live on a scratch repository, `ACCEPT` under both grants;
see Warden's `docs/REGISTRY.json`) used the older circuit that seated them.

```text
Live path: Admission → OBSERVE/Keys → Locks → PERCEIVE → Decision → Conservation → Execution → Custody
Assurance: ASSAY · ghost_tools · SWIZZLE · Warden · Judge  (this circuit, off the live path)
```

CNS (public, github.com/wking53214/CNS) holds the interoperability contracts. No repository in the circuit modifies it.

See [README.md](README.md).
