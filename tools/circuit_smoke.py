"""Smoke test for the horsemen circuit: Warden against live ASSAY, ghost_tools and SWIZZLE checkouts.

    python tools/circuit_smoke.py --ghost-tools DIR --swizzle DIR --assay DIR \\
        [--expect ghost_tools=SHA --expect swizzle=SHA --expect assay=SHA]

It builds a small scratch git repository, then runs the real `warden tagteam` command line twice:

  1. observe only (no Drafter): the instruments are consulted live, nothing can be proposed, so the run must
     end `INCONCLUSIVE` (exit 6) with SWIZZLE's proofs held, ASSAY's key graded and Ghost scanning, each loaded
     from its own checkout; a Ghost or SWIZZLE root that is not a checkout must fail closed;
  2. a governed change (a one-line README edit proposed by a stub Drafter, judged by a stub Judge, both
     defined here), with a receipt: Warden must not return a plain `ACCEPT` unless every check ran, the
     receipt must name the ASSAY specimens, and a floor above what Ghost catches must stop the stub Judge's
     ACCEPT.

It exits 0 when every expectation holds and 1 with the first failed one. Integration with the other
horsemen is exercised here, in CI, and not only on a developer's machine. Nothing is written outside a
temporary folder.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SEATS = '''
from pathlib import Path
from warden.models import FileEdit, Transformation, TransformationStatus
from warden.roles import Verdict


class Drafter:
    requires_contract = "1"
    scope = "documentation"

    def __init__(self):
        self.done = False

    def propose(self, target, observed, baseline):
        if self.done:
            return None
        self.done = True
        note = Path(target) / "NOTE.md"
        old = note.read_text(encoding="utf-8")
        return Transformation(
            target=str(Path(target).resolve()), intent="smoke", architectural_reason="smoke",
            affected_files=("NOTE.md",), expected_behavior="none", preservation_requirements=(),
            known_defects=(), transformation_scope="documentation", baseline_reference=baseline, evidence=(),
            edits=(FileEdit(path="NOTE.md", kind="write", new="smoke edit\\n", old=old),),
            status=TransformationStatus.PROPOSED)


class Judge:
    requires_contract = "1"

    def decide(self, evidence):
        return Verdict("ACCEPT", ("smoke stub",), "smoke-judge")
'''


class Failed(Exception):
    pass


def check(condition: bool, what: str) -> None:
    if not condition:
        raise Failed(what)
    print(f"ok: {what}")


def git(cwd: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "smoke", "GIT_AUTHOR_EMAIL": "s@s", "GIT_COMMITTER_NAME": "smoke",
           "GIT_COMMITTER_EMAIL": "s@s", "PATH": os.environ.get("PATH", ""), "HOME": str(cwd),
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    done = subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True, env=env)
    return done.stdout.strip()


def make_target(base: Path) -> Path:
    target = base / "target"
    (target / "pkg").mkdir(parents=True)
    (target / "tests").mkdir()
    (target / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (target / "tests" / "test_pkg.py").write_text(
        "from pkg import VALUE\n\n\ndef test_value():\n    assert VALUE == 1\n", encoding="utf-8")
    (target / "NOTE.md").write_text("old\n", encoding="utf-8")
    (target / "pyproject.toml").write_text('[project]\nname = "smoke"\nversion = "0.0.1"\n', encoding="utf-8")
    (target / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    git(target, "init", "-q", "-b", "main")
    git(target, "add", "-A")
    git(target, "commit", "-q", "-m", "smoke target")
    return target


def run_warden(args: list[str], base: Path, seats: Path) -> tuple[int, dict, str]:
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT), str(seats)]), HOME=str(base / "home"),
               XDG_STATE_HOME=str(base / "home" / "state"))
    env.pop("WARDEN_LOG_LEVEL", None)
    done = subprocess.run([sys.executable, "-m", "warden.cli", *args], capture_output=True, text=True, env=env,
                          cwd=str(base), timeout=1800)
    try:
        payload = json.loads(done.stdout)
    except ValueError as err:
        raise Failed(f"stdout was not one JSON document: {done.stdout[:200]!r} "
                     f"/ stderr {done.stderr[-300:]!r}") from err
    return done.returncode, payload, done.stderr


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--ghost-tools", type=Path, required=True)
    parser.add_argument("--swizzle", type=Path, required=True)
    parser.add_argument("--assay", type=Path, required=True)
    parser.add_argument("--expect", action="append", default=[], metavar="NAME=SHA",
                        help="the full commit each checkout must be at (ghost_tools, swizzle, assay)")
    args = parser.parse_args(argv)
    roots = {"ghost_tools": args.ghost_tools, "swizzle": args.swizzle, "assay": args.assay}
    for item in args.expect:
        name, _, sha = item.partition("=")
        if name not in roots or len(sha) != 40:
            parser.error(f"--expect wants NAME=<40 hex>, got {item!r}")
        head = git(roots[name], "rev-parse", "HEAD")
        check(head == sha, f"{name} checkout is at the pinned commit {sha[:10]}")

    with tempfile.TemporaryDirectory(prefix="warden-smoke-") as tmp:
        base = Path(tmp)
        (base / "home").mkdir()
        seats = base / "seats"
        seats.mkdir()
        (seats / "smoke_seats.py").write_text(SEATS, encoding="utf-8")
        target = make_target(base)
        instruments = ["--ghost-root", str(args.ghost_tools), "--swizzle-root", str(args.swizzle),
                       "--assay-root", str(args.assay)]

        code, out, _ = run_warden(["tagteam", str(target), *instruments], base, seats)
        check(code == 6 and out["decision"] == "INCONCLUSIVE", "observe-only run ends INCONCLUSIVE (exit 6)")
        check(out["swizzle_sound"] is True, "SWIZZLE's own proofs hold against the pinned checkout")
        check("swizzle" not in out["unmeasured"] and "assay" not in out["unmeasured"],
              "SWIZZLE and ASSAY were measured")
        check("ghost" not in out["unmeasured"], "Ghost scanned the target")
        versions = out["versions"]
        for name in ("ghost_tools", "swizzle", "assay"):
            check(bool(versions[name] and versions[name]["commit"]), f"versions names the {name} commit")
            check(versions[name]["module_in_root"] is True, f"{name} was loaded from its own checkout")

        # A root that is not the checkout fails closed, whatever is installed in this Python.
        code, out, _ = run_warden(["tagteam", str(target), "--ghost-root", str(base / "no-ghost")], base, seats)
        check(code == 6 and out["decision"] == "INCONCLUSIVE" and "ghost" in out["unmeasured"],
              "a --ghost-root that is not a checkout is refused (INCONCLUSIVE, Ghost unmeasured)")
        code, out, _ = run_warden(["tagteam", str(target), "--swizzle-root", str(base / "no-swizzle")], base, seats)
        check(code == 2 and out["swizzle_sound"] is False,
              "a --swizzle-root that is not a checkout proves nothing (swizzle_sound false, exit 2)")

        receipt = base / "receipt.json"
        governed = ["tagteam", str(target), *instruments, "--drafter", "smoke_seats:Drafter",
                    "--judge", "smoke_seats:Judge", "--authorize", "smoke-operator", "--reason", "circuit smoke",
                    "--receipt", str(receipt), "--assay-floor", "0"]
        code, out, err = run_warden(governed, base, seats)
        check(out["decision"] in {"ACCEPT", "ACCEPT_UNVERIFIED"}, f"governed run decided {out['decision']}")
        check((code == 0) == (out["decision"] == "ACCEPT"), "only ACCEPT exits 0")
        check((target / "NOTE.md").read_text(encoding="utf-8") in {"old\n", "smoke edit\n"}, "tree is old or edited")
        if out["decision"] == "ACCEPT_UNVERIFIED":
            check(bool(out["unmeasured"]), "an unverified run names what was not measured")
            check((target / "NOTE.md").read_text(encoding="utf-8") == "old\n", "an unverified run is put back")
            git(target, "status", "--porcelain")
        else:
            check(out["unmeasured"] == [], "a plain ACCEPT has nothing unmeasured")
            git(target, "checkout", "--", ".")
        data = json.loads(receipt.read_text(encoding="utf-8"))
        check(len(data["specimens_used"]) > 0, "the receipt names the ASSAY specimens the adapter read")
        check(data["actor"] == "smoke-operator" and data["cns_readiness"] == "UNKNOWN",
              "the receipt records the human actor and never claims CNS readiness")
        check("swizzle.proofs" in data["adversarial_cases"], "the receipt records SWIZZLE's proofs")

        # A floor no scanner meets must stop the stub Judge's ACCEPT, whatever the Judge says.
        impossible = governed[:-2] + ["--assay-floor", "999"]
        impossible = [a for a in impossible if a not in ("--receipt", str(receipt))]
        code, out, _ = run_warden(impossible, base, seats)
        check(out["decision"] == "REJECT" and code == 1, "a floor Ghost cannot meet rejects despite a Judge ACCEPT")
        check((target / "NOTE.md").read_text(encoding="utf-8") == "old\n", "the rejected run left the tree as found")
    print("circuit smoke test passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Failed as err:
        print(f"circuit smoke test FAILED: {err}", file=sys.stderr)
        raise SystemExit(1) from None
