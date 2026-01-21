# Mario Stars Annotations Generator

This script generates BIDS-compatible annotated event files (`*_desc-annotated_events.tsv`) for the Super Mario All-Stars dataset. It reads pre-processed game variables and computes detailed annotations for all gameplay events including button presses, enemy kills, hits taken, item collection, and more.

**IMPORTANT NOTE**: This script contains placeholder logic that needs to be updated once the `data.json` file for Super Mario All-Stars becomes available. All game-specific event detection logic is marked with `TODO` comments and should be verified against actual game variables.

## Prerequisites

- Python 3.8 or higher
- The Mario Stars dataset with `.bk2` replay files
- **Replays must be processed first** using `code/replays/create_replays.py` to generate `*_variables.json` files
- ROM files in the `stimuli/` directory

## Installation

### 1. Create a Python virtual environment

From the root directory of the mariostars repository:

```bash
python -m venv env
```

### 2. Activate the environment

```bash
source env/bin/activate  # On Linux/Mac
# OR
env\Scripts\activate  # On Windows
```

### 3. Install dependencies

```bash
pip install -r code/annotations/requirements.txt
```

This will install:
- numpy
- pandas
- stable-retro

## Usage

### Basic Usage

From the root directory of the mariostars repository:

```bash
python code/annotations/generate_annotations.py --datapath .
```

This will:
- Scan all `*_events.tsv` files in the dataset
- Load corresponding replay variables from `gamelogs/*_variables.json`
- Generate `*_desc-annotated_events.tsv` files with detailed event annotations

### Options

```bash
# Specify a custom data path
python code/annotations/generate_annotations.py --datapath /path/to/mariostars

# Custom output path
python code/annotations/generate_annotations.py --datapath . --output_path /path/to/output

# Filter by subject
python code/annotations/generate_annotations.py --datapath . --subjects sub-01 sub-02

# Filter by session
python code/annotations/generate_annotations.py --datapath . --sessions ses-001 ses-002
```

## Generated Annotations

The script produces `*_desc-annotated_events.tsv` files with the following structure:

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
| phase | "discovery" or "practice" (see below) |

### Event Types

**Note**: The event types and detection logic below are placeholders based on the original Super Mario Bros. These need to be verified and updated based on the actual `data.json` file for Super Mario All-Stars.

#### Repetition Events
- `gym-retro_game` - Base repetition events from the original events file

#### Button Press Events
Continuous events with onset and duration:
- `UP`, `DOWN`, `LEFT`, `RIGHT` - D-pad directions
- `A` - Jump button
- `B` - Run/fireball button
- `START` - Pause
- `SELECT` - Mode select
- **TODO**: Verify if L/R shoulder buttons are used in Super Mario All-Stars

#### Enemy Kill Events
Instantaneous events (duration=0):
- `Kill/stomp` - Jumping on enemy
- `Kill/impact` - Shell or fireball hit
- `Kill/kick` - Kicked shell
- **TODO**: Verify kill types and values for Super Mario All-Stars

#### Hit Events
Instantaneous events (duration=0):
- `Hit/powerup_lost` - Lost fire flower or super mushroom state
- `Hit/life_lost` - Death
- **TODO**: Verify powerstate threshold for Super Mario All-Stars

#### Item Collection Events
Instantaneous events (duration=0):
- `Coin_collected` - Coin counter increases
- `Powerup_collected` - Super mushroom or fire flower collected
- `Brick_smashed` - Brick destroyed by jumping
- **TODO**: Verify score increments and player_state values

### Phase Information

Each run is classified as:
- **discovery**: Single level repeated multiple times (practice/training)
- **practice**: Multiple different levels in sequence (testing)

## Placeholder Logic - Requires Data.json

The following sections of the code contain placeholder logic that **must be updated** once the `data.json` file for Super Mario All-Stars is available:

### 1. Enemy Kill Detection
- **Location**: `generate_kill_events()` function
- **Current**: Assumes 6 enemy slots with values 4 (stomp), 34 (impact), 132 (kick)
- **TODO**: Verify enemy slot count, variable names, and kill type values

### 2. Hit Detection
- **Location**: `generate_hits_taken_events()` function
- **Current**: Powerup loss threshold is -10000
- **TODO**: Verify powerstate change threshold for All-Stars

### 3. Brick Destruction
- **Location**: `generate_bricks_smashed_events()` function
- **Current**: Detects score increment of 5 points while airborne
- **TODO**: Verify score increment value for All-Stars (may vary by game)

### 4. Powerup Collection
- **Location**: `generate_powerup_events()` function
- **Current**: Detects player_state values [9, 12, 13]
- **TODO**: Verify player_state values for powerup animation

### 5. Button Controls
- **Location**: `create_runevents()` function
- **Current**: Assumes standard SNES controls (UP, DOWN, LEFT, RIGHT, A, B, START, SELECT)
- **TODO**: Verify if L/R shoulder buttons are used

## Dependencies

This script requires that replays have been processed first:

```bash
# First, process replays to generate variables
python code/replays/create_replays.py --datapath .

# Then run annotations
python code/annotations/generate_annotations.py --datapath .
```

## Troubleshooting

### "Variables file not found" errors
- Ensure you've run `code/replays/create_replays.py` first
- Check that `gamelogs/*_variables.json` files exist for each .bk2 file

### "No bk2 files available for this run"
- Normal if a run has no valid .bk2 files (all marked as "Missing file")

### ROM/stimuli errors
- Verify that `stimuli/SuperMarioAllStars-Snes/` contains the ROM files

### Already annotated files
- The script skips files that already have annotated versions
- To force regeneration, delete existing `*_desc-annotated_events.tsv` files

### Incorrect event detection
- If events seem incorrect, check the TODO comments in the code
- Compare with the actual `data.json` file for Super Mario All-Stars
- Update the placeholder values and logic as needed

## Next Steps

Before running this script on your full dataset:

1. Obtain the `data.json` file for Super Mario All-Stars
2. Review all TODO comments in `generate_annotations.py`
3. Update event detection logic based on actual game variables
4. Test on a small subset of data to verify correctness
5. Run on the full dataset once verified
