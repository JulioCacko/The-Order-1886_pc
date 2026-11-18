"""Merge an update-extraction tree into the base tree of a mixed-case dump.

Some players extracted the 1.02 update beside the base game, so the dump holds
_data/1408209885/PS4/ (uppercase: the update) next to _data/1408209885/ps4/
(lowercase: the base). The guest opens the lowercase paths first and reads base
1.00 art while the executable is 1.02: prompts then show one button while the
game checks another (a quick event asks for Triangle but the real button is
Cross). A real PS4 overwrote the base files with the update; this script does
the same for the dump, once:

    python3 order1886_merge_update.py /path/to/CUSA00035           # list only
    python3 order1886_merge_update.py /path/to/CUSA00035 --apply   # merge

--apply copies every file from PS4/ onto the same path under ps4/ (the update
wins), adds files the base tree lacks, never deletes, and leaves PS4/ in place.
Original game archives are not touched; only extracted loose files move.
"""
import argparse
import hashlib
import shutil
import sys
from pathlib import Path

NAMESPACE = '_data/1408209885'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan(base, update):
    """[(relative, 'replace'|'add')] where the update tree differs from the base."""
    actions = []
    for source in sorted(update.rglob('*')):
        if not source.is_file():
            continue
        relative = source.relative_to(update)
        target = base / relative
        if target.is_file():
            if digest(target) != digest(source):
                actions.append((relative, 'replace'))
        else:
            actions.append((relative, 'add'))
    return actions


def main(argv=None):
    parser = argparse.ArgumentParser(description='Merge a PS4/ update tree onto the base ps4/ tree.')
    parser.add_argument('game_dir', type=Path, help='the extracted game folder (holds eboot.bin)')
    parser.add_argument('--apply', action='store_true', help='copy the update files (default: list only)')
    args = parser.parse_args(argv)
    root = args.game_dir / NAMESPACE
    if not (args.game_dir / 'eboot.bin').is_file():
        raise SystemExit(f'{args.game_dir} does not hold eboot.bin')
    if not root.is_dir():
        raise SystemExit(f'{root} is missing; this is not a The Order: 1886 dump')
    base, update = root / 'ps4', root / 'PS4'
    if not update.is_dir():
        raise SystemExit(f'no update tree at {update}; nothing to merge')
    if not base.is_dir():
        raise SystemExit(f'no base tree at {base}; the game already reads {update.name}/ through case folding')
    actions = plan(base, update)
    if not actions:
        print(f'{base} already matches the update tree.')
        return 0
    print(f'{len(actions)} file(s) in the update tree differ from or are missing in the base tree:')
    for relative, kind in actions:
        print(f'  {kind:7s} {relative}')
    if not args.apply:
        print('\nDry run. Re-run with --apply to merge the update into the base tree.')
        return 0
    for relative, _ in actions:
        target = base / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(update / relative, target)
    print(f'\nMerged {len(actions)} file(s). PS4/ stays in place; the game now reads the 1.02 art.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
