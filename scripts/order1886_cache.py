"""Clear only The Order's regenerable native shader cache."""
import os
from pathlib import Path
import shutil
import stat


def _safe_stat(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode) or (
        getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise ValueError(f'Refusing redirected shader-cache path (link or reparse point): {path}')
    return info


def _check_ancestors(path):
    for parent in (*reversed(path.parents), path):
        _safe_stat(parent)


def clear_shader_cache(state: Path) -> bool:
    """Return whether a cache was removed; refuse active sessions and redirected paths.

    Filesystem errors propagate to the caller. A failed removal may leave part of
    the regenerable cache in place, but never changes settings or prepared images.
    """
    import order1886

    state = Path(state).absolute()
    _check_ancestors(state)
    state = state.resolve()
    if not state.exists():
        return False
    _check_ancestors(state / 'session.lock')
    with order1886.session_lock(state):
        # The runtime keys the cache by the running edition's TITLE_ID; clear every edition's.
        removed = False
        for title_id in order1886.editions.TITLE_IDS:
            removed |= _clear(state, state / 'gpu' / order1886.SHADER_CACHE_ABI / 'cache' / title_id)
        return removed


def _clear(state, cache):
    _check_ancestors(cache)
    resolved = cache.resolve()
    if resolved == state or not resolved.is_relative_to(state) or resolved != cache:
        raise ValueError(f'Refusing shader-cache path outside the selected state: {cache}')
    info = _safe_stat(cache)
    if info is None:
        return False
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError(f'Shader-cache path is not a directory: {cache}')

    # Check the whole tree before deletion, including Windows junctions.
    pending = [cache]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                path = Path(entry.path)
                info = _safe_stat(path)
                if info is None:
                    raise FileNotFoundError(f'Shader-cache entry disappeared: {path}')
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
    shutil.rmtree(resolved)
    return True
