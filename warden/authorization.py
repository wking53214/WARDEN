"""Human authority boundary.

Warden proposes. A human (or a governing process acting as one) authorizes.
Nothing in this package treats a proposal as permission.

UNKNOWN is not APPROVED. A missing Authorization is a refusal, not a default.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone


class Unauthorized(RuntimeError):
    """A transformation was asked to apply without a granted authorization."""


#: Names that may never authorize a change: Warden itself and every other seat or instrument in the
#: stack, plus the placeholders that mean "nobody". Compared after `canonical`, as a prefix.
SELF_ACTORS = ("warden", "thewarden", "drafter", "burnish", "ghost", "ghosttools", "swizzle", "assay", "judge")
#: Placeholders that mean "nobody". Matched whole, so a person named Selfridge is not turned away.
NOBODY = ("self", "unknown", "anonymous", "none", "nobody")

#: Letters from other alphabets that look like a Latin letter. NFKC does not fold these, so a name written
#: with them would otherwise slip past the check ("Dгafter", with a Cyrillic g-like letter).
_LOOKALIKES = str.maketrans({
    "а": "a", "в": "b", "с": "c", "е": "e", "н": "h", "к": "k", "м": "m", "о": "o", "р": "p", "т": "t",
    "х": "x", "у": "y", "і": "i", "ј": "j", "ѕ": "s", "ɡ": "g", "г": "r", "ԁ": "d", "ɩ": "l", "ӏ": "l",
    "α": "a", "β": "b", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u",
    "χ": "x", "γ": "y", "ϲ": "c", "ʜ": "h", "ᴅ": "d", "ᴊ": "j", "ᴡ": "w", "ɴ": "n", "ʀ": "r", "ɢ": "g",
    "0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t", "$": "s", "@": "a", "!": "i", "|": "l",
})


def _fold(ch: str) -> str:
    """One character with small-capital Latin letters (such as U+1D1C) turned into plain Latin."""
    name = unicodedata.name(ch, "")
    if name.startswith("LATIN LETTER SMALL CAPITAL ") and len(name.split()[-1]) == 1:
        return name.split()[-1].lower()
    return ch


def canonical(actor: str) -> str:
    """An actor name as it is compared: compatibility forms and accents folded (NFKD), invisible and
    format characters dropped, lower case, look-alike letters folded to Latin, and everything that is not
    a letter or digit removed.

    "D r a f t e r", "DRAFTER", "Dr\\u200bafter", fullwidth "Ｄrafter", a Cyrillic-lookalike "Drаfter" and a
    small-capital "Jᴜdge" all fold to the reserved name they imitate.
    """
    text = unicodedata.normalize("NFKD", str(actor))
    text = "".join(ch for ch in text if unicodedata.category(ch) not in {"Cf", "Cc", "Cs", "Co", "Mn", "Me"})
    text = "".join(_fold(ch) for ch in text).casefold().translate(_LOOKALIKES)
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if ch.isalnum())


def is_stack_actor(actor: str) -> bool:
    """True when `actor` names Warden, another part of the stack, or nobody (prefix match; any case;
    spaces, punctuation, zero-width characters and look-alike letters do not help)."""
    name = canonical(actor)
    return name.startswith(SELF_ACTORS) or name in NOBODY


@dataclass(frozen=True)
class Authorization:
    """WHO authorized WHAT, on WHICH subject, for WHICH operation.

    `granted` is the only field that permits a write. An object with
    granted=False is a recorded refusal, not an incomplete yes.
    """

    actor: str
    operation: str
    subject: str
    scope: str
    reason: str
    granted: bool
    at: str
    policy_version: str = "warden-0.1"

    def permits(self, operation: str, subject: str) -> bool:
        return (
            self.granted
            and self.operation == operation
            and self.subject == subject
        )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def refuse(actor: str, operation: str, subject: str, reason: str) -> Authorization:
    return Authorization(
        actor=actor,
        operation=operation,
        subject=subject,
        scope="none",
        reason=reason,
        granted=False,
        at=now_iso(),
    )


def grant(
    actor: str,
    operation: str,
    subject: str,
    scope: str,
    reason: str,
) -> Authorization:
    if not actor.strip() or not canonical(actor) or is_stack_actor(actor):
        raise Unauthorized(
            "Warden cannot authorize its own write. Actor must be a human "
            "or an external governing process, not Warden, 'self', 'unknown' or another part of the "
            "stack (Drafter, Burnish, Ghost, SWIZZLE, ASSAY, Judge)."
        )
    if not reason.strip():
        raise Unauthorized("An authorization without a reason is not an authorization.")
    return Authorization(
        actor=actor.strip(),
        operation=operation,
        subject=subject,
        scope=scope,
        reason=reason.strip(),
        granted=True,
        at=now_iso(),
    )
