"""RAM variables of Super Mario All-Stars' Super Mario Bros. (SNES): the candidates
verified before they were added to ``stimuli/SuperMarioAllStars-Snes/data.json``, and the
object id tables, which this port shares with the NES original.

Sources: Data Crystal's partial SMAS map plus addresses already present in the dataset's
own data.json, https://datacrystal.tcrf.net/wiki/Super_Mario_All-Stars_(SNES)/RAM_map; the
object ids from 1wErt3r's SMB disassembly, https://gist.github.com/1wErt3r/4048722
"""

from __future__ import annotations

from typing import Dict, List

from videogames_utils.events.ram import Candidate


# --- Super Mario All-Stars, SMB1 (SNES) --------------------------------------------
# The port keeps SMB1's $07xx player block at the same WRAM offsets ($7E0756 is still
# PlayerStatus) and shifts the timer block by +$10. The shipped data.json's
# "player_powerup" ($0578) and "star_power_timer" ($0553) do NOT hold what their names
# say: over all 1232 replays player_powerup takes values such as 28, 82, 107 and 231 with
# no relation to the engine's grow/hit transitions (it produced rows like
# "Powerup_started/107"), and star_power_timer holds constants rather than a countdown.
# Both are left in place (see apply_ram.MISLABELLED); the generator uses these instead.
#
# Found by recording the first 8 KB of WRAM on every frame of a w4-2 replay containing
# two mushrooms, two fire flowers and two hits, and keeping the bytes whose value is
# constant between the engine's 9/12/10 transitions and differs across them: exactly one
# byte qualifies. The two timers were then confirmed through the emulator's own
# variable reader (values 8 -> 1 over 212 frames after each hit; 35 -> 1 over 730 frames
# after a star in a w5-1 replay), i.e. the NES behaviour to the frame.
#
# Addresses are written the way the existing entries are: as offsets in the 8 KB block
# at 0 that the core exposes as a mirror of $7E0000-$7E1FFF.

SMAS_CANDIDATES: List[Candidate] = [
    Candidate("player_status", 0x0756, "|u1", "PlayerStatus",
              "0 small, 1 super, 2 fire; changes on the frame the engine enters 9/12 "
              "(grow / fire flower) or 10 (injury). Replaces 'player_powerup'"),
    Candidate("injury_timer", 0x07AE, "|u1", "InjuryTimer",
              "post-hit invulnerability countdown, 8 -> 0 over ~212 frames"),
    Candidate("star_timer", 0x07AF, "|u1", "StarInvincibleTimer",
              "star countdown, 35 -> 0 over ~730 frames. Replaces 'star_power_timer'"),
    # Player_State is $001D on the NES, just before Enemy_State ($001E..); this port's
    # sprite_state_* table starts at $0029, and $0028 behaves exactly like the NES byte:
    # 0 on the ground, 1 rising, 2 falling, 3 for the 87 frames of the flagpole slide of
    # every cleared level. Over 40 replays with bricks, 328 of the 331 +50 score steps
    # during play happen at 1 -- the head striking the brick from below.
    Candidate("jump_airborne", 0x0028, "|u1", "Player_State",
              "0 on the ground, 1 jumping, 2 falling, 3 flagpole slide; same name as "
              "the NES variable. Lets BlockSmashed require the player to be airborne"),
]



# --------------------------------------------------------------------- decode tables

#: Enemy/object ids for SMB1 ($00-$36), from SMBDIS.ASM: the named constants plus the
#: ``InitEnemyRoutines`` jump table, which covers the whole range including the entries
#: that have no symbolic constant. Ids with neither a constant nor a distinguishing init
#: routine are left as ``Unknown0xNN`` rather than guessed; the validator flags any that
#: actually turn up in the data.
#:
#: Super Mario All-Stars reuses these ids verbatim in ``sprite_number_*`` (verified
#: empirically against mariostars replays: 13=PiranhaPlant, 6=Goomba, 2=BuzzyBeetle,
#: 0=GreenKoopa, 14=GreenParatroopa, 48=FlagpoleFlag, 49=StarFlag).
SMB1_ENEMY_IDS: Dict[int, str] = {
    0x00: "GreenKoopa", 0x01: "Unknown0x01", 0x02: "BuzzyBeetle", 0x03: "RedKoopa",
    0x04: "Unknown0x04", 0x05: "HammerBro", 0x06: "Goomba", 0x07: "Blooper",
    0x08: "BulletBill", 0x09: "Unknown0x09", 0x0A: "GreyCheepCheep",
    0x0B: "RedCheepCheep", 0x0C: "Podoboo", 0x0D: "PiranhaPlant",
    0x0E: "GreenParatroopaJump", 0x0F: "RedParatroopa", 0x10: "GreenParatroopaFly",
    0x11: "Lakitu", 0x12: "Spiny", 0x13: "Unknown0x13", 0x14: "FlyingCheepCheep",
    0x15: "BowserFlame", 0x16: "Fireworks", 0x17: "BulletBillCheepCheepFrenzy",
    0x18: "StopFrenzy", 0x19: "Unknown0x19", 0x1A: "Unknown0x1A",
    0x1B: "ShortFirebar", 0x1C: "ShortFirebar", 0x1D: "ShortFirebar",
    0x1E: "ShortFirebar", 0x1F: "LongFirebar",
    0x20: "Unknown0x20", 0x21: "Unknown0x21", 0x22: "Unknown0x22",
    0x23: "Unknown0x23", 0x24: "BalancePlatform", 0x25: "VerticalPlatform",
    0x26: "LargeLiftUp", 0x27: "LargeLiftDown", 0x28: "HorizontalPlatform",
    0x29: "DropPlatform", 0x2A: "HorizontalPlatform", 0x2B: "PlatformLiftUp",
    0x2C: "PlatformLiftDown", 0x2D: "Bowser", 0x2E: "PowerUpObject",
    0x2F: "VineObject", 0x30: "FlagpoleFlagObject", 0x31: "StarFlagObject",
    0x32: "JumpspringObject", 0x33: "BulletBillCannon", 0x34: "Unknown0x34",
    0x35: "RetainerObject", 0x36: "EndOfEnemyObjects",
}

#: Moving platforms and lifts. They live in enemy slots but are scenery, not enemies.
SMB1_PLATFORM_IDS = frozenset(range(0x24, 0x2D))

#: Items, scenery and end-of-level objects that occupy an enemy slot.
SMB1_ITEM_SCENERY_IDS = frozenset({0x16, 0x2E, 0x2F, 0x30, 0x31, 0x32, 0x35, 0x36})

#: Spawner / control objects that occupy an enemy slot without ever being drawn.
#: They churn through a slot a frame at a time and must not produce Enemy_* events.
SMB1_SPAWNER_IDS = frozenset({0x17, 0x18})

#: The two ids a Bullet Bill can occupy: 0x08 when spawned by a frenzy and 0x33 when
#: fired from a cannon. Both are the same object -- measured over 120 mario replays,
#: runs of either id move at a median 1.5 px/frame, and 0x33 accounts for the large
#: majority (331 flying runs vs 90 for 0x08; on mariostars 283 vs 43). 0x33 was
#: previously classed as a spawner, which discarded most of the Bullet Bills in both
#: datasets outright.
#:
#: The id is shared with the stationary cannon object, which sits in a slot without
#: moving. Where per-slot X is available (NES) a motion test separates them; see
#: ``smb1._is_flying_bullet``.
SMB1_BULLET_IDS = frozenset({0x08, 0x33})

#: SMB1 ids that are projectiles rather than enemies proper. Bullet Bills are NOT here:
#: they are stompable, damage the player on contact, and behave as enemies. Bowser's
#: flame cannot be defeated and stays a projectile.
SMB1_PROJECTILE_IDS = frozenset({0x15})

#: The Piranha Plant, which hides inside its pipe for part of its cycle.
SMB1_PIRANHA_ID = 0x0D

#: Everything that is NOT an enemy for the purposes of Enemy_* events.
SMB1_NON_ENEMY_IDS = (
    SMB1_PLATFORM_IDS | SMB1_ITEM_SCENERY_IDS | SMB1_SPAWNER_IDS | SMB1_PROJECTILE_IDS
)


#: Existing data.json keys whose names are wrong, with the disassembly's actual symbol.
#: The addresses are correct, so the keys are kept as aliases; this only records the truth
#: for documentation.
MISLABELLED = {
    "player_powerup": "($0578) NOT the power-up state -- holds unrelated values such "
                      "as 82 and 107; use player_status ($0756)",
    "star_power_timer": "($0553) NOT the star timer -- holds constants, never counts "
                        "down; use star_timer ($07AF)",
}
