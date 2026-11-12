# What 1.0.0 means for Warden (criteria, version 1)

*Written 2026-11-12 from the owner's decisions of that day. This is a plan, not a record of work done. Nothing below is built or verified yet. Warden is at 0.16.6 and stays at 0.x until every "must" line is true.*

## The promise

A 1.0.0 Warden means two things. First, the command line, the exit codes, the run record format and the seat contract will not change without a major version bump. Second, the governing loop has been shown to work outside the five-seat circuit that built it, and seats can no longer reach Warden's own memory.

## Must be true before 1.0.0

1. **One recorded live run on a repository that is not one of the five seats.** Any non-seat repository counts, including one the owner wrote. The result goes into `docs/REGISTRY.json`. Today the recorded runs are scratch repositories and clones of the circuit's own repositories ([LIMITS.md](LIMITS.md)).
2. **One recorded run in which a real Judge reads the Finisher field (`finisher_ran`).** Only a stand-in Judge is tested today. This probably needs a Judge update first, because the Judge version in the tested set does not use the field.
3. **Tags.** 1.0.0 is tagged, and so is every release after it. Older history is left as it is, with the explanation already in the README and CHANGELOG.
4. **A stability page** that names the public interface: the command line, the exit codes, the run record format and the seat contract. Anything not named there may change in a minor release.
5. **Seats run in separate processes with operating-system limits.** The design is below. It ships behind an opt-in flag in a 0.x release first, the live runs in items 1 and 2 are made with it switched on, and it becomes the default in 1.0.0.

## Nice to have, not blocking

- A run on macOS.
- A live run on a Rust project.

## Item 5 design: isolated seats

- **What changes.** Each seat runs as its own program and talks to Warden through plain messages. A seat can no longer change Warden's own objects in memory, which is the "seats run inside Warden's own process" limit in [LIMITS.md](LIMITS.md).
- **Platforms.** Linux only, matching CI today. On any other system Warden refuses to run seats in this mode instead of running them unprotected.
- **Seat rights.** A seat can read the governed repository and its own code. It cannot write anywhere and cannot reach the network. It gets a throwaway scratch folder if it needs one. Warden alone applies changes.
- **The target's test suite.** It runs on the real tree under the same limits and no network. It may write only to a scratch folder and a short named list of cache folders (the pytest cache is an example). A suite that needs to write anywhere else fails as a refusal, never as a pass.
- **Seat contract.** It stays `"1"` unless testing shows it must change. Judge, Drafter, Burnish and WATCHER_MCU pin Warden by commit, so they move when they choose to.
- **Known risks.** A seat that writes today (Ghost's cache, for example) will fail until it is given scratch space. A target whose suite writes inside its own repository will be refused. This is the largest item on the list and needs its own build and test pass.

## Accepted, not fixed, for 1.0.0

Items in [LIMITS.md](LIMITS.md) other than the two item-5 limits (seats in Warden's process, and the hostile target test suite) stay as named limits and are listed in the 1.0.0 claim. Examples are the 10-entry cut on `ghost_scan.gaps`, the 200 MB tree ceiling, and the advisory lock.

## Open choices still to settle

None at the time of writing. If a later decision changes a line above, write a new version of this page (`_v2`) instead of editing this one.
