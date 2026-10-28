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
import struct

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
# src/runtime_savedata.c Param: title[128], subtitle[128], detail[1024], user_param, pad,
# mtime (the runtime takes it from the file), reserved[32].
PARAM_BIN = struct.Struct('<128s128s1024sIiq32s')


def read_sfo(path):
    """Text and integer entries of a PS4 param.sfo."""
    data = Path(path).read_bytes()
    magic, _, keys, values, count = struct.unpack_from('<4sIIII', data)
    if magic != b'\0PSF':
        raise ValueError(f'Not a param.sfo: {path}')
    entries = {}
    for i in range(count):
        key_at, fmt, length, _, value_at = struct.unpack_from('<HHIII', data, 20 + i * 16)
        key = data[keys + key_at:data.index(b'\0', keys + key_at)].decode()
        value = data[values + value_at:values + value_at + length]
        if fmt == 0x0404:
            entries[key] = int.from_bytes(value[:4], 'little')
        elif fmt == 0x0204:
            entries[key] = value.rstrip(b'\0').decode('utf-8', 'replace')
    return entries


def param_bin(sfo):
    """The runtime's param.bin for a save exported with its param.sfo."""
    text = lambda key, size: sfo.get(key, '').encode('utf-8')[:size - 1]
    return PARAM_BIN.pack(text('MAINTITLE', 128), text('SUBTITLE', 128), text('DETAIL', 1024),
                          sfo.get('SAVEDATA_LIST_PARAM', 0), 0, 0, b'')


def _valid_name(name):
    return 0 < len(name) < 32 and not set(name) & set('/\\:') and not name.startswith('.')


def _runtime_saves(folder):
    """Saves in the runtime's layout: <name>/ with its metadata in <name>.sce_sys/param.bin."""
    return [(d.name, d, folder / (d.name + '.sce_sys'), None) for d in sorted(folder.iterdir())
            if d.is_dir() and not d.name.endswith('.sce_sys')
            and (folder / (d.name + '.sce_sys') / 'param.bin').is_file()]


def _exported_save(folder):
    """A decrypted PS4 export (Apollo): the save's files plus sce_sys/param.sfo inside it."""
    sfo_path = folder / 'sce_sys' / 'param.sfo'
    if not sfo_path.is_file():
        return None
    sfo = read_sfo(sfo_path)
    if sfo.get('TITLE_ID') != SAVE_TITLE:
        raise ValueError(f'{folder.name} is a save of {sfo.get("TITLE_ID") or "an unnamed title"}, '
                         f'not The Order: 1886 ({SAVE_TITLE}).')
    name = sfo.get('SAVEDATA_DIRECTORY') or folder.name.rsplit('_' + SAVE_TITLE + '_', 1)[-1]
    if not _valid_name(name):
        raise ValueError(f'{folder.name} names an invalid save directory: {name!r}')
    return name, folder, folder / 'sce_sys', sfo


def _reject_encrypted(folder):
    for entry in folder.iterdir():
        key = folder / (entry.name + '.bin')
        if entry.is_file() and key.is_file() and key.read_bytes()[:8] == b'pfsSKKey':
            raise ValueError('These are encrypted PS4 saves (a save image with a pfsSKKey .bin). '
                             'Decrypt them first, for example with Apollo Save Tool on a PS4, '
                             'then import the decrypted folder.')


def find_saves(source):
    """(name, files, metadata, sfo or None) for each save in a savedata folder, a user or
    title folder, a folder of PS4 exports, or one save of either layout."""
    source = Path(source)
    if not source.is_dir():
        raise ValueError(f'Not a folder: {source}')
    exported = _exported_save(source)
    if exported:
        return [exported]
    if (source.parent / (source.name + '.sce_sys') / 'param.bin').is_file():
        return [(source.name, source, source.parent / (source.name + '.sce_sys'), None)]
    candidates = [source, source / SAVE_TITLE]
    candidates += sorted(p / SAVE_TITLE for p in source.iterdir() if p.is_dir())
    for folder in candidates:
        if folder.is_dir():
            _reject_encrypted(folder)
            # A folder may hold both layouts: runtime saves and decrypted exports.
            saves = _runtime_saves(folder) + [s for s in map(_exported_save, sorted(
                d for d in folder.iterdir() if d.is_dir())) if s]
            if saves:
                return saves
    raise ValueError(f'No saves found in {source}. Choose a savedata folder, its {SAVE_TITLE} '
                     'folder, a decrypted PS4 save export, or one save folder.')


def _replace(staging, target):
    shutil.rmtree(target, ignore_errors=True)
    staging.rename(target)


def import_saves(user_dir, source, now=None):
    """Copies saves from `source` over same-named saves; returns (names, safety backup)."""
    savedata = Path(user_dir) / 'savedata'
    source = Path(source).resolve()
    if source == savedata.resolve() or savedata.resolve() in source.parents:
        raise ValueError("That folder is already this installation's savedata.")
    saves = find_saves(source)
    safety = _copy(user_dir, now)
    users = sorted(p.name for p in savedata.iterdir() if p.is_dir() and p.name.isdigit()) \
        if savedata.is_dir() else []
    target = savedata / (users[0] if users else '1') / SAVE_TITLE
    target.mkdir(parents=True, exist_ok=True)
    for name, files, meta, sfo in saves:
        staging = target / (name + '.importing')
        shutil.rmtree(staging, ignore_errors=True)
        shutil.copytree(files, staging, ignore=shutil.ignore_patterns('sce_sys') if sfo else None)
        meta_staging = target / (name + '.sce_sys.importing')
        shutil.rmtree(meta_staging, ignore_errors=True)
        if sfo is None:
            shutil.copytree(meta, meta_staging)
        else:
            meta_staging.mkdir()
            (meta_staging / 'param.bin').write_bytes(param_bin(sfo))
            if (meta / 'icon0.png').is_file():
                shutil.copy2(meta / 'icon0.png', meta_staging / 'icon0.png')
        _replace(staging, target / name)
        _replace(meta_staging, target / (name + '.sce_sys'))
    _prune(user_dir)
    return [save[0] for save in saves], safety
