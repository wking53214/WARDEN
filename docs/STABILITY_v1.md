# Stability

*Version 1 of this page. It takes effect with Warden 1.0.0. Until then it is a draft, and the 0.x releases may still change anything it lists.*

Four things are public: the command line, the exit codes, the run record and the seat contract. Nothing else is. Within 1.x, nothing listed here is removed, and nothing listed here changes its meaning. A release may add new commands, options, record fields and exit codes. Removing or changing a listed thing takes 2.0.0.

`tests/test_stability.py` checks this page against the code, so a listed option, exit code, record field or contract number that goes missing fails the suite.

## 1. The command line

Warden has four commands: `tagteam`, `keep`, `chronicle` and `audit`. Each option below keeps its name and its meaning.

- `tagteam`: `--verbose`, `--ghost-root`, `--drafter`, `--claim-commit`, `--claim-repo`, `--claim-diff`, `--claim-subject`, `--claim-author`, `--judge`, `--finisher`, `--isolate-seats`, `--max-cycles`, `--ghost-timeout`, `--suite-timeout`, `--suite-runner`, `--suite-always`, `--seat-timeout`, `--swizzle-root`, `--assay-root`, `--allow-uncommitted-instruments`, `--assay-floor`, `--from-ghost`, `--stack`, `--join`, `--stack-manifest`, `--cns`, `--authorize`, `--reason`, `--scope`, `--receipt`, `--chronicle`, `--reuse-chronicle-suite`
- `keep`: `--verbose`, `--digest`, `--authorize`, `--reason`, `--chronicle`
- `chronicle`: `--verbose`, `--origin`
- `audit`: `--verbose`, `--ghost-root`, `--from-ghost`, `--authorize`, `--reason`

Not promised: the wording of help text, warnings and messages printed to the screen.

**Isolation.** From 1.0.0, seats and the target's test suite run under operating-system limits by default (Linux only; where the limits cannot be applied the run is refused, not run unprotected). `--isolate-seats` stays accepted. A separate option turns isolation off; it is named in the 1.0.0 release notes.

## 2. The exit codes

The table in [EXIT_CODES.md](EXIT_CODES.md) is the promise: each decision keeps its code. Only 0 means the change was accepted. A decision Warden does not know exits 1, never 0. When SWIZZLE's own proofs do not hold, the record says `INCONCLUSIVE` and the exit is 2; that stays too.

A later release may add a decision. A new decision never exits 0.

## 3. The run record

Every run prints one JSON document, and its `schema` field says `cns.run/1`. These top-level fields keep their names, their meaning and their kind of value (text, number, true or false, list, or record):

`schema`, `decision`, `converged`, `cycles`, `finished`, `put_back`, `held_digest`, `reason`, `notes`, `observed`, `reobserved`, `contract`, `released_seats`, `versions`, `swizzle_sound`, `allow_uncommitted_instruments`, `unmeasured`, `ghost_scan`, `ghost_baseline`, `drafter_skipped`, `informational`, `verdict`, `claim`, `evidence`, `suite_passes`, `chronicle`

Not promised: the wording of `reason` and `notes`, the order of fields, and the order of notes. A field may gain new entries inside it; it does not lose the ones it has.

The record's shape is partly defined by the shared CNS package, which Warden pins. A CNS change that breaks the record is treated as a 2.0.0 change here.

## 4. The seat contract

The contract number is `"1"`. A seat is a class named as MODULE:FACTORY. It declares `requires_contract = "1"` and reads and returns the shared rows from CNS. Warden refuses a seat that declares another number, or none.

- The Drafter has `propose`, the Finisher has `finish`, the Judge has `decide`.
- A seat may also have `scope` (Warden tells it the grant's scope) and `describe_skipped`. Warden uses them only if they are there.
- Isolation changes where a seat runs, not what it is given or what it may return.

## What is not public

The Python modules inside the `warden` package are internal. Importing them from outside is not covered by this page. The documents, the order and wording of messages, the layout of the chronicle folder and the contents of `notes` can change in any release.
