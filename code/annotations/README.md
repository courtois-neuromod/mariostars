# Mario Stars Annotations Generator

Generates BIDS-compatible `*_desc-annotated_events.tsv` files from pre-processed game variables.

## Prerequisites & Installation

1.  **Environment**: Python 3.8+, Mariostars dataset (with `.bk2` replays).
2.  **Replays must be processed first** using `code/replays/generate_replays.py` to generate `*_variables.json` files.
3.  **Setup**:
    ```bash
    python -m venv env
    source env/bin/activate
    pip install -r code/annotations/requirements.txt
    ```

## Usage

```bash
python code/annotations/generate_annotations.py
```

### Arguments
-   `--datapath`: Root directory of the dataset.
-   `--output_path`: Custom output path.
-   `--subjects`, `--sessions`: Filter processing.

## Generated Annotations

The script produces BIDS-compatible `*_desc-annotated_events.tsv` files with the following structure:

### Column Order

| Column | Description |
|--------|-------------|
| trial_type | Type of event (see below) |
| rep_index | Repetition index within the run (integer) |
| level | Level identifier (e.g., "w1l1", "w2l3") |
| onset | Time in seconds from the start of the run (3 decimal places) |
| duration | Duration of the event in seconds (3 decimal places) |
| frame_start | Frame index where event starts (integer) |
| frame_stop | Frame index where event ends (integer) |
| phase | "discovery" or "practice" |

### Event Types

#### Repetition Events
- `gym-retro_game` - Base repetition events from the original events file

#### Button Press Events
Continuous events with onset and duration:
- `UP`, `DOWN`, `LEFT`, `RIGHT` - D-pad directions
- `JUMP` - Jump button (A)
- `RUN/THROW` - Run/fireball button (B)
- `X`, `Y`, `L`, `R` - SNES face/shoulder buttons
- `START`, `SELECT`

#### Enemy Kill Events
Instantaneous events (duration=0):
- `Kill/stomp` - Jumping on enemy (sprite_state transition to 4 **Note:** Does note capture all the stomps - e.g. flying Koopas)
- `Kill/impact` - Shell, fireball, or star kill (sprite_state transition to 34)

#### Hit Events
Instantaneous events (duration=0):
- `Hit/powerup_lost` - Lost powerup state (player_action_state transition to 10)
- `Hit/life_lost` - Death by enemy (player_action_state transition to 11)
- `Hit/fall` - Death by falling in pit (lives decrease without state transition)
- `Hit/timeout` - Death by timer running out

#### Item Collection Events
- `Coin_collected` (Instant): Coin counter increases
- `Powerup_collected` (Instant): Mushroom or Fire Flower collected (action_state 8→9 or 8→12)
- `Brick_smashed` (Instant): Brick destroyed (detected via score increment of 50)
- `Star_activated` (Variable duration): Period where `star_power_timer` > 0

#### Level Completion Events
Instantaneous events (duration=0):
- `Level_complete` - Flag hit (detected via player_action_state becoming 1 - sliding down flagpole)

### Phase Information

Each run was performed in one of these two phases:
- **discovery**: Single level repeated multiple times (practice/training)
- **practice**: Multiple different levels in sequence (testing)

### RAM Variables Available in data.json

The current `data.json` file for Super Mario All-Stars includes:
- `lives` - Player lives count
- `score` - Current score
- `coins` - Coin count
- `player_powerup` - Mario's powerup state
- `player_action_state` - Player action/animation state
- `star_power_timer` - Star power timer
- `sprite_state_0` through `sprite_state_7` - Enemy sprite states
- `level_timer_*` - Time remaining
- `player_x_*`, `player_y_*` - Player position
