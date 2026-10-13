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

_TAGS = ["fn", "tv", "gg", "hq", "main", "plays", "clips", "fan", "watch"]


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _candidate(rng: random.Random) -> str:
    pattern = rng.choices(
        ["first_initial_num", "first_last", "first.last", "camel_pair", "word_word_num", "first_word", "word_num",
         "first_tag", "word_tag", "first_num"],
        weights=[14, 12, 6, 14, 10, 10, 8, 8, 8, 10],
        k=1,
    )[0]
    first, last = rng.choice(_FIRST), rng.choice(_LAST)
    w1, w2 = rng.choice(_WORDS), rng.choice(_WORDS)
    num2 = f"{rng.randint(0, 99):02d}"
    year = rng.choice(["97", "98", "99", "00", "01", "02", "03", "04", "05", "06"])

    if pattern == "first_initial_num":
        return f"{first}{last[0]}{rng.choice([num2, year])}"
    if pattern == "first_last":
        return f"{first}_{last}" if rng.random() < 0.6 else f"{_cap(first)}{_cap(last)}"
    if pattern == "first.last":
        return f"{first}.{last}"
    if pattern == "camel_pair":
        return f"{_cap(w1)}{_cap(w2)}" if w1 != w2 else f"{_cap(w1)}{_cap(first)}"
    if pattern == "word_word_num":
        return f"{w1}_{w2}_{num2}" if w1 != w2 else f"{w1}_{num2}"
    if pattern == "first_word":
        return f"{first}_{w1}" if rng.random() < 0.5 else f"{first}{_cap(w1)}"
    if pattern == "word_num":
        return f"{w1}{rng.choice([num2, year, str(rng.randint(100, 999))])}"
    if pattern == "first_tag":
        return f"{first}_{rng.choice(_TAGS)}"
    if pattern == "word_tag":
        return f"{w1}{rng.choice(_TAGS)}" if rng.random() < 0.5 else f"{_cap(w1)}{rng.choice(_TAGS).upper()}"
    return f"{first}{rng.choice([num2, year, str(rng.randint(100, 999))])}"  # first_num


def generate_username(rng: random.Random, taken: set[str]) -> str:
    """Returns a handle not present in `taken` (compared case-insensitively) and adds it to `taken`."""
    for _ in range(40):
        name = _candidate(rng)[:60]
        if name.lower() not in taken:
            taken.add(name.lower())
            return name
    while True:  # extremely unlikely; guarantees termination
        name = f"{_candidate(rng)[:50]}{rng.randint(1000, 9999)}"
        if name.lower() not in taken:
            taken.add(name.lower())
            return name
