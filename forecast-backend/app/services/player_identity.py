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


def lan_core_keys(name: str) -> set[str]:
    """Candidate 'core name' skeletons of a LAN account name, so "HAVOK SwizzY", "PWR ZDоg 7" and "SwizzY"
    can be recognised as the same person: tries the name as-is and with its leading team-prefix word dropped,
    and for each drops trailing digit/punctuation-only words ("10ǃ") and trailing digits on the last word
    ("Sphinx281"). Keys shorter than 3 characters are ignored.

    Deliberately conservative -- a leading word is only ever dropped, never fuzzy-matched -- and the scripts
    using it add further guards (LAN-only players, no shared tournament, human-reviewed dry run)."""
    tokens = strip_tags(name).split()
    variants = [tokens] + ([tokens[1:]] if len(tokens) >= 2 else [])
    keys: set[str] = set()
    for toks in variants:
        toks = list(toks)
        while toks and not any(ch.isalpha() for ch in toks[-1]):
            toks.pop()
        # A trailing decorative symbol word ("亗", "水") with no ASCII letters/digits -- dropped only if a real
        # name (>= 4 ASCII letters/digits) remains, so an all-Japanese handle is left alone.
        while len(toks) > 1 and not any(ch.isascii() and ch.isalnum() for ch in toks[-1]) and \
                sum(1 for t in toks[:-1] for ch in t if ch.isascii() and ch.isalnum()) >= 4:
            toks.pop()
        if not toks:
            continue
        keys.add(skeleton(" ".join(toks)))
        last = re.sub(r"\d+$", "", toks[-1])
        if last and last != toks[-1]:
            keys.add(skeleton(" ".join(toks[:-1] + [last])))
    return {k for k in keys if len(k) >= 3 and not k.startswith("raw:")}


_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t"})


def leet_fold(key: str) -> str:
    """Digit-for-letter fold ("vic0" -> "vico"). Only ever used as a FALLBACK after exact matching found nothing,
    because pros like Cringe / Cr1nge are genuinely different people."""
    return key.translate(_LEET)


def norm_id(value: str) -> str:
    """Epic account ids compare case- and dash-insensitively."""
    return value.strip().lower().replace("-", "")
