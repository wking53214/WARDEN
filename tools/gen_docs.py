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
    from warden.cli import EXIT_CODE_HELP, EXIT_CODES

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
        "`INCONCLUSIVE` (which is otherwise exit 6) and `swizzle_sound` false, and the exit is 2.",
        "",
        "`ACCEPT_UNVERIFIED` (3) is the distinct code for a run that could not be fully measured: the changes are",
        "put back and held, and nothing stands until a person approves the digest with `warden keep`.",
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
