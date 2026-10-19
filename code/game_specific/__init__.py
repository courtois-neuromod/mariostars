"""What :mod:`videogames_utils.events` needs to know about
Super Mario All-Stars: Super Mario Bros. (SNES).

See :class:`videogames_utils.events.game.Game`.
"""

from videogames_utils.events.game import Game

from . import docs, generator, outcome, ram, replays, validation
from .vocabulary import VOCABULARY


GAME = Game(
    task="mariostars",
    name="Super Mario All-Stars: Super Mario Bros. (SNES)",
    game_id="SuperMarioAllStars-Snes",
    frame_rate=generator.FRAME_RATE,
    vocabulary=VOCABULARY,
    generate=generator.generate,
    outcome=outcome.outcome,
    summary=replays.summary,
    phases=replays.phases,
    form_states=frozenset({"PlayerState/Small", "PlayerState/Super",
                           "PlayerState/Fire"}),
    form_var="player_status",
    state_timers=(("star_timer", "PlayerState/Star"),
                  ("injury_timer", "PlayerState/HitRecovery")),
    coin_var="player_coins",
    check_repetition=validation.check_repetition,
    reference=docs.REFERENCE,
    not_emitted=docs.NOT_EMITTED,
    golden_sessions=[("sub-03", "ses-006")],
    ram_candidates=ram.SMAS_CANDIDATES,
    mislabelled=ram.MISLABELLED,
)
