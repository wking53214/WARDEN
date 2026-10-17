"""Which versions took part in a run, for the `versions` field of `warden tagteam`'s JSON.

Commits and versions are read from files: a commit from `.git`, a version string from
`pyproject.toml` or from the installed package's metadata. Whether a checkout has uncommitted work
(`dirty`) is the one thing that asks git, read-only. A value that cannot be found is `None`, never a
guess, and a commit is only ever read from the thing's OWN checkout or install: never from a
repository that merely happens to contain it (the folder being governed, or a virtualenv inside it).
This only reports; nothing here decides anything.
"""

from __future__ import annotations

import ast
import importlib
import importlib.metadata as metadata
import json
import re
import tomllib
from pathlib import Path
from typing import Any, Optional

from . import gitstate
from .isolation import locate_module

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


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
#: A version module larger than this is not read (a version file is a few lines).
_VERSION_FILE_LIMIT = 256 * 1024


def _string_assignment(source: str, name: str) -> Optional[str]:
    """The string `name` is set to at the top level of `source`, read with `ast` and never run.

    Only a plain `name = "literal"` counts. None when it is assigned more than once to different values,
    assigned anything but a string literal (a call, an f-string, a name, a conditional), or not assigned."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    found: list[Any] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            value = node.value
            single = len(node.targets) == 1 and isinstance(value, ast.Constant) and isinstance(value.value, str)
            found.append(value.value if single and isinstance(value, ast.Constant) else None)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and isinstance(node.target, ast.Name) \
                and node.target.id == name:
            found.append(None)
    if not found or any(not isinstance(v, str) or not v for v in found) or len(set(found)) != 1:
        return None
    return found[0]


def _dynamic_version(root: Path, data: dict) -> Optional[str]:
    """A version a checkout declares as `dynamic`, from `[tool.setuptools.dynamic] version = {attr = "..."}`.

    The module is located from the dotted name and READ, never imported: target code is not executed to
    learn a version. Only a plain string-literal assignment is accepted. Folders tried: the checkout, then
    `src`, then the `package-dir` mapping for the root package if there is one."""
    if "version" not in (data.get("project", {}).get("dynamic") or []):
        return None
    setuptools = data.get("tool", {}).get("setuptools", {})
    spec = (setuptools.get("dynamic", {}) or {}).get("version")
    attr = spec.get("attr") if isinstance(spec, dict) else None
    if not isinstance(attr, str) or "." not in attr:
        return None
    parts = attr.split(".")
    module_parts, name = parts[:-1], parts[-1]
    if not all(_IDENTIFIER.match(p) for p in (*module_parts, name)):
        return None
    mapping = setuptools.get("package-dir")
    bases = [Path(root)]
    if isinstance(mapping, dict) and isinstance(mapping.get(""), str):
        bases.insert(0, Path(root) / mapping[""])
    bases.append(Path(root) / "src")
    for base in bases:
        for rel in (Path(*module_parts).with_suffix(".py"), Path(*module_parts) / "__init__.py"):
            candidate = base / rel
            try:
                if not candidate.resolve().is_relative_to(Path(root).resolve()) or not candidate.is_file():
                    continue
                if candidate.stat().st_size > _VERSION_FILE_LIMIT:
                    return None
                return _string_assignment(candidate.read_text(encoding="utf-8"), name)
            except (OSError, ValueError):
                return None
    return None


def project_version(root: Path) -> Optional[str]:
    """The version of a checkout, from its pyproject.toml, or None.

    A static `[project] version` is used as written. A `dynamic` version declared as
    `[tool.setuptools.dynamic] version = {attr = "pkg.module.__version__"}` is read from that module's source
    with `ast` (a plain string literal only); nothing is imported or run."""
    try:
        data = tomllib.loads((Path(root) / "pyproject.toml").read_text(encoding="utf-8"))
        version = data.get("project", {}).get("version")
        if isinstance(version, str):
            return version
        return _dynamic_version(Path(root), data)
    except (OSError, ValueError, AttributeError):
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


def instrument(root: Optional[Path], package: Optional[str] = None) -> Optional[dict]:
    """An instrument checkout (Ghost Tools, SWIZZLE, ASSAY): where it is, its commit, version and whether it
    has uncommitted work. The commit is only the checkout's own; a folder that is not a checkout of its own
    reports None, even when it sits inside someone else's repository.

    With `package` (the instrument's importable package) it also says where that package resolves when the
    instrument is started with this root: `module` is the file, or None when it resolves nowhere, and
    `module_in_root` is whether that file lies under the root. A run is refused when it does not (see
    `isolation.verify_root`); the record keeps the evidence."""
    if root is None:
        return None
    root = Path(root).expanduser().resolve()
    out = {"path": str(root), "commit": own_commit(root), "version": project_version(root), "dirty": _dirty(root)}
    if package is not None:
        found = locate_module(package, root)
        out["module"] = None if found is None else str(found)
        out["module_in_root"] = None if found is None else found.is_relative_to(root)
    return out


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
        if (candidate / ".git").exists() and any(
                (candidate / f).is_file() for f in ("pyproject.toml", "setup.py", "setup.cfg")):
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
           seats: dict, target: Optional[Path] = None, joins: tuple = ()) -> dict:
    """The `versions` object: Warden, each instrument root given, each seat that was loaded, and each
    checkout joined for Ghost (its path, commit, version and whether it had uncommitted work)."""
    me = _installed("warden", getattr(warden_module, "__file__", None), target)
    return {
        "warden": {"version": version, "contract": contract, "commit": me["commit"], "dirty": me["dirty"]},
        "ghost_tools": instrument(ghost_root, "ghost_buster"),
        "swizzle": instrument(swizzle_root, "swizzle"),
        "assay": instrument(assay_root, "assay_production"),
        "seats": seats,
        "joins": [instrument(j) for j in joins],
    }
