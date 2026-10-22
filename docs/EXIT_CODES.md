# Exit codes

Generated from `warden.cli.EXIT_CODES` by `tools/gen_docs.py`; `tests/test_docs.py` fails if it is stale.
Only exit code 0 means the change was accepted, so a CI job can trust the exit code alone.
A decision the code does not know exits 1, never 0.

| code | decisions |
|---|---|
| 0 | `ACCEPT` |
| 1 | `REJECT`, `JUDGE_REJECTED`, `NOT_CONVERGED`, `FINISH_REJECTED` |
| 2 | `USAGE_ERROR`, `SEAT_NOT_LOADED` |
| 3 | `ACCEPT_UNVERIFIED` |
| 4 | `ERROR` |
| 5 | `REFUSED` |
| 6 | `INCONCLUSIVE` |
| 7 | `INTERRUPTED` |

One decision exits with a code that is not its own: when SWIZZLE's own proofs do not hold, the JSON says
`INCONCLUSIVE` (which is otherwise exit 6) and `swizzle_sound` false, and the exit is 2. A SWIZZLE that
does not declare contract 1 (`swizzle --contract` absent, or a different number) is treated the same way,
with the reason in the record.

`ACCEPT_UNVERIFIED` (3) is the distinct code for a run that could not be fully measured: the changes are
put back and held, and nothing stands until a person approves the digest with `warden keep`.

## A stack run that refuses before anything runs

`warden tagteam --stack` exits 2 (`USAGE_ERROR`, "Nothing was run", the folder named) when a stack
folder it will use is not what it should be. The folders it uses are the three instrument roots
(`ghost_tools`, `swizzle`, `assay`) and the three seats (`drafter`, `judge`, `burnish`) that `--stack`
fills in; one whose option was given explicitly is not used from the stack. The rule has three parts:

- With a manifest (`--stack-manifest` or `--cns`), every used folder must be named by it. A folder the
  manifest leaves out has no pinned commit to be checked against.
- With a manifest, every folder it names must be at exactly the pinned commit.
- With or without a manifest, every used folder must have no uncommitted changes (see the README for what
  counts). A clone of the target at the same commit as a stack member is still checked; only the join for
  Ghost is skipped. The governed target itself is excluded.

## The ASSAY floor has two defaults

A graded ASSAY score below the floor is a `REJECT` (exit 1) that Warden decides itself, whatever the Judge
said. The command line and the library do not start from the same floor:

| caller | default | what it means |
|---|---|---|
| `warden tagteam` | `--assay-floor 3` (`warden.cli.CLI_ASSAY_FLOOR`) | Ghost must catch at least 3 known failure modes, or the run is a `REJECT`. |
| `TagTeam(...)` in the library | `assay_floor=0` (`warden.tagteam.LIBRARY_ASSAY_FLOOR`) | The floor is not enforced: a graded score is recorded, and the notes say the floor was not enforced. |

A library caller who wants the command line's behaviour passes `assay_floor=3`. `0` is the one
explicit way to skip the floor, in either place; below 0 is a usage error on the command line. A floor is
only applied to a score that was measured: when ASSAY could not be graded, `assay` is in `unmeasured` and
the run is never a plain `ACCEPT`, whatever the floor.

## What each code means

This is the text of `warden tagteam --help`.

```text
exit codes (only 0 means the change was accepted):
  0  ACCEPT. Measured, judged, and standing.
  1  REJECT, JUDGE_REJECTED, NOT_CONVERGED, FINISH_REJECTED, or any other rejection.
  2  usage error (the JSON says USAGE_ERROR), a seat could not be loaded, or SWIZZLE's own proofs are
     unsound (the JSON says INCONCLUSIVE; the exit is still 2). Nothing was written.
  3  ACCEPT_UNVERIFIED. A check did not run or the Judge could not decide. Changes were put back and
     held; keep them only with `warden keep`.
  4  ERROR. A seat failed, timed out, or gave the wrong kind of answer (an unknown Judge label counts),
     or the findings file given to --from-ghost could not be used. Nothing was approved and the tree was
     put back.
  5  REFUSED. No human authorization, or the folder has uncommitted git changes (commit or stash
     them first). A proposal may have been shown; nothing was written.
  6  INCONCLUSIVE. A needed measurement could not be made (Ghost down, a red suite from the
     start, an unusable ASSAY key), another run holds the target, or the folder is too big to put
     back. Nothing was written.
  7  INTERRUPTED. SIGTERM, SIGHUP or SIGINT arrived. The tree was put back as it was found.
The command always prints valid JSON on stdout; `reason` says why in one sentence.
```
