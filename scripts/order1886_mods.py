# SPDX-License-Identifier: GPL-2.0-or-later
"""Order asset overlays, adapted from Jgamrot/bloodborne_pc scripts/mods.py.

Donor: 52e4988f54b0626447563874bf8695633b1a4302, GPL-2.0-or-later.
Reuses the donor's mirrored-directory/link-and-copy overlay and ordered replacement
approach. Order permits only _data and its required archivemap.bin asset index.
Unlike the donor, new mods are disabled, directory links are refused, replacement
files are copied, and read-only source attributes are never changed for cleanup.
"""
import json
import os
from pathlib import Path
import re
import shutil
import stat
import uuid

OWNER = 'The Order: 1886 asset overlays v1\n'
GENERATION = re.compile(r'overlay-[0-9a-f]{32}\Z')
EXECUTABLE_SUFFIXES = {'.exe', '.dll', '.prx', '.sprx', '.elf', '.self', '.so', '.bat', '.cmd', '.ps1'}


def _component(name):
    if (not isinstance(name, str) or not name or name in ('.', '..') or name[-1] in '. '
            or any(ord(c) < 32 or c in '/\\:*?"<>|' for c in name)
            or name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                                            *(f'COM{i}' for i in range(1, 10)),
                                            *(f'LPT{i}' for i in range(1, 10))}):
        raise ValueError(f'Invalid mod path component: {name!r}')


def _stat(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError(f'Links and reparse points are not supported: {path}')
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        raise ValueError(f'Not a regular file or directory: {path}')
    return info


def safe_path(path):
    """Check before resolving, so a selected junction cannot hide its redirection."""
    path = Path(path).absolute()
    for ancestor in (*reversed(path.parents), path):
        try:
            _stat(ancestor)
        except FileNotFoundError:
            pass
    return path.resolve()


def resolve_root(root, installation):
    """Saved relative mod paths use the installation, independent of process CWD."""
    if not isinstance(root, (str, Path)):
        raise ValueError('Mods folder must be a path.')
    if not str(root):
        return ''
    path = Path(root)
    return safe_path(path if path.is_absolute() else Path(installation) / path)


def _entries(folder):
    entries, seen = [], set()
    for path in folder.iterdir():
        _component(path.name)
        key = path.name.casefold()
        if key in seen:
            raise ValueError(f'Ambiguous filename case in {folder}: {path.name}')
        seen.add(key)
        entries.append((path, _stat(path)))
    return sorted(entries, key=lambda item: item[0].name.casefold())


def _tree(folder):
    for path, info in _entries(folder):
        yield path, info
        if stat.S_ISDIR(info.st_mode):
            yield from _tree(path)


def discover(root):
    root = safe_path(root)
    if not root.is_dir():
        raise ValueError(f'Mods folder not found: {root}')
    return [path.name for path, info in _entries(root) if stat.S_ISDIR(info.st_mode)]


def validate_config(root, enabled, order):
    if type(enabled) is not bool or not isinstance(order, list) or not isinstance(root, (str, Path)):
        raise ValueError('Mods require a boolean enabled flag and an ordered list of folder names.')
    names = set()
    for name in order:
        _component(name)
        if name.casefold() in names:
            raise ValueError(f'Duplicate or ambiguous mod name: {name}')
        names.add(name.casefold())
    if not enabled or not order:
        return []
    if not isinstance(root, (str, Path)) or not str(root):
        raise ValueError('Choose a mods folder before enabling mods.')
    available = discover(root)
    for name in order:
        if name not in available:
            raise ValueError(f'Selected mod folder is missing or has different case: {name}')
    return [(name, safe_path(Path(root) / name)) for name in order]


def mod_files(folder):
    files = []
    for source, info in _tree(folder):
        relative = source.relative_to(folder)
        first = relative.parts[0].casefold()
        directory = stat.S_ISDIR(info.st_mode)
        if first != '_data' and not (first == 'archivemap.bin' and len(relative.parts) == 1 and not directory):
            if len(relative.parts) == 1 and not directory and source.name.casefold() in ('readme.txt', 'readme.md', 'license.txt', 'license.md'):
                continue
            raise ValueError(f'Only _data assets and archivemap.bin may be replaced: {source}')
        if directory:
            continue
        if source.suffix.casefold() in EXECUTABLE_SUFFIXES or source.name.casefold() == 'eboot.bin':
            raise ValueError(f'Executable replacement is unsupported: {source}')
        with source.open('rb') as stream:
            if stream.read(4).startswith((b'MZ', b'\x7fELF', b'\x4f\x15\x3d\x1d')):
                raise ValueError(f'Executable content is unsupported: {source}')
        files.append((relative, source))
    if not files:
        raise ValueError(f'No supported asset files in mod: {folder.name}')
    return files


def plan(game, root, enabled, order):
    selected = validate_config(root, enabled, order)
    if not selected:
        return [], []
    game = safe_path(game)
    known = {str(path.relative_to(game)).casefold(): (path.relative_to(game), stat.S_ISDIR(info.st_mode))
             for path, info in _tree(game)}
    replacements, conflicts, owners = [], [], {}
    for name, folder in selected:
        for relative, source in mod_files(folder):
            canonical = Path()
            for index, component in enumerate(relative.parts):
                canonical /= component
                key = str(canonical).casefold()
                directory = index < len(relative.parts) - 1
                if key in known:
                    canonical, previous_directory = known[key]
                    if previous_directory != directory:
                        raise ValueError(f'File/directory conflict: {relative}')
                else:
                    known[key] = (canonical, directory)
            key = canonical.as_posix().casefold()
            if key in owners:
                conflicts.append((canonical.as_posix(), owners[key], name))
            owners[key] = name
            replacements.append((canonical, source))
    return replacements, conflicts


def make_link(link, target):
    """Donor hard-link/copy strategy; read-only inputs must be independent copies."""
    info = _stat(target)
    if info.st_mode & stat.S_IWRITE:
        try:
            os.link(target, link)
            return
        except OSError:
            pass
    shutil.copyfile(target, link)


def _owned_root(state, create=False):
    root = safe_path(Path(state) / 'mod-overlays')
    if not root.exists():
        if not create:
            return None
        root.mkdir()
    marker = root / '.order1886-owned'
    if not any(root.iterdir()) and create:
        marker.write_text(OWNER, encoding='utf-8')
    if not marker.is_file() or _stat(marker).st_nlink != 1 or marker.read_text(encoding='utf-8') != OWNER:
        raise ValueError(f'Not an owned Order mod overlay folder: {root}')
    for path, info in _entries(root):
        if GENERATION.fullmatch(path.name) and stat.S_ISDIR(info.st_mode):
            continue
        if path.name not in ('.order1886-owned', 'active.json', 'active.tmp') or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError(f'Unexpected overlay entry: {path}')
    active = root / 'active.json'
    if active.exists():
        value = json.loads(active.read_text(encoding='utf-8'))
        if not isinstance(value, dict) or set(value) != {'active'} or not isinstance(value['active'], str) or not GENERATION.fullmatch(value['active']):
            raise ValueError('Malformed active mod overlay record.')
    return root


def _remove(root, directory):
    if directory.parent != root or not GENERATION.fullmatch(directory.name) or safe_path(directory) != directory:
        raise ValueError(f'Refusing overlay cleanup outside owned storage: {directory}')
    list(_tree(directory))  # Reject redirects before removal, including junctions after a crash.
    shutil.rmtree(directory)  # Never chmod: a hard link can share source attributes.


def _cleanup(root, keep=None):
    directories = [path for path in root.iterdir() if GENERATION.fullmatch(path.name) and path != keep]
    for directory in directories:
        list(_tree(directory))
    for directory in directories:
        _remove(root, directory)
    if keep is None:
        (root / 'active.json').unlink(missing_ok=True)
    (root / 'active.tmp').unlink(missing_ok=True)


def build_overlay(game, state, root='', enabled=False, order=None):
    """Build under the caller's Order session_lock; publish only a complete generation.

    The backend owns the lock through preparation, this call, and runtime exit.
    Read-only UI discovery/planning never creates or removes an overlay.
    """
    game, state = safe_path(game), safe_path(state)
    if state == game or game in state.parents:
        raise ValueError('Mod overlay state must be outside the original game folder.')
    destination = state / 'mod-overlays'
    if game == destination or game in destination.parents or destination in game.parents:
        raise ValueError('The game folder must not overlap managed mod overlay storage.')
    replacements, _ = plan(game, root, enabled, [] if order is None else order)
    if not replacements:
        owned = _owned_root(state)
        if owned:
            _cleanup(owned)
        return game
    mod_root = safe_path(root)
    if (destination == mod_root or destination in mod_root.parents or mod_root in destination.parents
            or mod_root == game or game in mod_root.parents or mod_root in game.parents):
        raise ValueError('Game, mods, and overlay folders must not contain one another.')
    owned = _owned_root(state, create=True)
    for previous in owned.iterdir():
        if GENERATION.fullmatch(previous.name):
            list(_tree(previous))
    overlay = owned / ('overlay-' + uuid.uuid4().hex)
    overlay.mkdir()
    try:
        for source, info in _tree(game):
            target = overlay / source.relative_to(game)
            if stat.S_ISDIR(info.st_mode):
                target.mkdir()
            else:
                make_link(target, source)
        for relative, source in replacements:
            target = overlay / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.unlink(missing_ok=True)
            safe_path(source)
            _stat(source)
            shutil.copyfile(source, target)
        temporary = owned / 'active.tmp'
        temporary.write_text(json.dumps({'active': overlay.name}), encoding='utf-8')
        temporary.replace(owned / 'active.json')
    except BaseException:
        _remove(owned, overlay)
        raise
    _cleanup(owned, keep=overlay)
    return overlay
