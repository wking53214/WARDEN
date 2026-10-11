"""Approve a held unverified result the way a person would: a grant for its exact digest, then apply."""

from pathlib import Path

from warden import held
from warden.authorization import grant


def keep_digest(target: Path, digest: str):
    assert digest, "the run held nothing to keep"
    auth = grant("Test Reviewer", held.KEEP_OPERATION, f"{Path(target).resolve()}@{digest}",
                 "held-result", "reviewed in test")
    return held.keep(target, digest, auth)


def keep_held(result, target: Path):
    return keep_digest(target, result.held_digest)
