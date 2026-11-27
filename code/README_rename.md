# BIDS Renaming Script for Mario Stars

This script renames `.bk2` files in the mariostars dataset to match the proper BIDS naming convention used in the mario dataset.

## What it does

Renames files from:
```
task-mariostars_level-w5l1_rep-001.bk2
```

to:
```
sub-02_ses-007_task-mariostars_level-w5l1_rep-001.bk2
```

And updates all references in `*_events.tsv` files accordingly.

## Usage

### 1. Preview changes (recommended first)

```bash
python code/rename_bk2_to_bids.py --datapath . --dry-run
```

This will show you what would be renamed without making any changes.

### 2. Perform the renaming

```bash
python code/rename_bk2_to_bids.py --datapath .
```

This will:
- Rename all `.bk2` files to include subject and session prefixes
- Update all `stim_file` paths in `*_events.tsv` files

## Requirements

- pandas

## Notes

- The script extracts subject and session IDs from the directory path
- Files that already have BIDS-compliant names are skipped
- Always run with `--dry-run` first to verify the changes
