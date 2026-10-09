"""
Shared name-identity helpers (used by osirion_service._match_player and the linker scripts).

`skeleton(name)` is the comparison key used everywhere a LAN account name has to be recognised
regardless of cosmetic differences: bracket tags removed, accents stripped, look-alike letters
(Cyrillic "о" vs Latin "o", "ν" vs "v", ...) folded, case and all punctuation dropped (including the
decorative "ǃ" U+01C3 that stands in for "!"). So "[EWC 2026] Twis Rаpid 5ǃ" and "twis rapid 5!" share
one key.
"""
from __future__ import annotations

import re
import unicodedata

_CLAN_TAG_RE = re.compile(r"\[[^\]]*\]")
_EXTRA_WHITESPACE_RE = re.compile(r"\s+")

# Look-alike characters used in Fortnite names (Cyrillic/Greek/etc. -> Latin).
_HOMOGLYPHS = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i", "ѕ": "s",
    "ј": "j", "һ": "h", "ԁ": "d", "к": "k", "м": "m", "н": "h", "т": "t", "в": "b", "ӏ": "l",
    "ν": "v", "ο": "o", "ρ": "p", "α": "a", "ι": "i", "τ": "t", "κ": "k", "ε": "e", "υ": "u",
    "β": "b", "ⅰ": "i", "ɑ": "a", "ı": "i", "ɡ": "g", "ø": "o", "đ": "d", "ł": "l",
})


def strip_tags(raw: str) -> str:
    """Same cleaning as osirion_service.clean_gamertag (kept separate so this module has no
    import-time dependency on the service layer)."""
    cleaned = _EXTRA_WHITESPACE_RE.sub(" ", _CLAN_TAG_RE.sub("", raw)).strip()
    return cleaned or raw.strip()


def skeleton(name: str) -> str:
    cleaned = strip_tags(name)
    decomposed = unicodedata.normalize("NFKD", cleaned)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()
    key = "".join(ch for ch in stripped.translate(_HOMOGLYPHS) if ch.isalnum() and ch != "ǃ")
    return key or ("raw:" + cleaned.casefold().strip())


def norm_id(value: str) -> str:
    """Epic account ids compare case- and dash-insensitively."""
    return value.strip().lower().replace("-", "")
