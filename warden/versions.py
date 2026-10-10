"""Which versions took part in a run, for the `versions` field of `warden tagteam`'s JSON.

Commits and versions are read from files: a commit from `.git`, a version string from
`pyproject.toml` or from the installed package's metadata. Whether a checkout has uncommitted work
(`dirty`) is the one thing that asks git, read-only. A value that cannot be found is `None`, never a
guess, and a commit is only ever read from the thing's OWN checkout or install: never from a
repository that merely happens to contain it (the folder being governed, or a virtualenv inside it).
This only reports; nothing here decides anything.
"""

from __future__ import annotations

import importlib
import importlib.metadata as metadata
import json
import re
import tomllib
from pathlib import Path
from typing import Optional

from . import gitstate

_SHA = re.compile(r"^[0-9a-f]{40}$")


def git_commit(path: Path) -> Optional[str]:
    """The commit a checkout is on (read from .git, walking up from `path`), or None."""
    try:
        here = Path(path).resolve()
        for folder in (here, *here.parents):
            dot = folder / ".git"
            if dot.is_file():  # a worktree or submodule: ".git" is a file naming the real folder
                text = dot.read_text(encoding="utf-8").strip()
                if not text.startswith("gitdir:"):
                    return None
                gitdir = (folder / text[len("gitdir:"):].strip()).resolve()
            elif dot.is_dir():
                gitdir = dot
            else:
                continue
            head = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
            if _SHA.match(head):
                return head
            if not head.startswith("ref:"):
                return None
            ref = head[4:].strip()
            common = gitdir
            if (gitdir / "commondir").is_file():
                common = (gitdir / (gitdir / "commondir").read_text(encoding="utf-8").strip()).resolve()
            for base in (gitdir, common):
                loose = base / ref
                if loose.is_file():
                    sha = loose.read_text(encoding="utf-8").strip()
                    return sha if _SHA.match(sha) else None
            packed = common / "packed-refs"
            if packed.is_file():
                for line in packed.read_text(encoding="utf-8").splitlines():
                    parts = line.split()
                    if len(parts) == 2 and parts[1] == ref and _SHA.match(parts[0]):
                        return parts[0]
            return None
    except (OSError, ValueError):
        return None
    return None


def project_version(root: Path) -> Optional[str]:
    """The `version` in a checkout's pyproject.toml, or None."""
    try:
        data = tomllib.loads((Path(root) / "pyproject.toml").read_text(encoding="utf-8"))
        version = data.get("project", {}).get("version")
        return version if isinstance(version, str) else None
    except (OSError, ValueError):
        return None


def own_commit(root: Path) -> Optional[str]:
    """The commit of a checkout whose `.git` is directly in `root`. Never a parent folder's repository."""
    root = Path(root)
    if not (root / ".git").exists():
        return None
    return git_commit(root)


def _dirty(root: Path) -> Optional[bool]:
    """True/False for a checkout with its own `.git`; None when it has none or git cannot say."""
    if not (Path(root) / ".git").exists():
        return None
    return gitstate.is_dirty(root)


def instrument(root: Optional[Path]) -> Optional[dict]:
    """An instrument checkout (Ghost Tools, SWIZZLE, ASSAY): where it is, its commit, version and whether it
    has uncommitted work. The commit is only the checkout's own; a folder that is not a checkout of its own
    reports None, even when it sits inside someone else's repository."""
    if root is None:
        return None
    root = Path(root).expanduser().resolve()
    return {"path": str(root), "commit": own_commit(root), "version": project_version(root), "dirty": _dirty(root)}


def _inside(path: Path, folder: Optional[Path]) -> bool:
    if folder is None:
        return False
    try:
        return Path(path).resolve().is_relative_to(Path(folder).resolve())
    except (OSError, ValueError):
        return False


def _own_root(module_name: str, module_file: str) -> Optional[Path]:
    """The folder of the project a module belongs to, when it is a checkout of its own (`.git` and a project
    file directly inside), judged from how deep the module sits in its packages. None for an installed copy."""
    path = Path(module_file).resolve()
    if {"site-packages", "dist-packages"}.intersection(path.parts):
        return None
    depth = len(module_name.split("."))
    for index in (depth - 1, depth):
        try:
            candidate = path.parents[index]
        except IndexError:
            continue
        if (candidate / ".git").exists() and any((candidate / f).is_file() for f in ("pyproject.toml", "setup.py", "setup.cfg")):
            return candidate
    return None


def _installed(module_name: str, module_file: Optional[str], avoid: Optional[Path] = None) -> dict:
    """Version, commit and dirty flag of the code a module really came from.

    The commit comes from the install record (`direct_url.json`) or from the module's OWN checkout. A
    module that sits inside `avoid` (the folder being governed) gets None for everything but what its
    install record says.
    """
    out: dict = {"version": None, "commit": None, "dirty": None}
    top = module_name.partition(".")[0]
    try:
        dists = metadata.packages_distributions().get(top) or []
        if dists:
            dist = metadata.distribution(dists[0])
            out["version"] = dist.version
            direct = dist.read_text("direct_url.json")
            if direct:
                info = json.loads(direct).get("vcs_info") or {}
                if _SHA.match(str(info.get("commit_id", ""))):
                    out["commit"] = info["commit_id"]
    except Exception:  # noqa: BLE001 - a report that cannot be read is None, never a crash
        pass
    if module_file and not _inside(Path(module_file), avoid):
        root = _own_root(module_name, module_file)
        if root is not None:
            own = git_commit(root)
            if out["commit"] is None:
                out["commit"] = own
            out["dirty"] = _dirty(root)
            if out["version"] is None:
                out["version"] = project_version(root)
    return out


def seat(spec: Optional[str], filled, target: Optional[Path] = None) -> Optional[dict]:
    """A seat named MODULE:FACTORY and the object built from it. `target` is the folder being governed:
    nothing about the target's own repository is ever reported as the seat's."""
    if not spec or filled is None:
        return None
    module_name = spec.partition(":")[0]
    try:
        module_file = getattr(importlib.import_module(module_name), "__file__", None)
    except Exception:  # noqa: BLE001
        module_file = None
    declared = getattr(filled, "requires_contract", None)
    return {"spec": spec, "requires_contract": declared if isinstance(declared, str) else None,
            **_installed(module_name, module_file, target)}


def report(*, warden_module, contract: str, version: str, ghost_root, swizzle_root, assay_root,
           seats: dict, target: Optional[Path] = None) -> dict:
    """The `versions` object: Warden, each instrument root given, and each seat that was loaded."""
    me = _installed("warden", getattr(warden_module, "__file__", None), target)
    return {
        "warden": {"version": version, "contract": contract, "commit": me["commit"], "dirty": me["dirty"]},
        "ghost_tools": instrument(ghost_root),
        "swizzle": instrument(swizzle_root),
        "assay": instrument(assay_root),
        "seats": seats,
    }
