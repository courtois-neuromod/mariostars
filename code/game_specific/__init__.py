"""What :mod:`videogames_utils.events` needs to know about
Super Mario All-Stars: Super Mario Bros. (SNES).

See :class:`videogames_utils.events.game.Game`.
"""

import re

from videogames_utils.events.game import Game

from . import docs, generator, outcome, ram, validation
from .vocabulary import VOCABULARY


def level_from_events(level: str) -> str:
    """The events.tsv level in the annotated form: ``Level1-1`` -> ``w1l1``."""
    m = re.fullmatch(r"Level(\w+)-(\w+)", level)
    return f"w{m.group(1)}l{m.group(2)}" if m else level


GAME = Game(
    task="mariostars",
    name="Super Mario All-Stars: Super Mario Bros. (SNES)",
    game_id="SuperMarioAllStars-Snes",
    frame_rate=generator.FRAME_RATE,
    vocabulary=VOCABULARY,
    generate=generator.generate,
    outcome=outcome.outcome,
    level_from_events=level_from_events,
    form_states=frozenset({"PlayerState/Small", "PlayerState/Super",
                           "PlayerState/Fire"}),
    form_var="player_status",
    state_timers=(("star_timer", "PlayerState/Star"),
                  ("injury_timer", "PlayerState/HitRecovery")),
    coin_var="player_coins",
    check_repetition=validation.check_repetition,
    notes=docs.NOTES,
    not_emitted=docs.NOT_EMITTED,
    golden_sessions=[("sub-03", "ses-006")],
    ram_candidates=ram.SMAS_CANDIDATES,
    mislabelled=ram.MISLABELLED,
)
