# Mario Stars Replay Processing

Processes `.bk2` replay files to generate video, metadata, game variables, and low-level features.

## Prerequisites & Installation

1.  **Environment**: Python 3.8+, Mariostars dataset (with `.bk2` replays), and ROMs in `stimuli/`.
2.  **Setup**:
    ```bash
    python -m venv env
    source env/bin/activate
    pip install -r code/replays/requirements.txt
    ```

## Usage

```bash
python code/replays/generate_replays.py
```

### Arguments
-   `--datapath`: Root directory of the dataset.
-   `--output`: Output directory.
-   `--skip_videos`, `--skip_variables`, `--skip_lowlevel`: Skip specific outputs.
-   `--n_jobs`: Number of parallel jobs (default: all cores).
-   `--subjects`, `--sessions`: Filter processing.
-   `--stimuli`: Custom path for ROMs.
-   `--verbose`: Enable detailed logging.

## Generated Files

For each replay (e.g., `sub-{subject}_ses-{session}_task-mariostars_run-{run}_rep-{replay}.bk2`):
1.  `*_recording.mp4`: Video recording.
2.  `*_variables.json`: Frame-by-frame RAM variables.
3.  `*_lowlevel.npy`: Luminance, optical flow, and audio features.
4.  `*_summary.json`: Summary metadata (BIDS sidecar).

## Summary Variables (in sidecar JSON)

All variables rely on RAM addresses defined in `stimuli/SuperMarioAllStars-Snes/data.json`.

| Variable | Source / Logic |
| :--- | :--- |
| **Duration** | Total replay duration in seconds. |
| **Outcome** | `cleared` (flag hit[state 4] & lives≥0), `failed/timeout` (timer=0), `failed/fall` (life lost, no state 11), `failed/killed` (life lost, state 11). |
| **X_traveled** | Distance traveled to flag hit (or end if not cleared). |
| **Enemies_killed** | Count of sprite_state transitions to kill states (4, 34). |
| **Hits_taken** | Count of hit events (powerup loss, life loss, fall). |
| **Bricks_smashed** | Count of `score` increments of 50 (before flag hit only). |
| **Coins** | Coin count changes. |
| **Powerups_collected** | Count of powerup collections (action_state transitions 8→9, 8→12). |
| **Stars_collected** | Count of star_power_timer activations. |
| **Phase** | `discovery` (level repeats) or `practice` (sequential progression). |
