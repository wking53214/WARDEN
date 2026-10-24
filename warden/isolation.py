"""Run Warden's instruments (SWIZZLE, Ghost Tools, ASSAY grading) away from the target.

`python -m swizzle.cli` puts the current directory first on the import path.
If Warden is started from inside the target, a `swizzle/cli.py` planted in the
target would be run and believed. So every instrument runs with:

  - a fresh empty directory as its working directory,
  - `-P`, so Python does not add the working directory to the import path,
  - instrument roots turned into absolute paths first,
  - no inherited PYTHONPATH: an instrument sees its named roots first, so a sibling checkout on the
    caller's path cannot stand in for a missing root,
  - a root that is checked before the instrument runs. Dropping PYTHONPATH is not enough on its own:
    the interpreter's site-packages stays importable, so a missing or wrong root would be satisfied
    silently by an installed copy of the same package. `verify_root` therefore requires each named root
    to be an existing directory that holds the instrument's package, and asks the interpreter, started
    the way the instrument is, where that package really resolves. A package that resolves anywhere
    but under the named root is refused (`InstrumentRootError`) and nothing is run.
  - a root that is not an installed copy. A root that is, or lies inside, a site-packages or dist-packages
    folder, or the interpreter's own stdlib or site folders (symbolic links followed first), is refused: the
    installed copy would stand in for a checkout. And a root must be a checkout Warden can name: a git commit
    of its own and a version in its pyproject.toml. A plain copy of the package in an ordinary folder has
    neither and is refused too, unless the caller opts in (`allow_uncommitted`), in which case the run is
    recorded as such and is never a plain ACCEPT.

What remains: the check names where the package is found, not what it does once it runs, and an
instrument that SWIZZLE itself starts (Ghost and ASSAY, graded by `swizzle assay`) is checked here for its
root and package but loaded by SWIZZLE's own path rules. A checkout that is also installed in editable mode
(its folder on the path through a `.pth` file) is allowed: it is a checkout, with a commit and a version.

The target's own test suite is the one thing that still runs inside the
target. That cannot be avoided: running those tests is the point.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Iterator, Mapping, Optional, Sequence

logger = logging.getLogger("warden.isolation")

#: The importable package each instrument is run from, and the name used for it in a reason.
INSTRUMENT_PACKAGES = {"ghost_buster": "Ghost Tools", "swizzle": "SWIZZLE", "assay_production": "ASSAY"}

#: Environment variables that carry credentials. The target's suite is the target's code, run by
#: Warden on a person's machine; it is handed none of these, so a hostile or careless suite cannot
#: read the caller's tokens from its environment. Cheap, partial hardening, not a sandbox.
_SECRET_NAME = re.compile(
    r"(^|_)(TOKEN|SECRET|PASSWORD|PASSWD|PASSPHRASE|CREDENTIALS?|API_?KEY|PRIVATE_KEY|ACCESS_KEY|AUTH)(_|$)"
    r"|^(AWS|ANTHROPIC|OPENAI|GOOGLE_APPLICATION|AZURE|TWINE|NPM)_"
    r"|^SSH_AUTH_SOCK$|^SSH_AGENT_PID$|^GIT_ASKPASS$",
    re.IGNORECASE,
)
#: Set to 1 to hand the suite the full environment (a suite that really needs a credential).
SUITE_ENV_PASSTHROUGH = "WARDEN_SUITE_ENV_PASSTHROUGH"


def suite_env(environ: Optional[Mapping[str, str]] = None) -> dict:
    """The environment for the target's own test suite: the caller's, without credential-bearing names.

    `PYTHONPATH` is kept on purpose: a suite that imports sibling checkouts needs it, and the
    suite is the one thing that has to see the caller's setup. What is removed is listed at DEBUG
    (names only, never values). `WARDEN_SUITE_ENV_PASSTHROUGH=1` keeps everything.
    """
    env = dict(os.environ if environ is None else environ)
    if env.get(SUITE_ENV_PASSTHROUGH) == "1":
        logger.warning("%s=1: the target's suite is given the full environment, credentials included",
                       SUITE_ENV_PASSTHROUGH)
        return env
    dropped = sorted(name for name in env if _SECRET_NAME.search(name) and name != SUITE_ENV_PASSTHROUGH)
    for name in dropped:
        del env[name]
    if dropped:
        logger.debug("suite environment: withheld %d variable(s): %s", len(dropped), ", ".join(dropped))
    return env


def absolute(path: Optional[Path]) -> Optional[Path]:
    return None if path is None else Path(path).expanduser().resolve()


#: The bytecode cache directory of the running `private_bytecode_cache()`, or None outside one.
_ACTIVE_CACHE: Optional[str] = None
#: A private directory made on first use when no `private_bytecode_cache()` is running (library callers).
_FALLBACK_CACHE: Optional[str] = None


@contextlib.contextmanager
def private_bytecode_cache() -> Iterator[str]:
    """Give this Python process a fresh, private, empty bytecode cache for as long as the block runs.

    A .pyc in a source tree's `__pycache__` is read in place of the source. An UNCHECKED_HASH one is never compared with
    the source at all, and `git status` does not show it (the folder is ignored), so a seat or instrument checkout
    can be clean, at its pinned commit, and still run planted bytecode. With `sys.pycache_prefix` set Python reads and
    writes bytecode only under the prefix, and never looks in a tree's `__pycache__`.

    What it changes: every import made while the block runs, by Warden or a seat, compiles from source the first time
    (the standard library's frozen modules aside); a module is cached for the rest of the run under the private
    directory, which is removed afterwards. It does not touch anything already imported, nor a .pyc with no source file
    beside it (a sourceless module), and the cache of other Python processes (third-party libraries in a virtual
    environment, for example) is untouched; `instrument_env` hands the same directory to every instrument Warden starts.
    """
    global _ACTIVE_CACHE
    path = tempfile.mkdtemp(prefix="warden-pyc-")  # mode 0700, a name nobody can plant a file in beforehand
    previous_prefix, previous_active = sys.pycache_prefix, _ACTIVE_CACHE
    sys.pycache_prefix, _ACTIVE_CACHE = path, path
    try:
        yield path
    finally:
        sys.pycache_prefix, _ACTIVE_CACHE = previous_prefix, previous_active
        shutil.rmtree(path, ignore_errors=True)


def bytecode_cache_dir() -> str:
    """The private bytecode directory instruments are started with: the running `private_bytecode_cache()`'s, else one
    made on first use for this process (removed at exit)."""
    global _FALLBACK_CACHE
    if _ACTIVE_CACHE is not None:
        return _ACTIVE_CACHE
    if _FALLBACK_CACHE is None or not os.path.isdir(_FALLBACK_CACHE):
        _FALLBACK_CACHE = tempfile.mkdtemp(prefix="warden-pyc-")
        atexit.register(shutil.rmtree, _FALLBACK_CACHE, True)
    return _FALLBACK_CACHE


def instrument_env(*roots: Optional[Path]) -> dict:
    """The environment for an instrument: its named roots only.

    An inherited PYTHONPATH is dropped on purpose. If a root is missing, the
    instrument must fail, not quietly import a sibling checkout from the
    caller's path and report its result as if it came from the named root.
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(str(absolute(r)) for r in roots if r is not None)
    # Bytecode comes from a private empty directory, never from a `__pycache__` in an instrument's checkout.
    env["PYTHONPYCACHEPREFIX"] = bytecode_cache_dir()
    return env


class InstrumentRootError(RuntimeError):
    """A named instrument root cannot be used: it is not a directory, it lacks the instrument's package, or
    the package the interpreter would load is not the one under the root. Nothing was run. `package` names
    the instrument package whose root was refused."""

    def __init__(self, message: str, package: str = "") -> None:
        super().__init__(message)
        self.package = package


#: Prints where a package resolves, without importing it. An empty line means it does not resolve.
_PROBE = (
    "import importlib.util, sys\n"
    "try:\n"
    "    spec = importlib.util.find_spec(sys.argv[1])\n"
    "except Exception:\n"
    "    spec = None\n"
    "origin = getattr(spec, 'origin', None)\n"
    "print(origin if isinstance(origin, str) and origin.endswith('.py') else '')\n"
)


#: Prints the interpreter's own stdlib and site folders as a JSON list, with PYTHONPATH already removed.
_LOCATIONS = (
    "import json, site, sysconfig\n"
    "found = [sysconfig.get_paths().get(k) for k in ('stdlib', 'platstdlib', 'purelib', 'platlib')]\n"
    "try:\n"
    "    found += list(site.getsitepackages())\n"
    "except Exception:\n"
    "    pass\n"
    "try:\n"
    "    found.append(site.getusersitepackages())\n"
    "except Exception:\n"
    "    pass\n"
    "print(json.dumps([p for p in found if isinstance(p, str) and p]))\n"
)
_INSTALLED_NAMES = frozenset({"site-packages", "dist-packages"})


_LOCATIONS_CACHE: dict[str, list[Path]] = {}


def interpreter_locations(python: Optional[str] = None, timeout: float = 60) -> list[Path]:
    """The stdlib and site folders of the interpreter an instrument is started with (and of this one), resolved.
    Asked of the interpreter itself (`sysconfig`, `site.getsitepackages()`), with PYTHONPATH removed so the
    instrument's own root is not mistaken for one of them."""
    import site
    import sysconfig
    paths = sysconfig.get_paths()
    found: list[str] = [p for p in (paths.get(k) for k in ("stdlib", "platstdlib", "purelib", "platlib")) if p]
    try:
        found += list(site.getsitepackages()) + [site.getusersitepackages()]
    except Exception:  # noqa: BLE001 - a site module that cannot answer adds nothing
        pass
    exe = python or sys.executable
    if exe in _LOCATIONS_CACHE:
        return list(_LOCATIONS_CACHE[exe])
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONPYCACHEPREFIX"] = bytecode_cache_dir()
    with tempfile.TemporaryDirectory(prefix="warden-instrument-") as empty:
        try:
            proc = subprocess.run([exe, "-P", "-c", _LOCATIONS], capture_output=True, text=True, env=env, cwd=empty,
                                  timeout=timeout)
            if proc.returncode == 0:
                answer = json.loads(proc.stdout.strip().splitlines()[-1])
                found += [p for p in answer if isinstance(p, str)]
        except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
            pass
    out: list[Path] = []
    for item in found:
        try:
            out.append(Path(item).resolve())
        except OSError:
            continue
    _LOCATIONS_CACHE[exe] = out
    return list(out)


def installed_location(root: Path, python: Optional[str] = None) -> str:
    """Why `root` is an installed location, or an empty string when it is not. `root` is resolved first, so a link
    to site-packages is site-packages. A folder named site-packages or dist-packages anywhere on its path counts,
    and so does any folder equal to or inside the interpreter's stdlib or site folders."""
    real = Path(root).expanduser().resolve()
    named = _INSTALLED_NAMES.intersection(real.parts)
    if named:
        return f"it is, or lies inside, a {sorted(named)[0]} folder"
    for place in interpreter_locations(python):
        if real == place or real.is_relative_to(place):
            return f"it is, or lies inside, {str(place)!r}, which belongs to the Python installation"
    return ""


def provenance_gap(root: Path) -> list[str]:
    """What Warden cannot establish about a checkout: a git commit of its own, a version in its pyproject.toml."""
    from . import versions
    gap = []
    if versions.own_commit(root) is None:
        gap.append("git commit (it is not a git checkout of its own)")
    if versions.project_version(root) is None:
        gap.append("version (its pyproject.toml gives none Warden can read)")
    return gap


def locate_module(package: str, root: Optional[Path], *, python: Optional[str] = None,
                  timeout: float = 60) -> Optional[Path]:
    """Where `package` resolves when `root` is the instrument's path and the interpreter is started the way an
    instrument is (empty working directory, `-P`, no inherited PYTHONPATH). None when it resolves nowhere.
    The module file is found, never imported, so no instrument code runs here."""
    with tempfile.TemporaryDirectory(prefix="warden-instrument-") as empty:
        try:
            proc = subprocess.run([python or sys.executable, "-P", "-c", _PROBE, package], capture_output=True,
                                  text=True, env=instrument_env(root), cwd=empty, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            return None
    lines = proc.stdout.strip().splitlines() if proc.returncode == 0 else []
    return Path(lines[-1]).resolve() if lines and lines[-1].strip() else None


def verify_root(package: str, root: Optional[Path], *, python: Optional[str] = None,
                allow_uncommitted: bool = False) -> Path:
    """The module file `package` resolves to, once `root` is shown to be what the instrument will load from.

    Raises `InstrumentRootError` unless `root` is an existing directory that holds `package` and the
    interpreter resolves `package` under it. A root that does not hold the package fails here exactly as it
    does with nothing installed, instead of being satisfied by a copy in site-packages. A root that is an installed
    location is refused whatever it holds. A root without a git commit and a version of its own is refused unless
    `allow_uncommitted` (the run is then recorded as having used one, and is never a plain ACCEPT)."""
    who = INSTRUMENT_PACKAGES.get(package, package)
    if root is None:
        raise InstrumentRootError(f"{who} was run with no root. Warden will not use an installed copy of "
                                  f"{package} in place of a named checkout. Nothing was run.", package)
    real = Path(root).expanduser().resolve()
    if not real.is_dir():
        raise InstrumentRootError(f"The {who} root {str(root)!r} does not exist or is not a directory. "
                                  "Nothing was run.", package)
    where = installed_location(real, python)
    if where:
        raise InstrumentRootError(f"The {who} root {str(root)!r} is an installed copy, not a checkout: {where}. "
                                  "An installed copy never stands in for a named checkout. Nothing was run.", package)
    if not (real / package / "__init__.py").is_file():
        raise InstrumentRootError(f"The {who} root {str(root)!r} has no {package} package, so it is not a "
                                  f"{who} checkout. An installed copy would not be used in its place. "
                                  "Nothing was run.", package)
    found = locate_module(package, real, python=python)
    if found is None:
        raise InstrumentRootError(f"The {package} package under the {who} root {str(root)!r} could not be "
                                  "located by the interpreter. Nothing was run.", package)
    if not found.is_relative_to(real):
        raise InstrumentRootError(f"The {package} package the interpreter would load is {str(found)!r}, which "
                                  f"is not under the {who} root {str(root)!r}. Nothing was run.", package)
    if not allow_uncommitted:
        gap = provenance_gap(real)
        if gap:
            raise InstrumentRootError(
                f"The {who} root {str(root)!r} is not a checkout Warden can name: it has no {' and no '.join(gap)}. "
                "A plain copy of the package is refused; pass --allow-uncommitted-instruments to run it anyway "
                "(recorded, and never better than ACCEPT_UNVERIFIED). Nothing was run.", package)
    return found


def run_instrument(cmd: Sequence[str], *, roots: Sequence[Optional[Path]], timeout: float,
                   extra_env: Optional[Mapping[str, str]] = None,
                   packages: Optional[Mapping[str, Optional[Path]]] = None,
                   allow_uncommitted: bool = False) -> subprocess.CompletedProcess:
    """Run `cmd` (python, then arguments) in an empty directory with `-P` added.

    `packages` maps each instrument package the run depends on to the root it must come from; every one is
    checked with `verify_root` first, and a failure raises `InstrumentRootError` before anything is run."""
    for package, package_root in (packages or {}).items():
        verify_root(package, package_root, python=cmd[0], allow_uncommitted=allow_uncommitted)
    full = [cmd[0], "-P", *cmd[1:]]
    env = instrument_env(*roots)
    if extra_env:
        env.update(extra_env)
    logger.debug("instrument: %s (timeout %ss)", " ".join(full), timeout)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="warden-instrument-") as empty:
        try:
            proc = subprocess.run(full, capture_output=True, text=True, env=env, cwd=empty, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.info("instrument %s did not finish after %.1fs: %s", _label(full), time.monotonic() - started,
                        type(exc).__name__)
            raise
    logger.info("instrument %s exited %s in %.1fs", _label(full), proc.returncode, time.monotonic() - started)
    return proc


def _label(cmd: Sequence[str]) -> str:
    """A short name for a command in a log line: the module and its first word, e.g. `swizzle.cli prove`."""
    words = list(cmd)
    if "-m" in words and words.index("-m") + 1 < len(words):
        at = words.index("-m")
        return " ".join(words[at + 1: at + 3])
    return Path(words[0]).name
