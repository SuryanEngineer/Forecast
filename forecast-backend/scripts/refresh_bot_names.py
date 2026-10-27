#!/usr/bin/env python3
"""
Replace a chosen set of bot usernames with Fortnite-style handles (the kind of thing real players pick). Bots only (users
with a BotProfile); only display_name changes. None of the replacement names are pro players/streamers, and each is
checked against the site's username rules + profanity filter, every existing user name, and every Player gamertag.
Dry run unless --confirm.

    python3 scripts/refresh_bot_names.py                       # preview the default list
    python3 scripts/refresh_bot_names.py --confirm
    python3 scripts/refresh_bot_names.py --only ivy_smith,zoe.smith --confirm   # just these bots
"""
from __future__ import annotations

import argparse
import random
import sys

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.bot import BotProfile  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import account_service  # noqa: E402

# Bots whose names were repeated first names, the same word_word_NN shape, or trading jargon.
DEFAULT_TARGETS = """
ivy_smith ivy.young jamal.nelson zoe.smith oliver_hq callumPump glideplays mikeOnyx blakem97 ember_storm_88
nova_moon_76 storm_orca_77 orbit_cobra_96 monarch_viper_80 archieDip PumpSwing RiftDip SwingZenith OnyxSwing
ShieldRamp BearPeak
""".split()

CANDIDATES = """
SweatyPeely PeelyEnjoyer Tilted_Tim LlamaDrama_ VictoryOrBust BoxFightBarry NoBuildNate ZeroBuildZed ClutchKid07
LobbyLarry TryhardTaco DefaultDance_ BushCamper22 SupplyDropSam StormSurge99 RoyaleRiley ChugJugChad SlurpJuice_
ShieldPotty WarmupWill OGSkinSteve BattleBusBrad FloppyFish_ MidFightMike EditCourseEd TurboBuild_T PumpSweaty
Sweat_Lord_X TomatoTownTed DriftBoardDan HopOnBus_ LootLakeLuke RetailRowRay PleasantPark_ SaltySpringsSid DustyDivotDan
FlushFactoryFin LazyLagoon_ NoScopeNoah ThirdPartyTy AFKAndy_ RiftRider_ SpawnIslandSid BigPotBen ShockwaveSam
TacoTuesdayFN FNCSwannabe DuoDiaries_ ZoneWarsZack LastCircleLee EndgameEli StormEyeEmma WinStreakWes BuildBattleBo
GoldenScarAl MythicMarvin ChapterOGChad SteadyAim_ TacticalTina BoomBoxBen HeadshotHal NoMoreTilted GGWPgreg
xXSweatyXx_ ClutchOrBust_ ReloadRory_ PanicBuildPaul GoblinMode_G RoofCampRon MegaMallMax SkyBaseSid HammerTimeHal
""".split()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--only", default=None, help="comma list of current bot names to rename (instead of the default list)")
    args = ap.parse_args()
    wanted = {n.strip().lower() for n in args.only.split(",")} if args.only else {n.lower() for n in DEFAULT_TARGETS}

    db = SessionLocal()
    try:
        bot_ids = [uid for (uid,) in db.query(BotProfile.user_id).all()]
        bots = db.query(User).filter(User.id.in_(bot_ids)).all() if bot_ids else []
        targets = [u for u in bots if (u.display_name or "").lower() in wanted]
        missing = wanted - {(u.display_name or "").lower() for u in targets}
        taken = {(n or "").lower() for (n,) in db.query(User.display_name).all()}
        taken |= {(g or "").lower() for (g,) in db.query(Player.gamertag).all()}
        pool = [c for c in CANDIDATES if account_service.NAME_RE.match(c) and not account_service.is_inappropriate(c)
                and c.lower() not in account_service.RESERVED and c.lower() not in taken]
        random.shuffle(pool)
        if len(pool) < len(targets):
            raise SystemExit(f"Only {len(pool)} usable replacement names for {len(targets)} bots -- add more CANDIDATES.")
        for u, new in zip(targets, pool):
            print(f"  {u.display_name!r:22} -> {new!r}")
            if args.confirm:
                u.display_name = new
        if missing:
            print("\nNot found among bots (already changed, or not a bot):", ", ".join(sorted(missing)))
        print(f"\n{len(targets)} bot(s) {'renamed' if args.confirm else 'would be renamed'}.")
        if args.confirm:
            db.commit()
        else:
            print("Dry run only -- re-run with --confirm to apply.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
