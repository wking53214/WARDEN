"""The README and the documents it was split into, joined in the order the sections used to appear in the README.

The README is a short entry point; the long sections moved, with their text unchanged, to the files below. Tests that
check what "the README" says about the code read this joined text so a moved sentence is still held."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARTS = ("README.md", "docs/WHAT_WORKS.md", "docs/LIMITS.md", "docs/HISTORY.md", "docs/REFERENCE.md", "docs/LIFECYCLE.md")


def full_text() -> str:
    return "\n".join((ROOT / name).read_text(encoding="utf-8") for name in PARTS)
