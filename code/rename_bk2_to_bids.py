#!/usr/bin/env python
"""
Rename .bk2 files in the mariostars dataset to match BIDS naming convention.

This script renames .bk2 files from:
    task-mariostars_level-w5l1_rep-001.bk2
to:
    sub-02_ses-007_task-mariostars_level-w5l1_rep-001.bk2

It also updates all corresponding references in events.tsv files.

Usage:
    # Preview changes without making them
    python code/rename_bk2_to_bids.py --datapath . --dry-run

    # Actually perform the renaming
    python code/rename_bk2_to_bids.py --datapath .
"""

import argparse
import os
import os.path as op
import shutil
import csv
from pathlib import Path


def find_all_bk2_files(data_path):
    """
    Find all .bk2 files in the dataset.

    Returns:
        List of tuples: (full_path, subject, session, old_filename)
    """
    bk2_files = []

    for root, dirs, files in os.walk(data_path):
        for file in files:
            if file.endswith('.bk2'):
                full_path = op.join(root, file)
                # Extract subject and session from path
                path_parts = root.split(os.sep)

                # Find subject and session in path
                subject = None
                session = None
                for part in path_parts:
                    if part.startswith('sub-'):
                        subject = part
                    elif part.startswith('ses-'):
                        session = part

                if subject and session:
                    bk2_files.append((full_path, subject, session, file))
                else:
                    print(f"Warning: Could not extract subject/session from {full_path}")

    return bk2_files


def generate_new_filename(old_filename, subject, session):
    """
    Generate new BIDS-compliant filename.

    Args:
        old_filename: e.g., "task-mariostars_level-w5l1_rep-001.bk2"
        subject: e.g., "sub-02"
        session: e.g., "ses-007"

    Returns:
        New filename: e.g., "sub-02_ses-007_task-mariostars_level-w5l1_rep-001.bk2"
    """
    # If filename already has subject/session prefix, don't modify it
    if old_filename.startswith(f"{subject}_"):
        return old_filename

    return f"{subject}_{session}_{old_filename}"


def find_events_files(data_path):
    """Find all events.tsv files that are not annotated."""
    events_files = []

    for root, dirs, files in os.walk(data_path):
        for file in files:
            if file.endswith('events.tsv') and 'annotated' not in file:
                events_files.append(op.join(root, file))

    return events_files


def update_events_file(events_file_path, rename_mapping, dry_run=False):
    """
    Update stim_file paths in events.tsv file.

    Args:
        events_file_path: Path to events.tsv file
        rename_mapping: Dict mapping old filenames to new filenames
        dry_run: If True, only preview changes

    Returns:
        Number of paths updated
    """
    try:
        with open(events_file_path, 'r') as f:
            reader = csv.DictReader(f, delimiter='\t')
            rows = list(reader)
            fieldnames = reader.fieldnames
    except Exception as e:
        print(f"Warning: Could not read {events_file_path}: {e}")
        return 0

    if 'stim_file' not in fieldnames:
        return 0

    updates = 0

    for row in rows:
        stim_file = row.get('stim_file', '')

        # Skip if not a string or not a .bk2 file
        if not stim_file or not stim_file.endswith('.bk2'):
            continue

        # Extract just the filename from the path
        old_filename = stim_file.split('/')[-1]

        # Check if we have a mapping for this file
        if old_filename in rename_mapping:
            new_filename = rename_mapping[old_filename]
            # Replace just the filename part in the full path
            path_parts = stim_file.split('/')
            path_parts[-1] = new_filename
            new_stim_file = '/'.join(path_parts)

            row['stim_file'] = new_stim_file
            updates += 1

    if updates > 0:
        if dry_run:
            print(f"  Would update {updates} paths in {events_file_path}")
        else:
            with open(events_file_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter='\t')
                writer.writeheader()
                writer.writerows(rows)
            print(f"  Updated {updates} paths in {events_file_path}")

    return updates


def main(args):
    data_path = op.abspath(args.datapath)

    print(f"Scanning for .bk2 files in {data_path}...")
    bk2_files = find_all_bk2_files(data_path)

    if not bk2_files:
        print("No .bk2 files found.")
        return

    print(f"Found {len(bk2_files)} .bk2 files")

    # Build rename mapping
    rename_mapping = {}  # old_filename -> new_filename
    rename_operations = []  # (old_path, new_path, subject, session)

    for full_path, subject, session, old_filename in bk2_files:
        new_filename = generate_new_filename(old_filename, subject, session)

        if new_filename != old_filename:
            new_path = op.join(op.dirname(full_path), new_filename)
            rename_operations.append((full_path, new_path, subject, session))
            rename_mapping[old_filename] = new_filename

    if not rename_operations:
        print("All .bk2 files already have BIDS-compliant names. Nothing to do.")
        return

    print(f"\n{len(rename_operations)} files need to be renamed:")
    print("=" * 80)

    for old_path, new_path, subject, session in rename_operations[:10]:
        old_name = op.basename(old_path)
        new_name = op.basename(new_path)
        print(f"  {old_name}")
        print(f"  -> {new_name}")
        print()

    if len(rename_operations) > 10:
        print(f"  ... and {len(rename_operations) - 10} more files")

    # Rename files
    if args.dry_run:
        print("\n[DRY RUN] Would rename the files above")
    else:
        print("\nRenaming files...")
        for old_path, new_path, subject, session in rename_operations:
            try:
                shutil.move(old_path, new_path)
                print(f"✓ Renamed: {op.basename(old_path)} -> {op.basename(new_path)}")
            except Exception as e:
                print(f"✗ Error renaming {old_path}: {e}")

    # Update events files
    print(f"\nScanning for events.tsv files...")
    events_files = find_events_files(data_path)
    print(f"Found {len(events_files)} events.tsv files")

    if events_files:
        print("\nUpdating events.tsv files...")
        total_updates = 0
        for events_file in events_files:
            updates = update_events_file(events_file, rename_mapping, dry_run=args.dry_run)
            total_updates += updates

        if args.dry_run:
            print(f"\n[DRY RUN] Would update {total_updates} total paths in events files")
        else:
            print(f"\nUpdated {total_updates} total paths in events files")

    if args.dry_run:
        print("\n" + "=" * 80)
        print("DRY RUN COMPLETE - No changes were made")
        print("Run without --dry-run to actually perform the renaming")
    else:
        print("\n" + "=" * 80)
        print("✓ COMPLETE - All files renamed and events.tsv files updated")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Rename .bk2 files to BIDS-compliant naming convention"
    )
    parser.add_argument(
        "-d",
        "--datapath",
        default=".",
        type=str,
        help="Path to the mariostars dataset root directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without actually renaming files",
    )

    args = parser.parse_args()
    main(args)
