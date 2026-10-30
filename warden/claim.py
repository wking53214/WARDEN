"""The claim seat: a Drafter that proposes one real change the operator names, then nothing.

The ordinary Drafter invents a change from Ghost's findings. This seat invents nothing: the operator
names a change that already exists, and Warden governs it like any other proposal (grant, suite
before and after, Ghost re-inspection, the Judge). Two ways to name it:

  --claim-commit SHA        the diff of SHA against its first parent, read from the target's own git
                            or from a reference clone given with --claim-repo PATH
  --claim-diff FILE         a unified diff, with --claim-subject and --claim-author saying what it is

The proposal is expressed as the only edits Warden makes: a `write` of a whole UTF-8 text file, or a
`delete`. Whatever cannot be said that way is refused with a reason before anything runs: a binary
file, a symbolic link, a submodule, a rename or copy header, a mode change with no content, a path git
had to quote. Nothing is guessed. The touched files of the target must be byte for byte as the parent has them, or
the claim is refused too; the rest of the tree is not compared, and the claim row's `base_matches_parent` says whether
the whole tree equals the parent's (true, false, or null when it cannot be computed).

The Transformation carries the facts as evidence: commit, parent, tree, the diff's sha256 and size,
and each file with its sha256 before and after. `warden.claimrow` turns those into the record's claim
row. The seat proposes once and then answers NOTHING_TO_PROPOSE, so the loop converges on the one
claimed change.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from . import gitstate
from .models import FileEdit, Transformation, TransformationStatus

#: The spec `warden tagteam` records for this seat (it is built here, not loaded by name).
SEAT_SPEC = "warden.claim:ClaimDrafter"
PROSE = (".md", ".rst", ".txt")
_TIMEOUT = 120
_FILE_MODES = {"100644", "100755"}
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
#: Extended git headers that describe something a write or delete of text cannot express.
_UNSAID = ("rename from", "rename to", "copy from", "copy to", "similarity index", "dissimilarity index",
           "GIT binary patch", "Binary files ")


class ClaimError(ValueError):
    """The named change cannot be governed as it stands. The message says why, in plain words."""


def _sha256(data: Optional[bytes]) -> Optional[str]:
    return None if data is None else hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class ClaimedFile:
    """One file the change touches: its bytes before and after (None: absent on that side)."""

    path: str
    status: str  # "A" added, "M" modified, "D" deleted
    before: Optional[bytes]
    after: Optional[bytes]

    def to_dict(self) -> dict:
        return {"path": self.path, "status": self.status, "before_sha256": _sha256(self.before),
                "after_sha256": _sha256(self.after)}


@dataclass(frozen=True)
class Claim:
    """A real change, named by the operator, as Warden read it."""

    subject: str
    author: str
    diff: bytes
    files: tuple[ClaimedFile, ...]
    commit: Optional[str] = None
    parent: Optional[str] = None
    tree: Optional[str] = None
    date: Optional[str] = None
    #: The repository the commit was read from (None for a diff file). Not part of the recorded facts.
    repo: Optional[Path] = None

    @property
    def diff_sha256(self) -> str:
        return hashlib.sha256(self.diff).hexdigest()

    def to_dict(self) -> dict:
        return {"commit": self.commit, "parent": self.parent, "tree": self.tree, "subject": self.subject,
                "author": self.author, "date": self.date, "diff_sha256": self.diff_sha256,
                "diff_bytes": len(self.diff), "files": [f.to_dict() for f in self.files]}


def _git(repo: Path, *args: str) -> bytes:
    """Run a read-only git command in `repo` and return its output; a failure is a ClaimError."""
    cmd = ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(repo), *args]
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=_TIMEOUT, env=gitstate._env())
    except OSError as exc:
        raise ClaimError(f"git could not be run ({exc}).") from exc
    except subprocess.TimeoutExpired as exc:
        raise ClaimError(f"git did not answer within {_TIMEOUT} seconds.") from exc
    if done.returncode != 0:
        said = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ClaimError(f"git {args[0]} failed in {repo}: {said[-1] if said else 'exit ' + str(done.returncode)}.")
    return done.stdout


def _refuse_links(target: Path, rel: str) -> None:
    """A claimed path whose own entry, or any folder above it inside the target, is a symbolic link is refused: writing
    through it would change something other than the file the change names. Each component is looked at with lstat."""
    here = Path(target)
    for part in Path(rel).parts:
        here = here / part
        try:
            mode = os.lstat(here).st_mode
        except FileNotFoundError:
            return  # nothing below a missing component exists yet, so nothing below it can be a link
        except OSError as exc:
            raise ClaimError(f"{rel}: {part} could not be examined ({exc.strerror or type(exc).__name__}).") from exc
        if stat.S_ISLNK(mode):
            raise ClaimError(f"{rel}: {part} is a symbolic link, so the claimed change would reach through it to "
                             "something else; a claimed path may not be, or lie below, a link.")


def _text(data: bytes, what: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ClaimError(f"{what} is not UTF-8 text, so the change cannot be expressed as a write of text; "
                         "binary files are refused, not guessed.") from exc


def from_commit(target: Path, sha: str, repo: Optional[Path] = None) -> Claim:
    """The diff of `sha` against its first parent, read from `repo` (the target itself when None)."""
    repo = Path(repo if repo is not None else target).resolve()
    full = _git(repo, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}").decode().strip()
    parents = _git(repo, "rev-list", "--parents", "-n", "1", full).decode().split()[1:]
    if not parents:
        raise ClaimError(f"commit {full[:12]} has no parent, so there is no diff to claim.")
    parent = parents[0]
    raw = _git(repo, "diff", "--raw", "--no-renames", "--no-abbrev", "-z", parent, full).decode("utf-8", "replace")
    files = []
    parts = raw.split("\0")
    index = 0
    while index + 1 < len(parts) and parts[index]:
        meta, path = parts[index], parts[index + 1]
        index += 2
        old_mode, new_mode, _old, _new, status = meta.lstrip(":").split(" ")[:5]
        status = status[0]
        for mode, side in ((old_mode, "before"), (new_mode, "after")):
            if mode != "000000" and mode not in _FILE_MODES:
                raise ClaimError(f"{path} is not a plain file {side} the change (mode {mode}: a symbolic link or a "
                                 "submodule), which a write or delete of text cannot express.")
        if status not in "AMD":
            raise ClaimError(f"{path} has a change of kind {status!r}, which a write or delete of text cannot express.")
        if status == "M" and old_mode != new_mode:
            raise ClaimError(f"{path}: the change alters the file's mode from {old_mode} to {new_mode}, which a write "
                             "of text cannot express (a write sets no executable bit).")
        if status == "A" and new_mode != "100644":
            raise ClaimError(f"{path}: the change adds the file with mode {new_mode}, which a write of text cannot "
                             "express (a write sets no executable bit).")
        before = None if status == "A" else _git(repo, "cat-file", "blob", f"{parent}:{path}")
        after = None if status == "D" else _git(repo, "cat-file", "blob", f"{full}:{path}")
        for data, side in ((before, "before"), (after, "after")):
            if data is not None:
                _text(data, f"{path} {side} the change")
        files.append(ClaimedFile(path, status, before, after))
    if not files:
        raise ClaimError(f"commit {full[:12]} changes no file against its parent {parent[:12]}.")
    diff = _git(repo, "diff", "--no-ext-diff", "--no-color", "--no-renames", "--src-prefix=a/", "--dst-prefix=b/",
                parent, full)
    tree = _git(repo, "rev-parse", f"{full}^{{tree}}").decode().strip()
    shown = _git(repo, "show", "-s", "--format=%s%x00%an <%ae>%x00%aI", full).decode("utf-8", "replace")
    subject, author, date = (shown.rstrip("\n").split("\0") + ["", "", ""])[:3]
    return Claim(subject=subject, author=author, diff=diff, files=tuple(files), commit=full, parent=parent,
                 tree=tree, date=date, repo=repo)


def parent_tree_digest(claim: Claim) -> Optional[str]:
    """Warden's fingerprint of the claimed commit's parent tree, materialised from the claimed repository into a
    temporary folder (files with their recorded executable bit; links as links; submodules left out). None when it
    cannot be computed: a diff file has no parent tree, and a repository that cannot be read gives no answer.
    The row compares it with the fingerprint of the target before the run (`base_matches_parent`)."""
    if claim.repo is None or not claim.parent:
        return None
    from .tagteam import _fingerprint  # local import: tagteam imports this module
    try:
        listing = _git(claim.repo, "ls-tree", "-r", "-z", "--full-tree", claim.parent)
        with tempfile.TemporaryDirectory(prefix="warden-parent-") as scratch:
            root = Path(scratch)
            for item in listing.split(b"\0"):
                if not item:
                    continue
                meta, _, raw_name = item.partition(b"\t")
                mode, kind, sha = meta.decode("ascii").split(" ")
                if kind != "blob":
                    continue  # a submodule is a commit, not content
                name = os.fsdecode(raw_name)
                dest = root / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                data = _git(claim.repo, "cat-file", "blob", sha)
                if mode == "120000":
                    os.symlink(os.fsdecode(data), dest)
                else:
                    dest.write_bytes(data)
                    dest.chmod(0o755 if mode == "100755" else 0o644)
            return _fingerprint(root)
    except (ClaimError, OSError, ValueError):
        return None


def _git_header_path(line: str) -> str:
    """The path a `diff --git a/P b/P` line names (the b side), or "" when it cannot be told."""
    rest = line[len("diff --git "):]
    if rest.startswith("a/") and " b/" in rest:
        return rest[2:].rpartition(" b/")[2]
    return ""


def _mode_problem(section: dict) -> str:
    """Why the section's mode headers cannot be said as a write of text, naming the path and the modes; else ''."""
    headers = section["headers"]
    name = section.get("git_path") or section.get("new") or section.get("old") or "a file"
    old = next((h.split(" ", 2)[2] for h in headers if h.startswith("old mode ") and h.count(" ") >= 2), None)
    new = next((h.split(" ", 2)[2] for h in headers if h.startswith("new mode ") and h.count(" ") >= 2), None)
    if old is not None or new is not None:
        return (f"{name}: the diff changes the file's mode from {old or 'unstated'} to {new or 'unstated'}, which a "
                "write of text cannot express (a write sets no executable bit).")
    for header in headers:
        parts = header.split(" ")
        if header.startswith("new file mode ") and len(parts) >= 4 and parts[3] != "100644":
            return (f"{name}: the diff adds the file with mode {parts[3]}, which a write of text cannot express "
                    "(a write sets no executable bit).")
    return ""


def _strip_prefix(name: str) -> str:
    """A `---`/`+++` path without its a/ or b/ prefix or a trailing tab-separated timestamp."""
    name = name.split("\t", 1)[0].strip()
    if name.startswith('"'):
        raise ClaimError(f"the diff names a quoted path ({name}), which is not read; rename the file first.")
    return name[2:] if name[:2] in ("a/", "b/") else name


def _apply_hunks(path: str, old_text: str, hunks: Sequence[tuple[int, list[str]]]) -> str:
    """The file after the hunks, or a ClaimError when a hunk does not match the file as it stands."""
    old_lines = old_text.split("\n")
    # split("\n") leaves the text after the last newline as a final item; a file that ends with a newline
    # therefore ends with "", and one that does not keeps its last partial line.
    ends_with_newline = old_text.endswith("\n") or old_text == ""
    if ends_with_newline and old_lines and old_lines[-1] == "":
        old_lines.pop()
    out: list[str] = []
    pos = 0
    new_ends_with_newline = True
    for start, body in hunks:
        at = max(start - 1, 0)
        if at < pos:
            raise ClaimError(f"{path}: the hunks are out of order or overlap.")
        out.extend(old_lines[pos:at])
        pos = at
        previous = ""
        for line in body:
            tag, rest = line[:1], line[1:]
            if tag == "\\":
                if previous in (" ", "+"):
                    new_ends_with_newline = False
                continue
            if tag in (" ", "-"):
                if pos >= len(old_lines) or old_lines[pos] != rest:
                    raise ClaimError(f"{path}: the hunk at line {start} does not match the file as it stands, "
                                     "so the diff was made against another version. Nothing was guessed.")
                if tag == " ":
                    out.append(rest)
                pos += 1
            elif tag == "+":
                out.append(rest)
            else:
                raise ClaimError(f"{path}: an unreadable line in the hunk at line {start}.")
            previous = tag
    rest_lines = old_lines[pos:]
    out.extend(rest_lines)
    if rest_lines:
        new_ends_with_newline = ends_with_newline
    text = "\n".join(out)
    return text + "\n" if out and new_ends_with_newline else text


def from_diff(target: Path, diff_path: Path, subject: str, author: str) -> Claim:
    """A unified diff (git style or plain), applied to the target's files to learn each file's text after."""
    target = Path(target).resolve()
    if not stat.S_ISREG(os.stat(diff_path).st_mode):
        raise ClaimError(f"{diff_path} is not a regular file (a pipe, a device or a folder), so it is not read.")
    diff = Path(diff_path).read_bytes()
    lines = _text(diff, "the diff file").split("\n")
    sections: list[dict] = []
    current: Optional[dict] = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("diff --git "):
            current = {"old": None, "new": None, "hunks": [], "headers": [], "git_path": _git_header_path(line)}
            sections.append(current)
        elif line.startswith(_UNSAID):
            raise ClaimError(f"the diff says {line.split(' ')[0]} {line.split(' ')[1]} for a file, which a write or "
                             "delete of text cannot express (renames, copies and binary patches are refused).")
        elif line.startswith("--- "):
            if current is None or current["old"] is not None:
                current = {"old": None, "new": None, "hunks": [], "headers": []}
                sections.append(current)
            current["old"] = _strip_prefix(line[4:])
        elif line.startswith("+++ "):
            if current is None:
                raise ClaimError("the diff has a +++ line before its --- line.")
            current["new"] = _strip_prefix(line[4:])
        elif _HUNK.match(line):
            if current is None or current["new"] is None:
                raise ClaimError("the diff has a hunk before its file header.")
            match = _HUNK.match(line)
            assert match is not None
            body: list[str] = []
            index += 1
            while index < len(lines) and lines[index][:1] in (" ", "-", "+", "\\") and lines[index] != "":
                body.append(lines[index])
                index += 1
            current["hunks"].append((int(match.group(1)), body))
            continue
        elif current is not None and (line.startswith(("old mode", "new mode", "deleted file mode", "new file mode",
                                                       "index "))):
            current["headers"].append(line)
        index += 1
    files = []
    for section in sections:
        problem = _mode_problem(section)
        if problem:
            raise ClaimError(problem)
        if section["old"] is None or section["new"] is None:
            raise ClaimError("the diff has a file header without both its --- and +++ lines.")
        if not section["hunks"]:
            raise ClaimError("the diff has a file with no hunks (a mode change alone, or an empty section), "
                             "which a write or delete of text cannot express.")
        old_name, new_name = section["old"], section["new"]
        if old_name.endswith("/dev/null") or old_name == "/dev/null":
            before = None
        else:
            _refuse_links(target, old_name)
            path = target / old_name
            if not path.is_file():
                raise ClaimError(f"{old_name} is not a file in the target, so the diff cannot be applied to it.")
            before = path.read_bytes()
            _text(before, f"{old_name} before the change")
        if new_name.endswith("/dev/null") or new_name == "/dev/null":
            status, name, after = "D", old_name, None
        else:
            if before is None:
                status, name = "A", new_name
                if (target / name).exists():
                    raise ClaimError(f"{name} already exists in the target, so the diff that adds it does not apply.")
            else:
                status, name = "M", new_name
                if old_name != new_name:
                    raise ClaimError(f"the diff moves {old_name} to {new_name}, which is a rename and is refused.")
            old_text = "" if before is None else before.decode("utf-8")
            after = _apply_hunks(name, old_text, section["hunks"]).encode("utf-8")
        if status == "D":
            # Every line of the file must be removed, or the diff does not describe a deletion of this file.
            left = _apply_hunks(name, (before or b"").decode("utf-8"), section["hunks"])
            if left.strip("\n"):
                raise ClaimError(f"{name}: the diff deletes the file but its hunks leave text behind.")
        files.append(ClaimedFile(name, status, before, after))
    if not files:
        raise ClaimError(f"{diff_path} holds no file change Warden can read.")
    return Claim(subject=subject, author=author, diff=diff, files=tuple(files))


def check_base(target: Path, claim: Claim) -> None:
    """The target must hold every touched file exactly as the change's base has it, or nothing is claimed."""
    target = Path(target).resolve()
    for file in claim.files:
        _refuse_links(target, file.path)
        path = target / file.path
        if file.before is None:
            if path.exists():
                raise ClaimError(f"{file.path} already exists in the target, but the change adds it; the target is "
                                 "not at the change's base.")
            continue
        if not path.is_file() or path.read_bytes() != file.before:
            raise ClaimError(f"{file.path} in the target differs from the change's base (sha256 "
                             f"{_sha256(file.before)}), so the target is not at the parent of the claimed change.")


def seat_from_args(args, target: Path) -> "ClaimDrafter":
    """The seat `warden tagteam --claim-*` builds, with the claim read and checked against the target."""
    if args.claim_commit:
        claim = from_commit(target, args.claim_commit, args.claim_repo)
    else:
        claim = from_diff(target, args.claim_diff, args.claim_subject, args.claim_author)
    check_base(target, claim)
    return ClaimDrafter(claim)


class ClaimDrafter:
    """One proposal per run: the claimed change. The second call answers None."""

    requires_contract = "1"

    def __init__(self, claim: Claim) -> None:
        self.claim = claim
        self.scope: Optional[str] = None  # Warden sets the grant's scope here before the first call
        self.proposed = False

    def describe_skipped(self) -> tuple[str, ...]:
        return ()

    def propose(self, target: Path, observed: Sequence, baseline: str) -> Optional[Transformation]:
        if self.proposed:
            return None
        self.proposed = True
        claim = self.claim
        edits = tuple(
            FileEdit(path=f.path, kind="delete", new="") if f.after is None
            else FileEdit(path=f.path, kind="write", new=f.after.decode("utf-8"),
                          old="" if f.before is None else f.before.decode("utf-8"))
            for f in claim.files)
        paths = tuple(f.path for f in claim.files)
        code = [p for p in paths if not p.lower().endswith(PROSE)]
        named = claim.commit[:12] if claim.commit else "the diff given"
        evidence = [f"commit:{claim.commit}", f"parent:{claim.parent}", f"tree:{claim.tree}",
                    f"diff_sha256:{claim.diff_sha256}", f"diff_bytes:{len(claim.diff)}"]
        evidence += [f"file:{f.status}:{_sha256(f.before) or '-'}:{_sha256(f.after) or '-'}:{f.path}"
                     for f in claim.files]
        proposal = Transformation(
            target=str(Path(target).resolve()),
            intent=f"apply the claimed change {named}: {claim.subject}",
            architectural_reason=f"claim: {claim.subject}; author {claim.author}; " + (
                f"commit {claim.commit} (parent {claim.parent})" if claim.commit else "a diff file"),
            affected_files=paths,
            expected_behavior=f"the files listed equal their content after the change; diff sha256 {claim.diff_sha256}",
            preservation_requirements=("files not listed in the diff are unchanged",),
            known_defects=(),
            transformation_scope="code" if code else "documentation",
            baseline_reference=baseline,
            evidence=tuple(evidence),
            edits=edits,
            status=TransformationStatus.PROPOSED,
            claim={**claim.to_dict(), "parent_tree_digest": parent_tree_digest(claim)},
        )
        return proposal
