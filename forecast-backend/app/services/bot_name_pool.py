"""
Hand-picked, believable usernames for bot accounts: the kind of handles real people actually pick (first names with
birth years, gamer word-mashups, initials + surname, lowercase one-worders, a few in-jokes). None are real pro
gamertags or well-known streamers. All satisfy the site's username rules (3-20 chars, letters/digits/_ . -).

Used first by app/services/bot_names.generate_username; the procedural generator only kicks in once this pool is
exhausted, so the first ~450 bots all get hand-written names.
"""
from __future__ import annotations

CURATED: list[str] = """
jakelopez04 emma_r23 tylerb_ jordanm.22 dylan_hayes mason.kreb ethan_w07 noah.fitz07 liamcarter lucas_fn
owen_plays mateo_r9 zachattack cole.stanton dom_ricci ianmoore98 nate_g23 brodie.k austin_vance shaneoh
tomasz_k kaylee_plays sofia.k maya_b05 chloe.dev zoe_fn_ lilyp_04 avamarie.q nora_t9 ella.ross07
graceful_g jess_m_22 katieb.fn mia_tran_ ruby.s88 hannah_gg tessa.hale paigeturner bella_q06 ivy_wren
sweatybanana crispywaffles toxictacos midnightmoose pancakebandit soggybiscuit quietstorm lazyhawk
turbotoast burntmarshmallow noodlecannon waffleiron_ salsaverde mildlyspicy cheddarbob bigmoodgary
sleepyraccoon pixelpirate44 rustyspoon_ copperkettle ghostly22 nightowl_nate coldbrew.carl
saltyseagull dustyboots_ quickfox_91 stormchaser88 emberfall_ novaridge frostbyte_k cobaltjay
hollowpoint_ dankdoughnut wafflehouse_w mapleleaf.mac northernlights_ bluemoon_ben redwood_rhys
tinyhurricane lucky_larry7 sneakyowl9 captain_crunchy baconator_ trashpanda_ lonesome.dove
maxwell_trades theo_b_24 benji_bulls leo.markets quantquinn finn_invests stocksbycole pennystock_pete
longtermlucas daytrader_dan dividend_dave yieldhunter_ bullish_ben beartrap_bri paperhands_pat
diamondhands_d hodl_hank volatilevic marketmaker_m ticker_tom ironcondor_ chartwizard_ greenarrow_g
roundlot_ross buyandhold_bo valueseeker_v alpha_amir spreadsheet_sam coffee.and.candles
carlos_m_fn diego.fortnite hugo_b_gaming enzo_rossi_ pablo.v13 andre_j_7 marcus_hill_ jamal.k.22
omar_fz ravi_s_play arjun.k_ kenji_t_ yuki.san93 minjun_k tariq_h7 yusuf_a_fn amir.tehr_ nikolai_v
anders_dk magnus.b felix_h_05 jonas.k.fn emil_se_ tobias_n_ kasper_l_ rasmus.v luca.b_ marco.polo_fn
callum_fn_ jamie.oc sean_murph_ harry_b_fn oliver.w_ jackhammer_j george.p_ archie_g_fn charliebrown_c
alfie_t_ rory_m_ ewan_b_ declan_c_ finley_d_ kieran.h_ niall_o_ cian_fn_ aaron_wlsh_ gareth_j_
mikey.d_ danny_boi_ benjamin_g_ jonny.b.fn timmy_t_ joey_c_ robbie_w_ andy_r_ sammy_k_ nicky_p_
tommy_l_ billy_h_ jakey_m_ zackattack dre_wins_ liv_gg izzy.fn abby_k_ lexi_j_ kayla_r_ bree_m_
rj_sniper tj_builds kb_ontop jp_clutch dj_ramps cj_boxfights mj_edits aj_zerobuild bj_peaks
xavier_z_ ximena.b yara_fn_ zane_h_ zelda_fn_ quincy_t_ rowan_v_ sasha.k_ talia_m_ uriel_s_
vince_r_ wyatt_e_ xander_l_ yosef_b_ zion_d_ ansel_k_ bryce_n_ cade_p_ dax_morrow_ elias_w_
fletcher_t gideon_h_ harlan_j_ idris_a_ jasper.f_ knox_b_ lennox_c_ maddox_g_ nolan.r_ orion_k_
pierce_d_ quentin_m_ remy_l_ silas.t_ tristan_o_ ulises_v_ vaughn_c_ weston.b_ ziggy_p_
dragonfruit_d sunnyside_up lemonade_larry orangejuice_o strawberry.s peachy_keen_ mangotango_
kiwi_kid_ blueberry.b_ cherrybomb_c_ pineapple.p coconut_cove_ guava_g_ papaya_pete_ lychee_lou_
nightshift_nick latenight_lu sundaydrive_s weekendwarrior_ afterschool_a gradstudent_gus
overtime_ollie lunchbreak_len mondayblues_m coffeeaddict_c redeye_rae earlybird_ed
the_real_dave not_a_bot_bob itsjustjosh its_me_mitch imjustkyle iamcarlos_ mr_nobody_77
ur_friend_andy just_vibing_v only_here_4_fun purely_luck_ hello_its_ben hey_its_gabe
lowkey_lenny highkey_hal midrange_mike offmeta_olive onmeta_ollie casualkev_ tryhard_tara
sweat_lord_sam grinder_gio_ clutch_kid_cj noob_slayer_n mid_tier_tim top_frag_tina
pro_in_progress practice_pete aim_trainer_al_ bot_lobby_ben_ lobby_legend_lia zone_walker_zed
storm_surge_sam rift_runner_ray loot_goblin_lee chest_hunter_cy glide_king_gus peak_pilot_pia
ramp_rush_ria wall_up_wes box_fight_bo edit_course_ed tarp_taker_tia shockwave_sy
nova_nine_ garnet_gray_ onyx_olsen_ cobalt_cruz_ amber_aldo_ ivory_ives_ jade_jonah_ ruby_ronan_
opal_ortiz_ topaz_tate_ pearl_penn_ coral_cade_ slate_sloane_ indigo_ines_ crimson_cal_
helena.v kostas_t_ dmitri_o_ ivan.petrov7 anya_k_fn_ katya_l_ olga.fn_ sergei_m7 viktor_b_
mei_lin_fn_ hiro_s_play_ takeshi_k_ aiko.fn_ sora_n_gg_ haruto_77 rin_okada_ yuna_p_
priya_s_fn_ rohan.m_ ananya_k7 dev_patel_ vikram_r_ neha_b_play_ kabir_s_gg aarav_fn_
tariq.fn_ layla_m_ hassan_k_ noor.s_gg zain_ali_ rania_b_ khalid_o7 salma.fn_
thabo_m_ amara_n_ kwame.b_ zuri_fn_ jabari_h_ nia_t_gg_ kofi_a_ imani.s_
mateus_f_ luiza.b_ thiago_s7 camila_fn_ rafa_m_gg_ bruno_c_ isabela.v_ pedro_h7
santi_g_fn_ valeria.m_ nacho_r_ lucia_d_gg_ mateo.fn_ carmen_o_ joaquin_b7 pilar_s_
""".split()

# Defensive cleanup: drop anything that breaks the username rules or duplicates (case-insensitive).
import re as _re

_OK = _re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{2,19}$")
_seen: set[str] = set()
_clean: list[str] = []
import zlib as _zlib

for _n in CURATED:
    # Trailing underscores are legit but a wall of them reads as generated -- keep roughly 1 in 8.
    if _n.endswith("_") and _zlib.crc32(_n.encode()) % 8 != 0:
        _n = _n.rstrip("_")
    if _OK.match(_n) and _n.lower() not in _seen:
        _seen.add(_n.lower())
        _clean.append(_n)
CURATED = _clean
del _re, _zlib, _OK, _seen, _clean, _n
