"""
Realistic-looking usernames for the bot trader accounts.

The market launches with a bot population standing in for a larger player base, so each bot gets a handle that reads
like an ordinary community member's (a mix of first-name handles, gamer-style word pairs, and short trader-flavoured
tags) rather than "Momentum Bot #14". Names never include real pro-player gamertags, so a bot can't be mistaken for,
or impersonate, an actual competitor.

`generate_username` is deterministic given an `rng` and the set of names already taken, and always returns a unique
value (a numeric tail is appended as a last resort).
"""
from __future__ import annotations

import random

_FIRST = [
    "jake", "mike", "tyler", "chris", "alex", "sam", "jordan", "ryan", "connor", "dylan", "ethan", "noah", "liam",
    "owen", "luke", "cole", "blake", "trevor", "austin", "brandon", "kyle", "nick", "josh", "matt", "zach", "evan",
    "logan", "hunter", "mason", "caleb", "isaac", "adam", "derek", "eric", "jesse", "marcus", "andre", "diego",
    "mateo", "lucas", "leo", "finn", "max", "theo", "ben", "dan", "tom", "will", "harry", "oliver", "jack", "george",
    "charlie", "archie", "callum", "jamie", "sean", "niko", "luca", "felix", "jonas", "emil", "tobias", "anders",
    "kasper", "rasmus", "hugo", "enzo", "gabe", "carlos", "pablo", "sophie", "emma", "maya", "chloe", "lily", "ava",
    "zoe", "ella", "grace", "nora", "ivy", "kate", "jess", "amy", "lea", "mia", "ruby", "hannah", "olivia", "tess",
    "riley", "casey", "morgan", "taylor", "jamal", "omar", "ravi", "arjun", "kenji", "yuki", "minjun", "tariq",
]

_LAST = [
    "smith", "jones", "miller", "davis", "clark", "lewis", "walker", "hall", "young", "king", "wright", "scott",
    "green", "baker", "adams", "nelson", "hill", "moore", "reed", "cook", "bell", "murphy", "bailey", "cooper",
    "ward", "brooks", "kelly", "price", "hayes", "foster", "gray", "ross", "wood", "james", "long", "myers",
    "fisher", "hunt", "stone", "webb", "tran", "nguyen", "kim", "park", "patel", "silva", "costa", "novak", "larsen",
    "berg", "dahl", "lund", "meyer", "fischer", "weber", "koch", "rossi", "ricci", "ortiz", "lopez", "reyes",
]

_WORDS = [
    "clutch", "storm", "pump", "shield", "bush", "peak", "rift", "apex", "drift", "nova", "frost", "ember", "viper",
    "hawk", "wolf", "fox", "raven", "ghost", "pixel", "turbo", "rapid", "sweat", "solo", "duo", "squad", "build",
    "edit", "ramp", "zone", "loot", "chest", "glide", "bull", "bear", "vector", "flip", "swing", "dip",
    "moon", "rocket", "whale", "shark", "tiger", "bison", "cobra", "raptor", "falcon", "orca", "lynx", "comet",
    "onyx", "cipher", "monarch", "zenith", "harbor", "summit", "ridge", "anchor", "beacon", "atlas", "orbit",
]

_NICK = [
    "mikey", "danny", "benji", "jonny", "timmy", "alfie", "joey", "charlie", "freddy", "teddy", "robbie", "andy",
    "sammy", "nicky", "tommy", "billy", "jakey", "zack", "dre", "liv", "izzy", "abby", "lexi", "kayla", "bree",
]

_TAGS = ["fn", "ttv", "yt", "gg", "clips", "plays", "tv", "xo"]

_PREFIX = ["its", "real", "the", "not", "iam", "mr", "x", "itz", "just", "ur"]


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _digits(rng: random.Random) -> str:
    return rng.choice([
        f"{rng.randint(0, 99):02d}", f"{rng.randint(0, 99):02d}",
        rng.choice(["97", "98", "99", "00", "01", "02", "03", "04", "05", "06", "07"]),
        str(rng.randint(100, 999)),
        str(rng.choice([69, 7, 13, 21, 23, 24, 77, 99, 420][:-2] + [7, 13, 21, 23, 24, 77, 99])),
    ])


def _stretch(name: str, rng: random.Random) -> str:
    """mikey -> mikeyy / mikeyyy (a very common real-handle habit)."""
    if rng.random() < 0.5 and name and name[-1].isalpha():
        return name + name[-1] * rng.randint(1, 2)
    return name


def _leet(name: str, rng: random.Random) -> str:
    table = {"a": "4", "e": "3", "i": "1", "o": "0", "s": "5"}
    out, done = [], 0
    for ch in name:
        if ch in table and done < 2 and rng.random() < 0.5:
            out.append(table[ch])
            done += 1
        else:
            out.append(ch)
    return "".join(out)


def _candidate(rng: random.Random) -> str:
    kind = rng.choices(
        ["name_digits", "name_initial", "nick", "prefix_name", "name_word", "word_word", "word_digits", "name_tag",
         "name_last", "x_name", "leet"],
        weights=[22, 11, 10, 9, 9, 10, 8, 7, 9, 5, 0],
        k=1,
    )[0]
    first, last = rng.choice(_FIRST), rng.choice(_LAST)
    w1, w2 = rng.choice(_WORDS), rng.choice(_WORDS)
    sep = rng.choice(["", "", "_", "."])

    if kind == "name_digits":
        return f"{first}{rng.choice(['', '_'])}{_digits(rng)}"
    if kind == "name_initial":
        return f"{first}{last[0]}{rng.choice(['', '', _digits(rng)])}"
    if kind == "nick":
        return f"{_stretch(rng.choice(_NICK), rng)}{rng.choice(['', '', _digits(rng)])}"
    if kind == "prefix_name":
        return f"{rng.choice(_PREFIX)}{sep}{first}"
    if kind == "name_word":
        return f"{first}{sep}{w1}"
    if kind == "word_word":
        if w1 == w2:
            w2 = first
        return f"{_cap(w1)}{_cap(w2)}" if rng.random() < 0.6 else f"{w1}{sep}{w2}"
    if kind == "word_digits":
        return f"{w1}{rng.choice(['', '_'])}{_digits(rng)}"
    if kind == "name_tag":
        return f"{first}{rng.choice(['', '_'])}{rng.choice(_TAGS)}"
    if kind == "name_last":
        return f"{first}{sep}{last}" if sep else f"{_cap(first)}{_cap(last)}"
    if kind == "x_name":
        return f"x{first}x" if rng.random() < 0.4 else f"{first}x{_digits(rng)}"
    return _leet(f"{first}{rng.choice(['', '_'])}{w1}", rng)  # leet


def generate_username(rng: random.Random, taken: set[str]) -> str:
    """Returns a handle not present in `taken` (compared case-insensitively) and adds it to `taken`."""
    for _ in range(40):
        name = _candidate(rng)[:40]
        if 3 <= len(name) and name.lower() not in taken:
            taken.add(name.lower())
            return name
    while True:  # extremely unlikely; guarantees termination
        name = f"{_candidate(rng)[:30]}{rng.randint(1000, 9999)}"
        if name.lower() not in taken:
            taken.add(name.lower())
            return name
