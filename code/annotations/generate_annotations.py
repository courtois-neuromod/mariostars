#!/usr/bin/env python
"""
Generate annotated event files for the Mario Stars dataset from replay variables.

This script reads game variables from replay processing and generates detailed
BIDS-compatible event files containing:
  - Button press events (UP, DOWN, LEFT, RIGHT, A, B, L, R, X, Y, START, SELECT) ✅ AVAILABLE
  - Kill events (stomp, impact) ✅ AVAILABLE via sprite_state_* transitions
  - Hit events (powerup_lost, life_lost, fall, timeout) ✅ AVAILABLE via player_action_state
  - Brick smashing events ✅ AVAILABLE via score increment of 50
  - Coin collection events ✅ AVAILABLE via coins variable
  - Powerup collection events (mushroom, fire_flower, star) ✅ AVAILABLE

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
  - Lives decrease without state change: fall (fell into pit)

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
        rep_index = events_dataframe['rep_index'].iloc[idx]

        if len(repvars.keys()) > 0:  # Check if repetition logs are available
            # Actions - button inputs are always available from replay file
            # SNES has: D-pad (UP, DOWN, LEFT, RIGHT), Face buttons (A, B, X, Y),
            # Shoulder buttons (L, R), and START/SELECT
            ACTIONS = ["UP", "DOWN", "LEFT", "RIGHT", "A", "B", "X", "Y", "L", "R", "START", "SELECT"]
            for act in ACTIONS:
                temp_df = generate_key_events(repvars, act, FS=FS)
                temp_df["onset"] = temp_df["onset"] + repvars["rep_onset"]
                temp_df["rep_index"] = rep_index
                all_df.append(temp_df)

            # Kills
            temp_df = generate_kill_events(repvars, FS=FS)
            temp_df["onset"] = temp_df["onset"] + repvars["rep_onset"]
            temp_df["rep_index"] = rep_index
            all_df.append(temp_df)

            # Hits taken
            temp_df = generate_hits_taken_events(repvars, FS=FS)
            temp_df["onset"] = temp_df["onset"] + repvars["rep_onset"]
            temp_df["rep_index"] = rep_index
            all_df.append(temp_df)

            # Bricks smashed
            temp_df = generate_bricks_smashed_events(repvars, FS=FS)
            temp_df["onset"] = temp_df["onset"] + repvars["rep_onset"]
            temp_df["rep_index"] = rep_index
            all_df.append(temp_df)

            # Coins collected
            temp_df = generate_coin_events(repvars, FS=FS)
            temp_df["onset"] = temp_df["onset"] + repvars["rep_onset"]
            temp_df["rep_index"] = rep_index
            all_df.append(temp_df)

            # Powerups
            temp_df = generate_powerup_events(repvars, FS=FS)
            temp_df["onset"] = temp_df["onset"] + repvars["rep_onset"]
            temp_df["rep_index"] = rep_index
            all_df.append(temp_df)

    try:
        events_df = pd.concat(all_df).sort_values(by="onset").reset_index(drop=True)

        # Round onset and duration to 3 decimal places
        events_df['onset'] = events_df['onset'].round(3)
        events_df['duration'] = events_df['duration'].round(3)

        # Ensure integer types for frame columns and rep_index
        for col in ['frame_start', 'frame_stop', 'rep_index']:
            if col in events_df.columns:
                events_df[col] = events_df[col].astype('Int64')  # nullable integer

        # Reorder columns: trial_type, rep_index, level, onset, duration, frame_start, frame_stop, phase
        cols = events_df.columns.tolist()
        priority_cols = ['trial_type', 'rep_index', 'level', 'onset', 'duration', 'frame_start', 'frame_stop', 'phase']
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
    trial_type = ["{}".format(key) for i in range(len(presses))]
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
    - Hit/life_lost: player_action_state transitions TO 11 AND lives decrease
                     (excludes timeout deaths by checking timer)
    - Hit/fall: lives decrease without state 10/11 transition (fell in pit)

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
                if "level_timer_hundreds" in repvars and "level_timer_tens" in repvars and "level_timer_ones" in repvars:
                    timer_h = repvars["level_timer_hundreds"][frame_idx]
                    timer_t = repvars["level_timer_tens"][frame_idx]
                    timer_o = repvars["level_timer_ones"][frame_idx]
                    # Timer at 000 means timeout
                    if timer_h == 0 and timer_t == 0 and timer_o == 0:
                        is_timeout = True

                if not is_timeout:
                    # This is a genuine hit death (small Mario hit by enemy)
                    onset.append(frame_idx / FS)
                    duration.append(0)  # Instantaneous event
                    trial_type.append("Hit/life_lost")
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
    if has_lives:
        for frame_idx in range(1, n_frames_total):
            prev_lives = repvars["lives"][frame_idx - 1]
            curr_lives = repvars["lives"][frame_idx]

            if curr_lives < prev_lives:
                # Check if we already recorded a hit at this frame (within a small window)
                # Look for hit events in a window around this frame
                window_size = 30  # Half second window at 60fps
                has_nearby_hit = any(
                    abs(frame_idx - hf) <= window_size for hf in hit_frames
                )

                if not has_nearby_hit:
                    # This is a fall death (no action_state transition detected)
                    onset.append(frame_idx / FS)
                    duration.append(0)
                    trial_type.append("Hit/fall")
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

    # Check if score variable exists
    if "score" in repvars:
        score_increments = list(np.diff(repvars["score"]))
        for frame_idx, inc in enumerate(score_increments):
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

    Note: Star collection could be detected via star_power_timer increasing from 0.

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
                trial_type.append("Powerup/mushroom")
                level.append(repvars["level"])
                frame_start.append(frame_idx)
                frame_stop.append(frame_idx)

            # Fire Flower: transition from 8 to 12 (big to fire)
            elif prev_state == 8 and curr_state == 12:
                onset.append(frame_idx / FS)
                duration.append(0)  # Instantaneous event
                trial_type.append("Powerup/fire_flower")
                level.append(repvars["level"])
                frame_start.append(frame_idx)
                frame_stop.append(frame_idx)

    # Star: detected via star_power_timer increasing from 0
    if "star_power_timer" in repvars:
        for frame_idx in range(1, n_frames_total):
            prev_timer = repvars["star_power_timer"][frame_idx - 1]
            curr_timer = repvars["star_power_timer"][frame_idx]

            # Star collected: timer goes from 0 to > 0
            if prev_timer == 0 and curr_timer > 0:
                onset.append(frame_idx / FS)
                duration.append(0)
                trial_type.append("Powerup/star")
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
                        ].reset_index()  # select only relevant columns
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

                                    # rename index column to rep_index
                                    events_dataframe.rename(
                                        columns={"index": "rep_index"}, inplace=True
                                    )

                                    runvars.append(repvars)
                                else:
                                    print(f"\nError: Variables file not found: {variables_sidecar_fname}")
                                    print("Please run create_replays.py first to generate the required files.")
                                    return
                            else:
                                print("Missing file, skipping")
                                runvars.append({})

                        # Add phase (discovery VS practice)
                        if (
                            events_dataframe["level"].values[0]
                            == events_dataframe["level"].values[1]
                        ):
                            phase = "discovery"
                        else:
                            phase = "practice"
                        events_dataframe["phase"] = phase
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
