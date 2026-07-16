#!/usr/bin/env python
"""
Generate annotated event files for the Mario Stars dataset from replay variables.

This script reads game variables from replay processing and generates detailed
BIDS-compatible event files containing:
  - Button press events (UP, DOWN, LEFT, RIGHT, A, B, L, R, X, Y, START, SELECT)
  - Kill events (stomp, impact) via sprite_state_* transitions
  - Hit events (powerup_lost, life_lost, fall, timeout) via player_action_state
  - Brick smashing events via score increment of 50
  - Coin collection events via coins variable
  - Powerup collection events (mushroom, fire_flower, star)

Usage:
    python generate_annotations.py

    Or with explicit paths:
    python generate_annotations.py --datapath /path/to/mariostars

Note: Requires replay files (_variables.json) in gamelogs/ folders.
      Run create_replays.py first if they don't exist.

Kill Detection:
  Kill events are detected via sprite_state_0 through sprite_state_7 transitions:
  - State transition TO 4: stomp (jumped on enemy)
  - State transition TO 34: impact (shell, fireball, or star mode kill)

Hit Detection:
  Hit events are detected via player_action_state transitions:
  - State transition TO 10: powerup_lost (Big Mario shrinks)
  - State transition TO 11: life_lost (small Mario hit) or timeout (if timer=000)
  - Lives decrease without state change in last 5s: fall (fell into pit)
    Note: Falls are timestamped 5 seconds earlier than when lives decrease,
    because the lives variable updates several seconds after the actual fall.

Powerup Detection:
  Powerup events are detected via player_action_state transitions:
  - Transition 8 → 9: mushroom (small to big Mario)
  - Transition 8 → 12: fire_flower (big Mario to fire Mario)
  - star_power_timer goes from 0 to >0: star collected

Brick Smashing Detection:
  Brick smashing is detected via score increment of exactly 50 points.
"""

import argparse
import os
import os.path as op
import stable_retro
import pandas as pd
import numpy as np
import json


def create_runevents(runvars, run_id, events_dataframe, FS=60):
    """Create a BIDS compatible events dataframe from game variables and start/duration info of repetitions

    Parameters
    ----------
    runvars : list
        A list of repvars dicts, corresponding to the different repetitions of a run. Each repvar must have it's own duration and onset.
    events_dataframe : pandas.DataFrame
        A BIDS-formatted DataFrame specifying the onset and duration of each repetition.
    FS : int
        The sampling rate of the .bk2 file

    Returns
    -------
    events_df :
        An events DataFrame in BIDS-compatible format.
    """
    all_df = [events_dataframe]
    for idx, repvars in enumerate(runvars):
        n_frames_total = len(repvars["START"])
        repvars["rep_onset"] = [events_dataframe["onset"][idx]]
        repvars["rep_duration"] = n_frames_total / FS

        if len(repvars.keys()) > 0:  # Check if repetition logs are available
            # Actions - button inputs are always available from replay file
            # SNES has: D-pad (UP, DOWN, LEFT, RIGHT), Face buttons (A, B, X, Y),
            # Shoulder buttons (L, R), and START/SELECT
            ACTIONS = ["UP", "DOWN", "LEFT", "RIGHT", "A", "B", "X", "Y", "START", "SELECT"] # ["L", "R"]
            for act in ACTIONS:
                temp_df = generate_key_events(repvars, act, FS=FS)
                temp_df["onset"] = temp_df["onset"] + repvars["rep_onset"]
                all_df.append(temp_df)

            # Kills
            temp_df = generate_kill_events(repvars, FS=FS)
            temp_df["onset"] = temp_df["onset"] + repvars["rep_onset"]
            all_df.append(temp_df)

            # Hits taken
            temp_df = generate_hits_taken_events(repvars, FS=FS)
            temp_df["onset"] = temp_df["onset"] + repvars["rep_onset"]
            all_df.append(temp_df)

            # Bricks smashed
            temp_df = generate_bricks_smashed_events(repvars, FS=FS)
            temp_df["onset"] = temp_df["onset"] + repvars["rep_onset"]
            all_df.append(temp_df)

            # Coins collected
            temp_df = generate_coin_events(repvars, FS=FS)
            temp_df["onset"] = temp_df["onset"] + repvars["rep_onset"]
            all_df.append(temp_df)

            # Powerups
            temp_df = generate_powerup_events(repvars, FS=FS)
            temp_df["onset"] = temp_df["onset"] + repvars["rep_onset"]
            all_df.append(temp_df)

            # Star power (duration event)
            temp_df = generate_star_events(repvars, FS=FS)
            if not temp_df.empty:
                temp_df["onset"] = temp_df["onset"] + repvars["rep_onset"]
                all_df.append(temp_df)

            # Level complete
            temp_df = generate_level_complete_events(repvars, FS=FS)
            if not temp_df.empty:
                temp_df["onset"] = temp_df["onset"] + repvars["rep_onset"]
                all_df.append(temp_df)

            # Warp (warp-zone pipe exit, e.g. W1-2 / W4-2)
            temp_df = generate_warp_events(repvars, FS=FS)
            if not temp_df.empty:
                temp_df["onset"] = temp_df["onset"] + repvars["rep_onset"]
                all_df.append(temp_df)

    try:
        events_df = pd.concat(all_df).sort_values(by="onset").reset_index(drop=True)

        # Round onset and duration to 3 decimal places
        events_df['onset'] = events_df['onset'].round(3)
        events_df['duration'] = events_df['duration'].round(3)

        # Ensure integer types for frame columns and rep_index
        for col in ['frame_start', 'frame_stop', 'IndexInRun', 'IndexGlobal', 'IndexLevel']:
            if col in events_df.columns:
                events_df[col] = events_df[col].astype('Int64')  # nullable integer

        # Reorder columns: trial_type, level, onset, duration, frame_start, frame_stop, phase, IndexInRun, IndexGlobal, IndexLevel, stim_file
        cols = events_df.columns.tolist()
        priority_cols = ['trial_type', 'level', 'onset', 'duration', 'frame_start', 'frame_stop', 'phase', 'IndexInRun', 'IndexGlobal', 'IndexLevel', 'stim_file']
        priority_cols = [c for c in priority_cols if c in cols]  # only include existing columns
        other_cols = [c for c in cols if c not in priority_cols]
        events_df = events_df[priority_cols + other_cols]

    except ValueError:
        print("No bk2 files available for this run. Returning empty df.")
        events_df = pd.DataFrame()
    return events_df


def generate_key_events(repvars, key, FS=60):
    """Create a BIDS compatible events dataframe containing key (actions) events

    Parameters
    ----------
    repvars : list
        A dict containing all the variables of a single repetition
    key : string
        Name of the action variable to process
    FS : int
        The sampling rate of the .bk2 file

    Returns
    -------
    events_df :
        An events DataFrame in BIDS-compatible format containing the
        corresponding action events.
    """

    var = np.multiply(repvars[key], 1)
    # always keep the first and last value as 0 so diff will register the state transition
    var[0] = 0
    var[-1] = 0

    var_bin = [int(val) for val in var]
    diffs = list(np.diff(var_bin, n=1))
    presses = [round(i / FS, 3) for i, x in enumerate(diffs) if x == 1]
    releases = [round(i / FS, 3) for i, x in enumerate(diffs) if x == -1]
    frame_start = [i for i, x in enumerate(diffs) if x == 1]
    frame_stop = [i for i, x in enumerate(diffs) if x == -1]
    onset = presses
    level = [repvars["level"] for x in onset]
    duration = [round(releases[i] - presses[i], 3) for i in range(len(presses))]

    
    event_name = key
    if key == "Y":
        event_name = "RUN/THROW"
    elif key == "B":
        event_name = "JUMP"
        
    trial_type = ["{}".format(event_name) for i in range(len(presses))]
    events_df = pd.DataFrame(
        data={
            "onset": onset,
            "duration": duration,
            "trial_type": trial_type,
            "level": level,
            "frame_start": frame_start,
            "frame_stop": frame_stop,
        }
    )
    return events_df


def generate_kill_events(repvars, FS=60):
    """Create a BIDS compatible events dataframe containing kill events.

    Super Mario All-Stars (SMB1) uses sprite_state_0 through sprite_state_7 to
    track enemy states. Kill events are detected by state transitions:
    - transition TO 4: stomp (jumping on enemy)
    - transition TO 34: impact (shell, fireball, or star mode kill)

    The detection is based on state TRANSITIONS (previous != 4/34, current == 4/34)
    because these death state values persist for several frames.

    Parameters
    ----------
    repvars : dict
        A dict containing all the variables of a single repetition.
    FS : int
        The sampling rate of the .bk2 file (default: 60)

    Returns
    -------
    events_df :
        An events DataFrame in BIDS-compatible format containing the
        kill events.
    """
    onset = []
    duration = []
    trial_type = []
    level = []
    frame_start = []
    frame_stop = []

    # Kill values based on sprite_state transitions
    # 4: stomp (jumped on enemy)
    # 34: impact (killed by shell, fireball, or star mode)
    killvals_dict = {4: "stomp", 34: "impact"}

    n_frames_total = len(repvars["START"])

    # Super Mario All-Stars SMB1 has 8 sprite slots (sprite_state_0 through sprite_state_7)
    for frame_idx in range(1, n_frames_total):  # Start at 1 to have a previous frame
        for slot_idx in range(8):
            sprite_state_var = f"sprite_state_{slot_idx}"

            # Check if this variable exists in repvars
            if sprite_state_var not in repvars:
                continue

            prev_val = repvars[sprite_state_var][frame_idx - 1]
            curr_val = repvars[sprite_state_var][frame_idx]

            # Detect transition TO a kill state (prev != kill_state AND curr == kill_state)
            for kill_val, kill_type in killvals_dict.items():
                if prev_val != kill_val and curr_val == kill_val:
                    killstring = f"Kill/{kill_type}"
                    onset.append(frame_idx / FS)
                    duration.append(0)  # Instantaneous event
                    trial_type.append(killstring)
                    level.append(repvars["level"])
                    frame_start.append(frame_idx)
                    frame_stop.append(frame_idx)

    events_df = pd.DataFrame(
        data={
            "onset": onset,
            "duration": duration,
            "trial_type": trial_type,
            "level": level,
            "frame_start": frame_start,
            "frame_stop": frame_stop,
        }
    )
    return events_df


def generate_hits_taken_events(repvars, FS=60):
    """Generate events for when Mario takes damage or loses a life.

    Super Mario All-Stars (SMB1) uses player_action_state to track hit states:
    - State 10: Big Mario shrinks (powerup lost, but not life lost)
    - State 11: Mario dies (small Mario hit OR timeout - need to differentiate)

    Hit types detected:
    - Hit/powerup_lost: player_action_state transitions TO 10
    - Hit/killed: player_action_state transitions TO 11 AND timer > 0
                  (excludes timeout deaths by checking timer)
    - Hit/timeout: player_action_state transitions TO 11 AND timer == 0
    - Hit/fall: lives decrease without hit event in previous 5 seconds
    
    Note on Hit/fall detection:
    When Mario is killed by an enemy (Hit/killed), the lives variable decreases
    several seconds AFTER the death event (after the death animation plays).
    To avoid false Hit/fall events:
    - When lives decrease, look back 5 seconds for any Hit/killed, Hit/timeout, 
      or Hit/powerup_lost event
    - If found: don't register a fall (it's the delayed lives decrease from that hit)
    - If not found: register a genuine fall, but with onset 5 seconds earlier
      (because the actual fall happened ~5 seconds before lives decreased)

    Parameters
    ----------
    repvars : dict
        Dictionary containing all the variables of a single repetition
    FS : int
        The sampling rate of the .bk2 file (default: 60)

    Returns
    -------
    events_df : pandas.DataFrame
        Events DataFrame in BIDS-compatible format
    """
    onset = []
    duration = []
    trial_type = []
    level = []
    frame_start = []
    frame_stop = []

    n_frames_total = len(repvars["START"])

    # Check if required variables exist
    has_action_state = "player_action_state" in repvars
    has_lives = "lives" in repvars

    # Track frames where we detected a hit via action_state (to avoid double-counting)
    hit_frames = set()

    if has_action_state:
        # Powerup lost: transition TO state 10 (Big Mario shrinks)
        for frame_idx in range(1, n_frames_total):
            prev_state = repvars["player_action_state"][frame_idx - 1]
            curr_state = repvars["player_action_state"][frame_idx]

            if prev_state != 10 and curr_state == 10:
                onset.append(frame_idx / FS)
                duration.append(0)  # Instantaneous event
                trial_type.append("Hit/powerup_lost")
                level.append(repvars["level"])
                frame_start.append(frame_idx)
                frame_stop.append(frame_idx)
                hit_frames.add(frame_idx)

        # Life lost by hit: transition TO state 11 AND lives decrease
        # Need to check that timer didn't run out (timeout death)
        for frame_idx in range(1, n_frames_total):
            prev_state = repvars["player_action_state"][frame_idx - 1]
            curr_state = repvars["player_action_state"][frame_idx]

            if prev_state != 11 and curr_state == 11:
                # Check if this is a timeout death by checking if timer is at 0
                is_timeout = False
                #if "level_timer_hundreds" in repvars and "level_timer_tens" in repvars and "level_timer_ones" in repvars:
                timer_h = repvars["time_hundreds"][frame_idx]
                timer_t = repvars["time_tens"][frame_idx]
                timer_o = repvars["time_units"][frame_idx]
                # Timer at 000 means timeout
                if timer_h == 0 and timer_t == 0 and timer_o == 0:
                    is_timeout = True

                if not is_timeout:
                    # This is a genuine hit death (small Mario hit by enemy)
                    onset.append(frame_idx / FS)
                    duration.append(0)  # Instantaneous event
                    trial_type.append("Hit/killed")
                    level.append(repvars["level"])
                    frame_start.append(frame_idx)
                    frame_stop.append(frame_idx)
                    hit_frames.add(frame_idx)
                else:
                    # Timeout death
                    onset.append(frame_idx / FS)
                    duration.append(0)
                    trial_type.append("Hit/timeout")
                    level.append(repvars["level"])
                    frame_start.append(frame_idx)
                    frame_stop.append(frame_idx)
                    hit_frames.add(frame_idx)

    # Fall deaths: lives decrease without a corresponding action_state hit
    # This catches deaths from falling into pits
    # 
    # IMPORTANT: When Mario is killed by an enemy, the lives variable decreases
    # several seconds AFTER the Hit/killed event (after the death animation).
    # This can cause false Hit/fall events. To fix this:
    # - Look back 5 seconds (300 frames) for a Hit/killed event
    # - If Hit/killed found: don't register the fall (it's a false positive)
    # - If no Hit/killed: register the fall, but with onset 5 seconds earlier
    #   (because the actual fall happened ~5 seconds before lives decreased)
    LOOKBACK_SECONDS = 5
    LOOKBACK_FRAMES = int(LOOKBACK_SECONDS * FS)  # 300 frames at 60fps
    
    if has_lives:
        for frame_idx in range(1, n_frames_total):
            prev_lives = repvars["lives"][frame_idx - 1]
            curr_lives = repvars["lives"][frame_idx]

            if curr_lives < prev_lives:
                # Check if there's a Hit/killed in the previous 5 seconds
                # hit_frames contains frames where Hit/killed, Hit/powerup_lost, 
                # or Hit/timeout was detected
                has_killed_in_lookback = any(
                    (frame_idx - LOOKBACK_FRAMES) <= hf <= frame_idx 
                    for hf in hit_frames
                )

                if not has_killed_in_lookback:
                    # This is a genuine fall death
                    # Adjust onset to 5 seconds earlier (when the fall actually happened)
                    adjusted_frame = max(0, frame_idx - LOOKBACK_FRAMES)
                    onset.append(adjusted_frame / FS)
                    duration.append(0)
                    trial_type.append("Hit/fall")
                    level.append(repvars["level"])
                    frame_start.append(adjusted_frame)
                    frame_stop.append(adjusted_frame)
                # If has_killed_in_lookback is True, we skip registering the fall
                # because it's a false positive from the lives decrease after enemy kill

    events_df = pd.DataFrame(
        data={
            "onset": onset,
            "duration": duration,
            "trial_type": trial_type,
            "level": level,
            "frame_start": frame_start,
            "frame_stop": frame_stop,
        }
    )
    return events_df


def generate_bricks_smashed_events(repvars, FS=60):
    """Generate events for when Mario smashes bricks.

    Super Mario All-Stars (SMB1) brick smashing is detected by a score
    increment of exactly 50 points.

    Parameters
    ----------
    repvars : dict
        Dictionary containing all the variables of a single repetition
    FS : int
        The sampling rate of the .bk2 file (default: 60)

    Returns
    -------
    events_df : pandas.DataFrame
        Events DataFrame in BIDS-compatible format
    """
    onset = []
    duration = []
    trial_type = []
    level = []
    frame_start = []
    frame_stop = []

    # Find flag hit frame
    # After flag hit, 50-point score increments are time-to-score conversion, not bricks
    flag_frame = None
    player_states = repvars.get("player_action_state", [])
    for i, state in enumerate(player_states):
        if state == 4:
            flag_frame = i
            break

    # Check if score variable exists
    if "score" in repvars:
        score_increments = list(np.diff(repvars["score"]))
        for frame_idx, inc in enumerate(score_increments):
            # Skip frames after flag hit (those are time-to-score conversions)
            if flag_frame is not None and frame_idx >= flag_frame:
                continue
            
            # Brick smashing gives 50 points in Super Mario All-Stars
            if inc == 50:
                onset.append((frame_idx + 1) / FS)  # +1 because diff shifts by 1
                duration.append(0)  # Instantaneous event
                trial_type.append("Brick_smashed")
                level.append(repvars["level"])
                frame_start.append(frame_idx + 1)
                frame_stop.append(frame_idx + 1)

    events_df = pd.DataFrame(
        data={
            "onset": onset,
            "duration": duration,
            "trial_type": trial_type,
            "level": level,
            "frame_start": frame_start,
            "frame_stop": frame_stop,
        }
    )
    return events_df


def generate_coin_events(repvars, FS=60):
    """Generate events for coin collection.

    Detected by increase in coins counter.

    Parameters
    ----------
    repvars : dict
        Dictionary containing all the variables of a single repetition
    FS : int
        The sampling rate of the .bk2 file

    Returns
    -------
    events_df : pandas.DataFrame
        Events DataFrame in BIDS-compatible format
    """
    onset = []
    duration = []
    trial_type = []
    level = []
    frame_start = []
    frame_stop = []

    diff_coins = np.diff(repvars["coins"])
    for idx_val, val in enumerate(diff_coins):
        if val > 0:
            onset.append(idx_val / FS)
            duration.append(0)
            trial_type.append("Coin_collected")
            level.append(repvars["level"])
            frame_start.append(idx_val)
            frame_stop.append(idx_val)

    events_df = pd.DataFrame(
        data={
            "onset": onset,
            "duration": duration,
            "trial_type": trial_type,
            "level": level,
            "frame_start": frame_start,
            "frame_stop": frame_stop,
        }
    )
    return events_df


def generate_powerup_events(repvars, FS=60):
    """Generate events for powerup collection.

    Super Mario All-Stars (SMB1) uses player_action_state transitions to detect powerups:
    - Transition 8 → 9: Mushroom collected (small Mario grows to big Mario)
    - Transition 8 → 12: Fire Flower collected (big Mario gets fire power)

    Both are reported as Powerup_collected for consistency with other games.

    Parameters
    ----------
    repvars : dict
        Dictionary containing all the variables of a single repetition
    FS : int
        The sampling rate of the .bk2 file (default: 60)

    Returns
    -------
    events_df : pandas.DataFrame
        Events DataFrame in BIDS-compatible format
    """
    onset = []
    duration = []
    trial_type = []
    level = []
    frame_start = []
    frame_stop = []

    n_frames_total = len(repvars["START"])

    # Check if player_action_state exists
    if "player_action_state" in repvars:
        for frame_idx in range(1, n_frames_total):
            prev_state = repvars["player_action_state"][frame_idx - 1]
            curr_state = repvars["player_action_state"][frame_idx]

            # Mushroom: transition from 8 to 9 (small to big)
            if prev_state == 8 and curr_state == 9:
                onset.append(frame_idx / FS)
                duration.append(0)  # Instantaneous event
                trial_type.append("Powerup_collected")
                level.append(repvars["level"])
                frame_start.append(frame_idx)
                frame_stop.append(frame_idx)

            # Fire Flower: transition from 8 to 12 (big to fire)
            elif prev_state == 8 and curr_state == 12:
                onset.append(frame_idx / FS)
                duration.append(0)  # Instantaneous event
                trial_type.append("Powerup_collected")
                level.append(repvars["level"])
                frame_start.append(frame_idx)
                frame_stop.append(frame_idx)

    events_df = pd.DataFrame(
        data={
            "onset": onset,
            "duration": duration,
            "trial_type": trial_type,
            "level": level,
            "frame_start": frame_start,
            "frame_stop": frame_stop,
        }
    )
    return events_df


def generate_star_events(repvars, FS=60):
    """Generate events for star power activation.

    Detected by star_power_timer going from 0 to >0.
    This is a duration event that tracks the entire period of invincibility.

    Parameters
    ----------
    repvars : dict
        Dictionary containing all the variables of a single repetition
    FS : int
        The sampling rate of the .bk2 file (default: 60)

    Returns
    -------
    events_df : pandas.DataFrame
        Events DataFrame in BIDS-compatible format
    """
    onset = []
    duration = []
    trial_type = []
    level = []
    frame_start = []
    frame_stop = []

    if "star_power_timer" not in repvars:
        return pd.DataFrame(
            data={
                "onset": onset,
                "duration": duration,
                "trial_type": trial_type,
                "level": level,
                "frame_start": frame_start,
                "frame_stop": frame_stop,
            }
        )

    timer = repvars["star_power_timer"]

    # Detect contiguous blocks where timer > 0
    in_event = False
    event_start_idx = 0

    for idx in range(len(timer)):
        val = timer[idx]

        if val > 0 and not in_event:
            # Event started
            in_event = True
            event_start_idx = idx

        elif val == 0 and in_event:
            # Event ended
            in_event = False
            onset.append(event_start_idx / FS)
            dur = (idx - event_start_idx) / FS
            duration.append(dur)
            trial_type.append("Star_activated")
            level.append(repvars["level"])
            frame_start.append(event_start_idx)
            frame_stop.append(idx)

    # Handle case where event goes until end of replay
    if in_event:
        idx = len(timer)
        onset.append(event_start_idx / FS)
        dur = (idx - event_start_idx) / FS
        duration.append(dur)
        trial_type.append("Star_activated")
        level.append(repvars["level"])
        frame_start.append(event_start_idx)
        frame_stop.append(idx)

    events_df = pd.DataFrame(
        data={
            "onset": onset,
            "duration": duration,
            "trial_type": trial_type,
            "level": level,
            "frame_start": frame_start,
            "frame_stop": frame_stop,
        }
    )
    return events_df


def generate_level_complete_events(repvars, FS=60):
    """Generate events for level completion.

    Super Mario All-Stars (SMB1) level completion is detected when
    player_action_state becomes 4 (sliding down the flagpole).

    Parameters
    ----------
    repvars : dict
        Dictionary containing all the variables of a single repetition
    FS : int
        The sampling rate of the .bk2 file (default: 60)

    Returns
    -------
    events_df : pandas.DataFrame
        Events DataFrame in BIDS-compatible format
    """
    onset = []
    duration = []
    trial_type = []
    level = []
    frame_start = []
    frame_stop = []

    if "player_action_state" not in repvars:
        return pd.DataFrame(
            data={
                "onset": onset,
                "duration": duration,
                "trial_type": trial_type,
                "level": level,
                "frame_start": frame_start,
                "frame_stop": frame_stop,
            }
        )

    player_states = repvars["player_action_state"]

    # Detect first frame where player_action_state is 4 (flagpole slide)
    for idx in range(len(player_states)):
        if player_states[idx] == 4:
            onset.append(idx / FS)
            duration.append(0)
            trial_type.append("Level_complete")
            level.append(repvars["level"])
            frame_start.append(idx)
            frame_stop.append(idx)
            break  # Only one level complete event per repetition

    events_df = pd.DataFrame(
        data={
            "onset": onset,
            "duration": duration,
            "trial_type": trial_type,
            "level": level,
            "frame_start": frame_start,
            "frame_stop": frame_stop,
        }
    )
    return events_df


def generate_warp_events(repvars, FS=60):
    """Generate a Warp event for warp-zone pipe exits (e.g. W1-2 / W4-2).

    Emitted once, at the transport frame (where current_world or current_level
    changes), for repetitions whose summary Outcome is 'incomplete/warp' (the
    single source of truth, computed by generate_replays._determine_outcome).
    Gating on the Outcome guarantees Warp events correspond 1:1 to those reps.
    """
    onset = []
    duration = []
    trial_type = []
    level = []
    frame_start = []
    frame_stop = []
    empty = pd.DataFrame(
        data={
            "onset": onset,
            "duration": duration,
            "trial_type": trial_type,
            "level": level,
            "frame_start": frame_start,
            "frame_stop": frame_stop,
        }
    )

    if repvars.get("Outcome") != "incomplete/warp":
        return empty

    cur_world = repvars.get("current_world", [])
    cur_level = repvars.get("current_level", [])
    if not (isinstance(cur_world, list) or isinstance(cur_level, list)):
        return empty

    # Detect the transport frame (current_world or current_level changes).
    n = max(len(cur_world) if isinstance(cur_world, list) else 0,
            len(cur_level) if isinstance(cur_level, list) else 0)
    for idx in range(1, n):
        w_changed = (isinstance(cur_world, list) and idx < len(cur_world)
                     and cur_world[idx] != cur_world[idx - 1])
        l_changed = (isinstance(cur_level, list) and idx < len(cur_level)
                     and cur_level[idx] != cur_level[idx - 1])
        if w_changed or l_changed:
            onset.append(idx / FS)
            duration.append(0)
            trial_type.append("Warp")
            level.append(repvars["level"])
            frame_start.append(idx)
            frame_stop.append(idx)
            break  # Only one warp event per repetition

    return pd.DataFrame(
        data={
            "onset": onset,
            "duration": duration,
            "trial_type": trial_type,
            "level": level,
            "frame_start": frame_start,
            "frame_stop": frame_stop,
        }
    )


def main(args):
    FS = 60

    # Get datapath
    DATA_PATH = args.datapath
    if DATA_PATH == ".":
        print("No data path specified. Searching files in this folder.")
    print(f"Generating annotations for the mariostars dataset in : {DATA_PATH}")
    # Import stimuli
    stimuli_path = op.join(DATA_PATH, "stimuli")
    stable_retro.data.Integrations.add_custom_path(stimuli_path)

    OUTPUT_PATH = args.output_path

    # Get subject/session filters
    subjects = args.subjects
    sessions = args.sessions

    if subjects:
        print(f"Filtering subjects: {', '.join(subjects)}")
    if sessions:
        print(f"Filtering sessions: {', '.join(sessions)}")

    # Walk through all folders looking for events.tsv files
    for root, folder, files in sorted(os.walk(DATA_PATH)):
        if not "sourcedata" in root:
            # Check if this path matches subject filter
            if subjects is not None:
                if not any(sub in root for sub in subjects):
                    continue

            # Check if this path matches session filter
            if sessions is not None:
                if not any(ses in root for ses in sessions):
                    continue

            for file in files:
                if "events.tsv" in file and not "annotated" in file:
                    run_events_file = op.join(root, file)
                    run_id = file.split("_")[3]
                    if OUTPUT_PATH is not None:
                        sub = file.split("_")[0]
                        ses = file.split("_")[1]
                        events_annotated_fname = op.join(
                            OUTPUT_PATH,
                            sub,
                            ses,
                            "func",
                            file.replace("_events.", "_desc-annotated_events."),
                        )
                        os.makedirs(op.dirname(events_annotated_fname), exist_ok=True)
                    else:
                        events_annotated_fname = run_events_file.replace(
                            "_events.", "_desc-annotated_events."
                        )
                    if not op.isfile(events_annotated_fname):
                        print(f"Processing : {file}")
                        events_dataframe = pd.read_table(run_events_file, index_col=0)
                        events_dataframe = events_dataframe[
                            events_dataframe["trial_type"] == "gym-retro_game"
                        ]  # select only repetition events
                        events_dataframe = events_dataframe[
                            ["trial_type", "onset", "level", "stim_file"]
                        ].reset_index(drop=True)  # select only relevant columns
                        bk2_files = events_dataframe["stim_file"].values.tolist()
                        runvars = []
                        for bk2_idx, bk2_file in enumerate(bk2_files):
                            if bk2_file != "Missing file" and type(bk2_file) != float:
                                print("Adding : " + bk2_file)
                                sub = bk2_file.split("/")[0]
                                ses = bk2_file.split("/")[1]
                                filename = bk2_file.split("/")[-1]
                                # Look for variables file in gamelogs/ within datapath
                                variables_sidecar_fname = op.join(
                                    DATA_PATH,
                                    sub,
                                    ses,
                                    "gamelogs",
                                    filename.replace(".bk2", "_variables.json"),
                                )
                                if op.exists(variables_sidecar_fname):
                                    with open(variables_sidecar_fname, "r") as f:
                                        repvars = json.load(f)

                                    # Load summary sidecar for repetition indices
                                    summary_fname = variables_sidecar_fname.replace("_variables.json", "_summary.json")
                                    if op.exists(summary_fname):
                                        with open(summary_fname, "r") as f:
                                            summary = json.load(f)
                                        # Make the outcome available to event
                                        # generators (e.g. Warp) as the single
                                        # source of truth for the rep's ending.
                                        repvars["Outcome"] = summary.get("Outcome")
                                        events_dataframe.loc[events_dataframe["stim_file"] == bk2_file, "IndexInRun"] = summary["IndexInRun"]
                                        events_dataframe.loc[events_dataframe["stim_file"] == bk2_file, "IndexGlobal"] = summary["IndexGlobal"]
                                        events_dataframe.loc[events_dataframe["stim_file"] == bk2_file, "IndexLevel"] = summary["IndexLevel"]

                                    # Add info to repetition event
                                    events_dataframe.loc[
                                        events_dataframe["stim_file"] == bk2_file,
                                        "level",
                                    ] = repvars[
                                        "level"
                                    ]  # replace level value in the dataframe by the one in the repvars dict
                                    events_dataframe.loc[
                                        events_dataframe["stim_file"] == bk2_file,
                                        "frame_start",
                                    ] = int(0)
                                    events_dataframe.loc[
                                        events_dataframe["stim_file"] == bk2_file,
                                        "frame_stop",
                                    ] = int(len(repvars["score"]))
                                    events_dataframe.loc[
                                        events_dataframe["stim_file"] == bk2_file,
                                        "duration",
                                    ] = (
                                        int(len(repvars["score"])) / FS
                                    )

                                    runvars.append(repvars)
                                else:
                                    print(f"\nError: Variables file not found: {variables_sidecar_fname}")
                                    print("Please run create_replays.py first to generate the required files.")
                                    return
                            else:
                                print("Missing file, skipping")
                                runvars.append({})

                        # Mariostars is always practice phase
                        events_dataframe["phase"] = "practice"
                        events_df = create_runevents(
                            runvars, run_id, events_dataframe, FS=FS
                        )

                        events_df.to_csv(events_annotated_fname, sep="\t", index=False)
                        print(f"Saved annotated events to: {events_annotated_fname}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-d",
        "--datapath",
        default=".",
        type=str,
        help="Data path to look for events.tsv and .bk2 files. Should be the root of the mariostars dataset.",
    )

    parser.add_argument(
        "-o",
        "--output_path",
        default=None,
        type=str,
        help="Path to save the annotated events files. If not specified, saves in the same folder as the input events.tsv files.",
    )

    parser.add_argument(
        "--subjects",
        "-sub",
        nargs="+",
        default=None,
        help="List of subjects to process (e.g., sub-01 sub-02). If not specified, all subjects are processed.",
    )

    parser.add_argument(
        "--sessions",
        "-ses",
        nargs="+",
        default=None,
        help="List of sessions to process (e.g., ses-001 ses-002). If not specified, all sessions are processed.",
    )

    args = parser.parse_args()
    main(args)
