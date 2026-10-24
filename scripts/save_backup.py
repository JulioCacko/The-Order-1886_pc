#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Backups of the game's saves: <user>/savedata copied to <user>/savedata_backups/<time>.

run.py makes one before every start; the launcher lists them and restores one. A restore
or an import first backs up the current saves, so it can always be undone.
"""
import datetime
from pathlib import Path
import re
import shutil

KEEP = 10
STAMP = '%Y%m%d-%H%M%S'
BACKUP_NAME = re.compile(r'([0-9]{8}-[0-9]{6})(?:-([0-9]+))?')


def backups_dir(user_dir):
    return Path(user_dir) / 'savedata_backups'


def _backup_order(name):
    match = BACKUP_NAME.fullmatch(name)
    return (match[1], int(match[2] or 1)) if match else (name, 0)


def list_backups(user_dir):
    """Backup names, newest first."""
    root = backups_dir(user_dir)
    return sorted((p.name for p in root.iterdir() if p.is_dir()),
                  key=_backup_order, reverse=True) if root.is_dir() else []


def _has_saves(savedata):
    return savedata.is_dir() and any(p.is_file() for p in savedata.rglob('*'))


def _prune(user_dir, keep=KEEP):
    for name in list_backups(user_dir)[keep:]:
        shutil.rmtree(backups_dir(user_dir) / name, ignore_errors=True)


def _copy(user_dir, now):
    savedata = Path(user_dir) / 'savedata'
    if not _has_saves(savedata):
        return None
    root = backups_dir(user_dir)
    root.mkdir(parents=True, exist_ok=True)
    base = (now or datetime.datetime.now()).strftime(STAMP)
    # Pruning may have removed the unsuffixed folder or left gaps. Keep the
    # sequence increasing so a fresh backup cannot sort behind older ones.
    n = 1
    for entry in root.iterdir():
        stamp, sequence = _backup_order(entry.name)
        if stamp == base:
            n = max(n, sequence + 1)
    target = root / (base if n == 1 else f'{base}-{n}')
    shutil.copytree(savedata, target)
    return target


def backup(user_dir, now=None, keep=KEEP):
    """Copies savedata; returns the new folder, or None when there is nothing to save."""
    made = _copy(user_dir, now)
    if made:
        _prune(user_dir, keep)
    return made


def restore(user_dir, name, now=None):
    """Replaces savedata with backup `name`; returns the backup of the saves it replaced."""
    if not name or name not in list_backups(user_dir):
        raise ValueError(f'No save backup named {name!r}')
    source = backups_dir(user_dir) / name
    savedata = Path(user_dir) / 'savedata'
    # Pruning waits until the copy is done: the restored backup may be the oldest one.
    safety = _copy(user_dir, now)
    staging = Path(user_dir) / 'savedata.restoring'
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(source, staging)
    shutil.rmtree(savedata, ignore_errors=True)
    staging.rename(savedata)
    _prune(user_dir)
    return safety


# The SFO's INSTALL_DIR_SAVEDATA: the runtime keeps The Order's saves under this title id.
SAVE_TITLE = 'CUSA00035'


def _save_pairs(title_dir):
    """Saves in the runtime's layout: <name>/ with its metadata in <name>.sce_sys/param.bin."""
    return sorted(d.name for d in title_dir.iterdir()
                  if d.is_dir() and not d.name.endswith('.sce_sys')
                  and (title_dir / (d.name + '.sce_sys') / 'param.bin').is_file())


def _reject_unconverted(folder):
    for entry in folder.iterdir():
        key = folder / (entry.name + '.bin')
        if entry.is_file() and key.is_file() and key.read_bytes()[:8] == b'pfsSKKey':
            raise ValueError('These are encrypted PS4 saves (a save image with a pfsSKKey .bin). '
                             'Decrypt them first, for example with Apollo Save Tool on a PS4, '
                             'then import the decrypted folder.')
        if entry.is_dir() and (entry / 'sce_sys' / 'param.sfo').is_file():
            raise ValueError('This folder uses the PS4 export layout (sce_sys/param.sfo inside the '
                             'save). Import a folder from another installation\'s savedata or a '
                             'save backup instead: <name> beside <name>.sce_sys/param.bin.')


def find_saves(source):
    """(title folder, save names) for a savedata folder, a user or title folder, or one save."""
    source = Path(source)
    if not source.is_dir():
        raise ValueError(f'Not a folder: {source}')
    if (source.parent / (source.name + '.sce_sys') / 'param.bin').is_file():
        return source.parent, [source.name]
    candidates = [source, source / SAVE_TITLE]
    candidates += sorted(p / SAVE_TITLE for p in source.iterdir() if p.is_dir())
    for folder in candidates:
        if folder.is_dir():
            _reject_unconverted(folder)
            names = _save_pairs(folder)
            if names:
                return folder, names
    raise ValueError(f'No saves found in {source}. Choose a savedata folder, its {SAVE_TITLE} '
                     'folder, or one save folder that has a matching <name>.sce_sys/param.bin.')


def import_saves(user_dir, source, now=None):
    """Copies saves from `source` over same-named saves; returns (names, safety backup)."""
    savedata = Path(user_dir) / 'savedata'
    source = Path(source).resolve()
    if source == savedata.resolve() or savedata.resolve() in source.parents:
        raise ValueError('That folder is already this installation\'s savedata.')
    folder, names = find_saves(source)
    safety = _copy(user_dir, now)
    users = sorted(p.name for p in savedata.iterdir() if p.is_dir() and p.name.isdigit()) \
        if savedata.is_dir() else []
    target = savedata / (users[0] if users else '1') / SAVE_TITLE
    target.mkdir(parents=True, exist_ok=True)
    for name in names:
        for part in (name, name + '.sce_sys'):
            staging = target / (part + '.importing')
            shutil.rmtree(staging, ignore_errors=True)
            shutil.copytree(folder / part, staging)
            shutil.rmtree(target / part, ignore_errors=True)
            staging.rename(target / part)
    _prune(user_dir)
    return names, safety

