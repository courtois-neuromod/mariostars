#!/usr/bin/env python
"""
Generate replay outputs for the Mario Stars dataset.

By default, all files are generated:
  - JSON sidecar file with metadata
  - MP4 video file
  - Variables JSON file with game variables
  - Low-level features NPY file (luminance, optical flow, audio envelope)

Use the flags below to skip specific outputs:
  --skip_videos      : Skip generating video files (_recording.mp4).
  --skip_variables   : Skip generating variables files (_variables.json).
  --skip_lowlevel    : Skip generating low-level features (_lowlevel.npy).

Use the -v/--verbose flag to display verbose output.
"""

import argparse
import os
import os.path as op
import stable_retro
import pandas as pd
import json
import numpy as np
import gc
from joblib import Parallel, delayed
from tqdm_joblib import tqdm_joblib
from tqdm import tqdm
import logging
from videogames_utils.replay import get_variables_from_replay
from videogames_utils.video import make_mp4
from videogames_utils.psychophysics import (
    compute_luminance,
    compute_optical_flow,
    audio_envelope_per_frame,
)


# ============================================================================
# Mario Stars-specific utility functions (using data.json variables)
# ============================================================================

def _calculate_world_and_level(level_str):
    """Extract world and level numbers from level string."""
    # Mario Stars uses naming like "W1L1", "W2L3", etc.
    try:
        if level_str and len(level_str) >= 2:
            return level_str[1], level_str[-1]
    except:
        pass
    return None, None


def _find_flag_frame(repetition_variables):
    """Find the frame when flag was hit (coins_added_to_counter becomes non-zero).
    
    Returns None if no flag hit was detected.
    """
    coins_added = repetition_variables.get("coins_added_to_counter", [])
    for i, c in enumerate(coins_added):
        if c != 0:
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


def _determine_outcome(repetition_variables):
    """
    Determine how the replay ended: 'cleared' or 'failed/*'.
    
    Outcome values (consistent with mario3):
    - cleared: Flag hit AND lives >= 0 at end
    - failed/timeout: Timer reached 0
    - failed/fall: Death by falling in pit (detected via player_action_state)
    - failed/killed: Death by enemy or other cause
    - unknown: Could not determine outcome
    
    Uses coins_added_to_counter to detect flag hit (level cleared).
    Uses time_* variables for timeout detection (only when no flag hit).
    """
    try:
        # Get lives at end
        lives_end = repetition_variables["lives"][-1]
        
        # Check if flag was hit (level cleared) - coins_added_to_counter becomes non-zero
        coins_added = repetition_variables.get("coins_added_to_counter", [])
        flag_hit = any(c != 0 for c in coins_added)
        
        # Cleared only if flag was hit AND lives >= 0 at end
        if flag_hit and lives_end >= 0:
            return "cleared"
        
        # No flag hit - check if lives decreased (death occurred)
        lives_start = repetition_variables["lives"][0]
        
        if lives_end < lives_start:
            # Check if it was a timeout using time_* variables at last frame
            time_h = repetition_variables.get("time_hundreds", [])
            time_t = repetition_variables.get("time_tens", [])
            time_u = repetition_variables.get("time_units", [])
            
            if time_h and time_t and time_u:
                timer_h = time_h[-1]
                timer_t = time_t[-1]
                timer_o = time_u[-1] // 1000  # time_units is scaled by 1000
                if timer_h == 0 and timer_t == 0 and timer_o == 0:
                    return "failed/timeout"
            
            # Check for fall death vs killed:
            # State 11 = death animation (killed by enemy)
            # If life lost but state 11 never appears, it's a fall death (state stays at 8)
            player_states = repetition_variables.get("player_action_state", [])
            if 11 in player_states:
                return "failed/killed"
            else:
                return "failed/fall"
        
        # No flag hit but no death - unclear outcome
        return "unknown"
        
    except (KeyError, IndexError):
        return "unknown"


def _check_level_cleared(repetition_variables):
    """Determine if level was successfully cleared."""
    outcome = _determine_outcome(repetition_variables)
    if outcome == "unknown":
        return None
    return outcome == "cleared"


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


def count_bricks_smashed(repetition_variables):
    """
    Count bricks smashed. In Mario All-Stars (SMB1), brick breaking gives 50 points.
    
    Only counts score increments BEFORE flag hit, since the 50-point increments
    after flag hit are the time-to-score conversion during the finish animation.
    """
    try:
        score = repetition_variables["score"]
        flag_frame = _find_flag_frame(repetition_variables)
        
        # Only count increments before flag hit
        end_idx = flag_frame if flag_frame is not None else len(score)
        score_increments = list(np.diff(score[:end_idx]))
        
        # In Mario All-Stars (SMB1), brick breaking gives 50 points
        return sum(1 for inc in score_increments if inc == 50)
    except KeyError:
        return None


def _count_powerup_lost_hits(repetition_variables):
    """Count hits where Mario lost a powerup (transition to player_action_state 10)."""
    try:
        if "player_action_state" not in repetition_variables:
            return None
        
        states = repetition_variables["player_action_state"]
        hit_count = 0
        
        for idx in range(1, len(states)):
            if states[idx - 1] != 10 and states[idx] == 10:
                hit_count += 1
        
        return hit_count
    except (KeyError, IndexError):
        return None


def _count_life_losses(repetition_variables):
    """Count hits from life losses."""
    try:
        diff_lives = list(np.diff(repetition_variables["lives"]))
        return sum(1 for val in diff_lives if val < 0)
    except KeyError:
        return None


def count_hits_taken(repetition_variables):
    """Count total hits taken (powerup losses + deaths)."""
    powerup_hits = _count_powerup_lost_hits(repetition_variables)
    life_losses = _count_life_losses(repetition_variables)
    if powerup_hits is None and life_losses is None:
        return None
    return (powerup_hits or 0) + (life_losses or 0)


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
    """Count times star power was activated (star_power_timer goes from 0 to >0)."""
    try:
        if "star_power_timer" not in repetition_variables:
            return None
        
        timer = repetition_variables["star_power_timer"]
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
        
        # Find the frame when flag was hit (coins_added_to_counter becomes non-zero)
        flag_frame = None
        for i, c in enumerate(coins_added):
            if c != 0:
                flag_frame = i
                break
        
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
    
    player_powerup values:
    0 = Small, 1 = Big, 2 = Fire
    """
    try:
        powerup = _safe_get_last(repetition_variables, "player_powerup")
        if powerup is not None:
            powerup_names = {0: "small", 1: "big", 2: "fire"}
            return powerup_names.get(powerup, f"unknown_{powerup}")
    except:
        pass
    return None


def create_sidecar_dict(repetition_variables):
    """
    Create JSON sidecar metadata from replay variables.

    Extracts high-level statistics from frame-by-frame game data.
    Metrics that require unavailable variables are set to None.

    Args:
        repetition_variables: Dictionary with per-frame game variables

    Returns:
        Dictionary with comprehensive summary statistics for the replay
    """
    # Calculate duration based on score frames
    try:
        n_frames = len(repetition_variables["score"])
        duration = n_frames / 60
    except KeyError:
        n_frames = None
        duration = None

    # Calculate distance and speed (using flag frame for proper gameplay duration)
    distance = _calculate_distance_traveled(repetition_variables)
    flag_frame = _find_flag_frame(repetition_variables)
    
    # Use gameplay duration (up to flag hit) for speed calculation
    if flag_frame is not None:
        gameplay_duration = (flag_frame + 1) / 60  # +1 because frame is 0-indexed
    else:
        gameplay_duration = duration
    
    average_speed = None
    if distance is not None and gameplay_duration is not None and gameplay_duration > 0:
        average_speed = distance / gameplay_duration

    # Determine outcome
    outcome = _determine_outcome(repetition_variables)

    # Calculate lives lost
    lives_start = _safe_get_first(repetition_variables, "lives")
    lives_final = _safe_get_last(repetition_variables, "lives")
    lives_lost = None
    if lives_start is not None and lives_final is not None:
        lives_lost = lives_start - lives_final

    # Build comprehensive result dict
    result = {
        # === Timing ===
        "Duration_seconds": round(duration, 3) if duration else None,
        "Frame_count": n_frames,
        "Timer_final": _get_final_timer(repetition_variables),
        
        # === Outcome ===
        "Outcome": outcome,  # 'cleared', 'death', 'timeout', 'unknown'
        
        # === Score & Progression ===
        "Score": _safe_diff(repetition_variables, "score"),
        
        # === Movement ===
        "X_traveled": distance,
        "Average_speed": round(average_speed, 2) if average_speed else None,
        
        # === Lives ===
        "Lives_lost": lives_lost,
        
        # === Combat ===
        "Hits_taken": count_hits_taken(repetition_variables),
        "Enemies_killed": count_kills(repetition_variables),
        
        # === Items ===
        "Coins": _safe_diff(repetition_variables, "coins"),
        "Powerups_collected": count_powerups_collected(repetition_variables),
        "Stars_collected": count_star_power_activations(repetition_variables),
        "Bricks_smashed": count_bricks_smashed(repetition_variables),
        
        # === Player State ===
        "Player_form_final": _get_final_powerup_state(repetition_variables),
    }

    return result


# ============================================================================
# Main replay processing functions
# ============================================================================

def _extract_subject_from_bk2(bk2_file):
    """Extract subject ID from bk2 filename."""
    return bk2_file.split("/")[-1].split("_")[0]


def _extract_session_from_bk2(bk2_file):
    """Extract session ID from bk2 filename."""
    return bk2_file.split("/")[-1].split("_")[1]


def _extract_level_from_bk2(bk2_file):
    """Extract level ID from bk2 filename."""
    return bk2_file.split("/")[-1].split("_")[4].split("-")[1]


def get_passage_order(bk2_df):
    """
    Sort replays and assign global and level-specific indices.

    Indices are all 1-indexed:
    - idx_in_run: Position within the run (1, 2, 3, ...)
    - global_idx: Position across all replays for that subject (1, 2, 3, ...)
    - level_idx: Position across all replays of that level for that subject (1, 2, 3, ...)

    Args:
        bk2_df: DataFrame with replay data including 'bk2_file' column

    Returns:
        DataFrame with added subject, session, level, global_idx, and level_idx columns
    """
    bk2_df["subject"] = [
        _extract_subject_from_bk2(x) for x in bk2_df["bk2_file"].values
    ]
    bk2_df["session"] = [
        _extract_session_from_bk2(x) for x in bk2_df["bk2_file"].values
    ]
    bk2_df["level"] = [_extract_level_from_bk2(x) for x in bk2_df["bk2_file"].values]

    # Convert idx_in_run to 1-indexed (it comes from enumerate which is 0-indexed)
    bk2_df["idx_in_run"] = bk2_df["idx_in_run"] + 1

    # Sort by subject, session, run, idx_in_run and assign global index (1-indexed)
    bk2_df = bk2_df.sort_values(["subject", "session", "run", "idx_in_run"]).assign(
        global_idx=lambda x: x.groupby("subject").cumcount() + 1
    )
    
    # Sort by subject, level, session, run, idx_in_run and assign level index (1-indexed)
    bk2_df = bk2_df.sort_values(
        ["subject", "level", "session", "run", "idx_in_run"]
    ).assign(level_idx=lambda x: x.groupby(["subject", "level"]).cumcount() + 1)
    
    return bk2_df.sort_values(["subject", "global_idx"])


def _setup_stimuli_path(args, data_path):
    """Set up and register stimuli path with retro."""
    if args.stimuli is None:
        stimuli_path = op.abspath(op.join(data_path, "stimuli"))
    else:
        stimuli_path = op.abspath(args.stimuli)
    logging.debug(f"Adding stimuli path: {stimuli_path}")
    stable_retro.data.Integrations.add_custom_path(stimuli_path)


def _validate_bk2_file(bk2_file, bk2_path):
    """Check if bk2 file is valid and exists."""
    if bk2_file == "Missing file" or isinstance(bk2_path, float):
        return False
    if not op.exists(bk2_path):
        logging.error(f"File not found: {bk2_path}")
        return False
    return True


def _check_outputs_exist(paths, args):
    """
    Check which output files already exist.

    Returns:
        tuple: (all_exist, missing_outputs) where all_exist is bool and
               missing_outputs is list of output types that need to be generated
    """
    missing = []

    # JSON is always required
    if not op.exists(paths["json"]):
        missing.append("json")

    # Check optional outputs (if not skipped)
    if not args.skip_videos and not op.exists(paths["mp4"]):
        missing.append("mp4")
    if not args.skip_variables and not op.exists(paths["variables"]):
        missing.append("variables")
    if not args.skip_lowlevel and not op.exists(paths["lowlevel"]):
        missing.append("lowlevel")

    return len(missing) == 0, missing


def _build_output_paths(output_folder, bk2_file, subject, session):
    """Build all output file paths for replay processing using flat gamelogs/ structure."""
    entities = bk2_file.split("/")[-1].split(".")[0]
    gamelogs_folder = op.join(output_folder, subject, session, "gamelogs")

    return {
        "mp4": op.join(gamelogs_folder, f"{entities}_recording.mp4"),
        "json": op.join(gamelogs_folder, f"{entities}_summary.json"),
        "variables": op.join(gamelogs_folder, f"{entities}_variables.json"),
        "lowlevel": op.join(gamelogs_folder, f"{entities}_lowlevel.npy"),
        "entities": entities,
    }


def _save_optional_outputs(
    args,
    paths,
    replay_frames,
    repetition_variables,
    audio_track,
    audio_rate,
):
    """Save video, variables, and lowlevel files if not skipped."""
    if not args.skip_videos:
        os.makedirs(os.path.dirname(paths["mp4"]), exist_ok=True)
        make_mp4(replay_frames, paths["mp4"], audio=audio_track, sample_rate=audio_rate)
        logging.info(f"Video saved to: {paths['mp4']}")

    if not args.skip_variables:
        os.makedirs(os.path.dirname(paths["variables"]), exist_ok=True)
        with open(paths["variables"], "w") as f:
            json.dump(repetition_variables, f)
        logging.info(f"Variables saved to: {paths['variables']}")

    if not args.skip_lowlevel:
        os.makedirs(os.path.dirname(paths["lowlevel"]), exist_ok=True)
        # Compute psychophysical low-level features (luminance, optical flow, audio envelope)
        luminance = compute_luminance(replay_frames)
        optical_flow = compute_optical_flow(replay_frames)
        audio_envelope = audio_envelope_per_frame(
            audio_track,
            sample_rate=audio_rate,
            frame_rate=60.0,
            frame_count=len(replay_frames),
        )

        lowlevel_dict = {
            "luminance": luminance,
            "optical_flow": optical_flow,
            "audio_envelope": audio_envelope,
        }
        np.save(paths["lowlevel"], lowlevel_dict)
        logging.info(f"Low-level features saved to: {paths['lowlevel']}")


def _create_and_save_sidecar(repetition_variables, task_metadata, paths):
    """Create and save JSON sidecar with replay metadata."""
    info_dict = create_sidecar_dict(repetition_variables)
    info_dict.update(
        {
            "IndexInRun": task_metadata["idx_in_run"],
            "Run": task_metadata["run"],
            "IndexGlobal": task_metadata["global_idx"],  # Already 1-indexed
            "IndexLevel": task_metadata["level_idx"],  # Already 1-indexed
            "Phase": "practice",  # Always practice for mariostars
        }
    )

    os.makedirs(os.path.dirname(paths["json"]), exist_ok=True)
    with open(paths["json"], "w") as f:
        json.dump(info_dict, f)
    logging.info(f"JSON saved for: {paths['json']}")


def process_bk2_file(task, args):
    """
    Process a single .bk2 replay file.

    Extracts game data and creates JSON metadata sidecar.
    Optionally saves video, variables, and low-level features.

    Args:
        task: Tuple of (bk2_file, run, idx_in_run, phase, subject,
              session, level, global_idx, level_idx)
        args: Command-line arguments with processing options
    """
    game_name = "SuperMarioAllStars-Snes"
    data_path = op.abspath(args.datapath)
    output_folder = op.abspath(args.output)
    os.makedirs(output_folder, exist_ok=True)
    # Set up stimuli path in each worker process for parallel processing
    _setup_stimuli_path(args, data_path)

    bk2_file, run, idx_in_run, phase, subject, session, level, global_idx, level_idx = (
        task
    )
    bk2_path = op.abspath(op.join(data_path, bk2_file))

    if not _validate_bk2_file(bk2_file, bk2_path):
        return

    paths = _build_output_paths(output_folder, bk2_file, subject, session)

    # Check if all required outputs already exist - skip if so
    all_exist, missing_outputs = _check_outputs_exist(paths, args)
    if all_exist:
        logging.info(f"Skipping (all outputs exist): {paths['entities']}")
        return
    else:
        logging.info(
            f"Processing {paths['entities']} (missing: {', '.join(missing_outputs)})"
        )

    # Get replay data with audio
    repetition_variables, _, replay_frames, audio_track, audio_rate = (
        get_variables_from_replay(
            op.join(data_path, bk2_file),
            skip_first_step=(idx_in_run == 0),
            game=game_name,
            inttype=stable_retro.data.Integrations.CUSTOM_ONLY,
        )
    )

    _save_optional_outputs(
        args,
        paths,
        replay_frames,
        repetition_variables,
        audio_track,
        audio_rate,
    )

    task_metadata = {
        "idx_in_run": idx_in_run,
        "run": run,
        "global_idx": global_idx,
        "level_idx": level_idx,
        "phase": phase,
        "level": level,
    }
    _create_and_save_sidecar(repetition_variables, task_metadata, paths)

    # Explicitly clear large data structures to free memory
    del replay_frames
    del repetition_variables
    if audio_track is not None:
        del audio_track
    # Force garbage collection to release memory immediately
    gc.collect()


def _configure_logging(verbose):
    """Set up logging configuration."""
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(message)s", force=True)


def _determine_phase(events_dataframe):
    """Determine if replay is discovery or practice phase."""
    unique_levels = len(np.unique(events_dataframe["level"].dropna()))
    return "discovery" if unique_levels == 1 else "practice"


def _extract_run_from_filename(filename):
    """Extract run ID from events file name."""
    return filename.split("_")[-2]


def _collect_bk2_info_from_events(run_events_file):
    """Collect bk2 file info from a single events file."""
    run = _extract_run_from_filename(op.basename(run_events_file))
    logging.info(f"Processing events file: {run_events_file}")

    try:
        events_df = pd.read_table(run_events_file)
    except Exception as e:
        logging.error(f"Cannot read {run_events_file}: {e}")
        return []

    phase = _determine_phase(events_df)
    
    # Filter to only rows with valid .bk2 stim_files BEFORE enumerating
    # This ensures idx_in_run correctly counts only actual game repetitions
    valid_bk2_mask = events_df["stim_file"].apply(
        lambda x: isinstance(x, str) and ".bk2" in x
    )
    bk2_files = events_df.loc[valid_bk2_mask, "stim_file"].values.tolist()

    bk2_list = []
    for idx_in_run, bk2_file in enumerate(bk2_files):
        bk2_list.append(
            {
                "bk2_file": bk2_file,
                "run": run,
                "idx_in_run": idx_in_run,
                "phase": phase,
            }
        )
    return bk2_list


def _collect_all_bk2_files(data_path, subjects=None, sessions=None):
    """
    Walk dataset and collect all bk2 file information.

    Parameters
    ----------
    data_path : str
        Path to the mariostars dataset root directory
    subjects : list of str, optional
        List of subject IDs to process (e.g., ['sub-01', 'sub-02']).
        If None, processes all subjects.
    sessions : list of str, optional
        List of session IDs to process (e.g., ['ses-001', 'ses-002']).
        If None, processes all sessions.

    Returns
    -------
    list
        List of dicts containing bk2 file information
    """
    bk2_list = []
    for root, _, files in sorted(os.walk(data_path)):
        for file in files:
            if "events.tsv" in file and "annotated" not in file:
                # Check if this file matches subject filter
                if subjects is not None:
                    if not any(sub in root for sub in subjects):
                        continue

                # Check if this file matches session filter
                if sessions is not None:
                    if not any(ses in root for ses in sessions):
                        continue

                run_events_file = op.join(root, file)
                bk2_list.extend(_collect_bk2_info_from_events(run_events_file))
    return bk2_list


def _run_parallel_processing(tasks, args):
    """Process tasks in parallel using joblib."""
    with tqdm_joblib(tqdm(desc="Processing files", total=len(tasks))):
        Parallel(n_jobs=args.n_jobs, max_nbytes=None)(
            delayed(process_bk2_file)(task, args) for task in tasks
        )


def _run_sequential_processing(tasks, args):
    """Process tasks sequentially with progress bar."""
    for task in tqdm(tasks, desc="Processing files"):
        process_bk2_file(task, args)


def main(args):
    """
    Main entry point for replay processing.

    Scans dataset for events files, collects bk2 file info,
    and processes each replay in parallel or sequentially.

    Args:
        args: Parsed command-line arguments
    """
    _configure_logging(args.verbose)
    data_path = op.abspath(args.datapath)

    # Set up stimuli path once before parallel processing to avoid race conditions
    _setup_stimuli_path(args, data_path)

    # Get subject/session filters if provided
    subjects = getattr(args, "subjects", None)
    sessions = getattr(args, "sessions", None)

    if subjects:
        logging.info(f"Filtering subjects: {', '.join(subjects)}")
    if sessions:
        logging.info(f"Filtering sessions: {', '.join(sessions)}")

    bk2_list = _collect_all_bk2_files(data_path, subjects=subjects, sessions=sessions)

    if not bk2_list:
        logging.warning("No bk2 files found to process. Check your datapath and ensure events.tsv files exist.")
        return


    bk2_df = pd.DataFrame(bk2_list)
    bk2_df = get_passage_order(bk2_df)

    # Ensure explicit column order for task tuples to match process_bk2_file expectations
    task_columns = ["bk2_file", "run", "idx_in_run", "phase", "subject", "session", "level", "global_idx", "level_idx"]
    tasks = [tuple(row) for row in bk2_df[task_columns].values]
    logging.info(f"Found {len(tasks)} bk2 files to process.")

    n_jobs = os.cpu_count() if args.n_jobs == -1 else args.n_jobs
    logging.info(f"Using {n_jobs} parallel jobs")

    if n_jobs != 1:
        _run_parallel_processing(tasks, args)
    else:
        _run_sequential_processing(tasks, args)


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
        "-s",
        "--stimuli",
        default=None,
        type=str,
        help="Data path to look for the stimuli files (rom, state files, data.json etc...).",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=".",
        type=str,
        help="Path to the derivatives folder, where the outputs will be saved.",
    )
    parser.add_argument(
        "-nj",
        "--n_jobs",
        default=1,
        type=int,
        help="Number of parallel jobs to run. Use -1 to use all available cores.",
    )
    parser.add_argument(
        "--skip_videos",
        action="store_true",
        help="Skip generating the playback video file (_recording.mp4).",
    )
    parser.add_argument(
        "--skip_variables",
        action="store_true",
        help="Skip generating the variables file (_variables.json) that contains game variables.",
    )
    parser.add_argument(
        "--skip_lowlevel",
        action="store_true",
        help="Skip generating low-level features (_lowlevel.npy) - luminance, optical flow, audio envelope.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Display verbose output.",
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

    # Main loop
    main(args)
