"""Generate the parts of docs/ that must agree with the code.

    python tools/gen_docs.py            # print nothing, exit 1 if a file is out of date
    python tools/gen_docs.py --write    # rewrite them

`docs/EXIT_CODES.md` is generated whole from `warden.cli.EXIT_CODES` and `EXIT_CODE_HELP`.
`docs/ARCHITECTURE.md` is hand-written except for the module table between its markers, which is
generated from each module's own docstring. `tests/test_docs.py` fails when either is stale, so the
documents cannot drift from the code without a red test.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BEGIN = "<!-- BEGIN GENERATED MODULES -->"
END = "<!-- END GENERATED MODULES -->"


def exit_codes_md() -> str:
    from warden.cli import CLI_ASSAY_FLOOR, EXIT_CODE_HELP, EXIT_CODES
    from warden.tagteam import LIBRARY_ASSAY_FLOOR

    by_code: dict[int, list[str]] = {}
    for decision, code in EXIT_CODES.items():
        by_code.setdefault(code, []).append(decision)
    lines = [
        "# Exit codes",
        "",
        "Generated from `warden.cli.EXIT_CODES` by `tools/gen_docs.py`; `tests/test_docs.py` fails if it is stale.",
        "Only exit code 0 means the change was accepted, so a CI job can trust the exit code alone.",
        "A decision the code does not know exits 1, never 0.",
        "",
        "| code | decisions |",
        "|---|---|",
    ]
    for code in sorted(by_code):
        lines.append(f"| {code} | " + ", ".join(f"`{d}`" for d in by_code[code]) + " |")
    lines += [
        "",
        "One decision exits with a code that is not its own: when SWIZZLE's own proofs do not hold, the JSON says",
        "`INCONCLUSIVE` (which is otherwise exit 6) and `swizzle_sound` false, and the exit is 2. A SWIZZLE that",
        "does not declare contract 1 (`swizzle --contract` absent, or a different number) is treated the same way,",
        "with the reason in the record.",
        "",
        "`ACCEPT_UNVERIFIED` (3) is the distinct code for a run that could not be fully measured: the changes are",
        "put back and held, and nothing stands until a person approves the digest with `warden keep`.",
        "",
        "## A stack run that refuses before anything runs",
        "",
        "`warden tagteam --stack` exits 2 (`USAGE_ERROR`, \"Nothing was run\", the folder named) when a stack",
        "folder it will use is not what it should be. The folders it uses are the three instrument roots",
        "(`ghost_tools`, `swizzle`, `assay`) and the three seats (`drafter`, `judge`, `burnish`) that `--stack`",
        "fills in; one whose option was given explicitly is not used from the stack. The rule has three parts:",
        "",
        "- With a manifest (`--stack-manifest` or `--cns`), every used folder must be named by it. A folder the",
        "  manifest leaves out has no pinned commit to be checked against.",
        "- With a manifest, every folder it names must be at exactly the pinned commit.",
        "- With or without a manifest, every used folder must have no uncommitted changes (see the README for what",
        "  counts). A clone of the target at the same commit as a stack member is still checked; only the join for",
        "  Ghost is skipped. The governed target itself is excluded.",
        "",
        "\"No uncommitted changes\" is decided the same way for every asker. Warden runs git with no user or system",
        "configuration, lists every untracked file, does not ignore submodules and always compares the executable",
        "bit, so no setting of your own can hide a change. A tracked file whose index entry says",
        "`assume-unchanged` or `skip-worktree` counts as uncommitted work, because git would not show its next edit.",
        "Only the repository\'s own `.gitignore` can still hide a file. The same check decides the target\'s own dirty",
        "policy (`REFUSED`, exit 5).",
        "",
        "## The ASSAY floor has two defaults",
        "",
        "A graded ASSAY score below the floor is a `REJECT` (exit 1) that Warden decides itself, whatever the Judge",
        "said. The command line and the library do not start from the same floor:",
        "",
        "| caller | default | what it means |",
        "|---|---|---|",
        f"| `warden tagteam` | `--assay-floor {CLI_ASSAY_FLOOR}` (`warden.cli.CLI_ASSAY_FLOOR`) | Ghost must catch at "
        f"least {CLI_ASSAY_FLOOR} known failure modes, or the run is a `REJECT`. |",
        f"| `TagTeam(...)` in the library | `assay_floor={LIBRARY_ASSAY_FLOOR}` "
        "(`warden.tagteam.LIBRARY_ASSAY_FLOOR`) | "
        "The floor is not enforced: a graded score is recorded, and the notes say the floor was not enforced. |",
        "",
        f"A library caller who wants the command line's behaviour passes `assay_floor={CLI_ASSAY_FLOOR}`. "
        "`0` is the one",
        "explicit way to skip the floor, in either place; below 0 is a usage error on the command line. A floor is",
        "only applied to a score that was measured: when ASSAY could not be graded, `assay` is in `unmeasured` and",
        "the run is never a plain `ACCEPT`, whatever the floor.",
        "",
        "## What each code means",
        "",
        "This is the text of `warden tagteam --help`.",
        "",
        "```text",
        EXIT_CODE_HELP,
        "```",
        "",
    ]
    return "\n".join(lines)


def _summary(path: Path) -> str:
    doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
    return (doc.splitlines() or [""])[0].strip()


def modules_table() -> str:
    rows = ["| module | what it is |", "|---|---|"]
    files = sorted((ROOT / "warden").glob("*.py")) + sorted((ROOT / "warden" / "horsemen").glob("*.py"))
    for path in files:
        rel = path.relative_to(ROOT).with_suffix("")
        name = ".".join(rel.parts)
        if name.endswith(".__init__"):
            name = name[: -len(".__init__")]
        rows.append(f"| `{name}` | {_summary(path).replace('|', '/')} |")
    return "\n".join(rows)


def architecture_md(current: str) -> str:
    """`current` with the generated module table replaced (or appended between fresh markers)."""
    block = f"{BEGIN}\n{modules_table()}\n{END}"
    if BEGIN in current and END in current:
        head, rest = current.split(BEGIN, 1)
        _, tail = rest.split(END, 1)
        return head + block + tail
    return current.rstrip("\n") + "\n\n" + block + "\n"


def main(argv: list[str]) -> int:
    write = "--write" in argv
    docs = ROOT / "docs"
    stale = []
    targets = {
        docs / "EXIT_CODES.md": exit_codes_md(),
        docs / "ARCHITECTURE.md": architecture_md((docs / "ARCHITECTURE.md").read_text(encoding="utf-8")
                                                  if (docs / "ARCHITECTURE.md").exists() else ""),
    }
    for path, text in targets.items():
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            stale.append(path.name)
            if write:
                path.write_text(text, encoding="utf-8")
    if stale and not write:
        print("out of date: " + ", ".join(stale) + " (run: python tools/gen_docs.py --write)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
