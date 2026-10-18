"""Hand-written documentation of the mariostars events, rendered into the dataset README."""

#: Why a vocabulary entry produces no row in the dataset. Entries absent from here that
#: have zero rows are reported as "never occurred". Keep this honest: "not implemented"
#: means the pipeline has no detector for it.
NOT_EMITTED = {
    "PlayerDied/Timeout": "implemented (death routine with the timer at 0); no "
                          "subject ever ran out of time",
    "ItemCollected/Powerup": "not implemented; the pickup is the first frame of the "
                             "`PlayerState/Super`, `Fire` or `Star` row it starts (a "
                             "1-up is `LifeGained`)",
    "EnemyAttack/{enemy_type}": "not implemented (no verified RAM signal)",
    "ProjectileOnScreen/{projectile_type}": "implemented for Bowser's flames (id "
                                            "0x15) but the flame never passes the "
                                            "visibility test; not yet resolved",
    "ShellStartedMoving": "not implemented for SMB1",
    "CheckpointReached": "deliberately not emitted: `HalfwayPage` is written at a "
                         "death past the midpoint, not at the crossing",
    "LevelRestarted": "not applicable: an SMB1 repetition spans all its lives, and "
                      "each restart is a `Screen/LevelIntro` row",
    "Action/Start": "never pressed",
    "Action/Select": "never pressed",
}

#: Accuracy notes, in Markdown. Reviewed by hand when the generator changes.
NOTES = """\
- Super Mario All-Stars reuses Super Mario Bros.' object id table verbatim, verified
  empirically (`sprite_number_*` values decode to PiranhaPlant / Goomba / BuzzyBeetle /
  GreenKoopa / Paratroopa / FlagpoleFlag on the levels where those appear), and the same
  engine enumeration in `player_action_state`. The same generator therefore serves both
  `mario` and `mariostars`; see the mario README for the shared logic.
- Visibility uses bit 0 of `sprite_onscreen_flag_*`. This port exposes no per-sprite
  coordinates, so the Piranha Plant and Bullet Bill refinements of the NES do not apply:
  a plant counts for its whole cycle and roughly 10% of Bullet Bill tracks are cannons.
- **Three RAM variables were added** for the `PlayerState/*` rows: `player_status`
  ($0756), `injury_timer` ($07AE) and `star_timer` ($07AF). The shipped `player_powerup`
  ($0578) and `star_power_timer` ($0553) do **not** hold what their names say (values
  such as 82 and 107, constants rather than a countdown) and are no longer read.
- The title card (`Screen/LevelIntro`) is invisible to the engine variable on this port,
  which idles at 8 while the card is up. It is read from `OperMode_Task` ($0772), decoded
  out of the shipped `reset` variable (a 4-byte BCD read at $0771 whose second byte pair
  is that task; 1 = card, 3 = game routines). The port fades in and out around the card,
  so those boundaries are within ~30 frames (0.5 s).
- A fall death is dated from the frame the level timer stops ticking, plus half a tick;
  validated on the NES against the exact crossing: 100% within 24 frames (0.4 s).
- The SNES pad maps B to jump and Y to run. `L` and `R` are recorded as `Action/Other`
  with the raw button preserved.
"""
