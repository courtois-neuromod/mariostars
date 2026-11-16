"""The Super Mario All-Stars parts of the replay pipeline (:mod:`videogames_utils.replays`): the
game's own ``_summary.json`` fields and the protocol phase.

The counting functions are those of the former ``code/replays/generate_replays.py``.
"""

from __future__ import annotations

import numpy as np

from .generator import FRAME_RATE


def _find_flag_frame(repetition_variables):
    """Find the frame when flag was hit (player_action_state becomes 4).
    
    State 4 corresponds to sliding down the flagpole.
    Returns None if no flag hit was detected.
    """
    player_states = repetition_variables.get("player_action_state", [])
    for i, state in enumerate(player_states):
        if state == 4:
            return i
    return None


def _calculate_distance_traveled(repetition_variables):
    """Calculate total X distance traveled using scroll positions.
    
    Distance is calculated up to flag hit (if cleared) to avoid
    including the finish animation movement.
    """
    try:
        # Find the effective end frame (flag hit or last frame)
        flag_frame = _find_flag_frame(repetition_variables)
        end_idx = flag_frame if flag_frame is not None else -1
        
        # Use scroll_x_high and scroll_x_low if available
        if "scroll_x_high" in repetition_variables and "scroll_x_low" in repetition_variables:
            start_x = (repetition_variables["scroll_x_low"][0] +
                       (256 * repetition_variables["scroll_x_high"][0]))
            end_x = (repetition_variables["scroll_x_low"][end_idx] +
                     (256 * repetition_variables["scroll_x_high"][end_idx]))
            return end_x - start_x
        # Fallback to player position if scroll not available
        elif "player_x_low" in repetition_variables and "player_x_high" in repetition_variables:
            start_x = (repetition_variables["player_x_low"][0] +
                       (256 * repetition_variables["player_x_high"][0]))
            end_x = (repetition_variables["player_x_low"][end_idx] +
                     (256 * repetition_variables["player_x_high"][end_idx]))
            return end_x - start_x
    except (KeyError, IndexError):
        pass
    return None


def _count_kills_via_sprite_state(repetition_variables):
    """
    Count kills using sprite_state_* transitions.
    
    Kill states in Mario Stars:
    - State transition TO 4: stomp (jumped on enemy)
    - State transition TO 34: impact (shell, fireball, or star mode kill)
    """
    kill_count = 0
    n_frames = None
    
    # Determine frame count from any available variable
    for key in repetition_variables:
        if isinstance(repetition_variables[key], list) and len(repetition_variables[key]) > 0:
            n_frames = len(repetition_variables[key])
            break
    
    if n_frames is None or n_frames < 2:
        return None
    
    # Check all 8 sprite slots
    slots_found = 0
    for slot_idx in range(8):
        sprite_state_var = f"sprite_state_{slot_idx}"
        if sprite_state_var not in repetition_variables:
            continue
        
        slots_found += 1
        sprite_states = repetition_variables[sprite_state_var]
        
        for frame_idx in range(1, len(sprite_states)):
            prev_val = sprite_states[frame_idx - 1]
            curr_val = sprite_states[frame_idx]
            
            # Detect transition TO kill states
            if prev_val != 4 and curr_val == 4:  # Stomp
                kill_count += 1
            elif prev_val != 34 and curr_val == 34:  # Impact
                kill_count += 1
    
    return kill_count if slots_found > 0 else None


def count_kills(repetition_variables):
    """Count total enemies killed during replay."""
    return _count_kills_via_sprite_state(repetition_variables)


def count_powerups_collected(repetition_variables):
    """
    Count powerups collected using player_action_state transitions.
    
    Powerup collection states in Mario Stars:
    - Transition 8 → 9: Mushroom (small to big)
    - Transition 8 → 12: Fire Flower (big to fire)
    """
    try:
        if "player_action_state" not in repetition_variables:
            return None
        
        states = repetition_variables["player_action_state"]
        powerup_count = 0
        
        for idx in range(1, len(states)):
            prev_state = states[idx - 1]
            curr_state = states[idx]
            
            # Mushroom collection (state 8 -> 9)
            if prev_state == 8 and curr_state == 9:
                powerup_count += 1
            # Fire flower collection (state 8 -> 12)
            elif prev_state == 8 and curr_state == 12:
                powerup_count += 1
        
        return powerup_count
    except (KeyError, IndexError):
        return None


def count_star_power_activations(repetition_variables):
    """Count times star power was activated (star_timer goes from 0 to >0).

    Uses star_timer rather than star_power_timer, whose shipped SNES address holds
    unrelated bytes (see videogames_utils.events.generators.smb1).
    """
    try:
        if "star_timer" not in repetition_variables:
            return None
        
        timer = repetition_variables["star_timer"]
        activations = 0
        
        for idx in range(1, len(timer)):
            if timer[idx - 1] == 0 and timer[idx] > 0:
                activations += 1
        
        return activations
    except (KeyError, IndexError):
        return None


def _safe_get_first(variables, key):
    """Safely get first element of a variable, returns None if unavailable."""
    try:
        return variables[key][0]
    except (KeyError, IndexError):
        return None


def _safe_get_last(variables, key):
    """Safely get last element of a variable, returns None if unavailable."""
    try:
        return variables[key][-1]
    except (KeyError, IndexError):
        return None


def _safe_diff(variables, key):
    """Safely compute difference between first and last elements, returns None if unavailable."""
    first = _safe_get_first(variables, key)
    last = _safe_get_last(variables, key)
    if first is not None and last is not None:
        return last - first
    return None


def _get_final_timer(repetition_variables):
    """Get the timer value at completion (flag hit) as a combined integer (e.g., 285 for 2:85).
    
    Uses time_hundreds, time_tens, and time_units variables.
    Note: time_units is scaled by 1000, so divide by 1000 to get actual ones digit.
    
    The timer value is captured at the moment of flag hit (when coins_added_to_counter
    becomes non-zero), since the timer quickly counts down to 0 after level completion.
    If no flag hit is detected, returns the timer at the last frame.
    """
    try:
        time_h = repetition_variables.get("time_hundreds", [])
        time_t = repetition_variables.get("time_tens", [])
        time_u = repetition_variables.get("time_units", [])
        coins_added = repetition_variables.get("coins_added_to_counter", [])
        
        if not time_h or not time_t or not time_u:
            return None
        
        # Find the frame when flag was hit
        flag_frame = _find_flag_frame(repetition_variables)
        
        # Use flag frame if found, otherwise use last frame
        idx = flag_frame if flag_frame is not None else -1
        
        hundreds = time_h[idx]
        tens = time_t[idx]
        ones = time_u[idx] // 1000  # time_units is scaled by 1000
        
        return hundreds * 100 + tens * 10 + ones
    except:
        return None


def _get_final_powerup_state(repetition_variables):
    """
    Get the final powerup state as a human-readable string.
    
    player_status values:
    0 = Small, 1 = Big, 2 = Fire

    Uses player_status rather than player_powerup, whose shipped SNES address holds
    unrelated bytes (see videogames_utils.events.generators.smb1).
    """
    try:
        powerup = _safe_get_last(repetition_variables, "player_status")
        if powerup is not None:
            powerup_names = {0: "small", 1: "big", 2: "fire"}
            return powerup_names.get(powerup, f"unknown_{powerup}")
    except:
        pass
    return None

def _count(events, *trial_types) -> int:
    """Rows of the repetition's events with one of ``trial_types``."""
    return int(events["trial_type"].isin(trial_types).sum()) if len(events) else 0


def hits_taken(events) -> int:
    """Hits that cost a power-up or a life. A fall or a timeout is not a hit."""
    return _count(events, "PlayerDamaged", "PlayerDied/Enemy")


def bricks_smashed(events) -> int:
    """Bricks broken, as in the events (``BlockSmashed``)."""
    return _count(events, "BlockSmashed")


def summary(repvars: dict, events) -> dict:
    """The game's fields of a repetition's ``_summary.json``."""
    try:
        duration = len(repvars["score"]) / FRAME_RATE
    except KeyError:
        duration = None
    distance = _calculate_distance_traveled(repvars)
    flag_frame = _find_flag_frame(repvars)
    # Use gameplay duration (up to flag hit) for speed calculation
    gameplay_duration = (flag_frame + 1) / FRAME_RATE if flag_frame is not None else duration
    average_speed = None
    if distance is not None and gameplay_duration is not None and gameplay_duration > 0:
        average_speed = distance / gameplay_duration
    lives_start = _safe_get_first(repvars, "lives")
    lives_final = _safe_get_last(repvars, "lives")
    lives_lost = None
    if lives_start is not None and lives_final is not None:
        lives_lost = lives_start - lives_final
    return {
        "ScoreGained": _safe_diff(repvars, "score"),
        "LivesLost": lives_lost,
        "HitsTaken": hits_taken(events),
        "EnemiesDefeated": count_kills(repvars),
        "CoinsCollected": _safe_diff(repvars, "coins"),
        "PowerupsCollected": count_powerups_collected(repvars),
        "StarsCollected": count_star_power_activations(repvars),
        "BricksSmashed": bricks_smashed(events),
        "DistanceTraveled": distance,
        "AverageSpeed": round(average_speed, 2) if average_speed else None,
        "FinalTimer": _get_final_timer(repvars),
        "FinalForm": _get_final_powerup_state(repvars),
    }


def phases(repetitions):
    """Practice only: levels in pseudo-random order, one repetition each."""
    return np.full(len(repetitions), "practice", dtype=object)
