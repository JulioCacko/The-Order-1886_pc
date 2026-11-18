"""The Order's regenerable native shader cache: clear, seed-import, migrate, export.

The runtime replays cached pipelines while the game boots (its "Building shader
cache" warm-up), but only for pipelines some session already recorded. These
helpers give a fresh install something to replay: the package may ship a seed
bundle under <install>/shader-cache/<TITLE_ID>/ (captured by playing the game,
see export_shader_cache_seed) which import_shader_cache_seeds places into the
per-title cache before the first launch. The engine's own Shader::Profile check
still decides whether the seed applies to the running GPU/driver; on a mismatch
it rebuilds exactly as it does today.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import time


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


def _abi(explicit=None):
    if explicit:
        return explicit
    import order1886

    return order1886.SHADER_CACHE_ABI


def title_cache_dir(state, title_id, abi=None):
    """Where the runtime keys this edition's pipeline cache (see order1886.py's
    ORDER1886_GPU_USER_DIR); the engine adds 'cache/<TITLE_ID>' below it."""
    return Path(state) / 'gpu' / _abi(abi) / 'cache' / title_id


def ensure_cache_home(state) -> Path:
    """Create the GPU cache home the launcher points ORDER1886_GPU_USER_DIR at.

    path_util.cpp falls back to the shared per-user directory (XDG / %APPDATA%
    shadPS4) when that path does not exist, which quietly breaks the promise
    that caches live with the package — and makes a shipped seed bundle
    unimportable. Always called before the runtime starts.
    """
    import order1886

    home = Path(state) / 'gpu' / order1886.SHADER_CACHE_ABI
    (home / 'cache').mkdir(parents=True, exist_ok=True)
    return home


def migrate_shared_caches(state, log=print) -> int:
    """No longer adopts anything; kept so older callers keep working.

    v0.2.24-v0.2.27 copied the shared per-user cache (XDG / %APPDATA% shadPS4)
    into the package. That folder can only hold caches written by a different
    build: a pre-v0.2.24 package or a local engine build. Since v0.2.26 their
    shader metas are refused anyway (meta format 11), so adopting them gained
    nothing but their graphics-pipeline keys, and replaying foreign keys during
    WarmUp crashes RADV (SIGSEGV in CreateCachedGraphicsPipeline, exit 139) on
    every boot. The old folder is left untouched; the cache rebuilds by playing.
    """
    return 0


# Frames that put a host fault inside the boot-time pipeline-cache replay.
_WARMUP_FAULT_FRAMES = ('PipelineCache6WarmUp', 'PipelineCache::WarmUp',
                        'LoadGraphicsPipeline', 'CreateCachedGraphicsPipeline')


def _warmup_crash(report):
    """Return the crashed boot's log text if the run died replaying the cache."""
    if report.get('status') != 'failed' or not report.get('log'):
        return None
    try:
        text = Path(report['log']).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None
    _, fault, backtrace = text.rpartition('Host fault')
    if not fault or not any(frame in backtrace for frame in _WARMUP_FAULT_FRAMES):
        return None
    return backtrace


def quarantine_crashed_cache(state, log=print):
    """Set aside a pipeline cache whose replay crashed the previous boot.

    WarmUp replays every recorded pipeline before the first frame, so a single
    entry the driver cannot rebuild crashes every launch, forever. When
    logs/last-run.json says the last boot failed with a host fault inside that
    replay, the title's cache is renamed to <TITLE_ID>.crashed-<run> (the cache
    is regenerable; nothing is deleted except an older quarantine of the same
    title) and the next boot starts clean. Returns the quarantine path or None.
    """
    state = Path(state).absolute()
    try:
        report = json.loads((state / 'logs' / 'last-run.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    title_id = report.get('title_id')
    abi = report.get('shader_cache_abi') or None
    if not isinstance(title_id, str) or not title_id.isalnum() or _warmup_crash(report) is None:
        return None
    cache = title_cache_dir(state, title_id, abi)
    _check_ancestors(cache)
    if not cache.is_dir():
        return None
    run = ''.join(ch for ch in str(report.get('started_utc') or 'last') if ch.isalnum())
    target = cache.with_name(f'{title_id}.crashed-{run}')
    for old in cache.parent.glob(f'{title_id}.crashed-*'):
        if old != target:
            _check_ancestors(old)
            if old.is_dir() and not old.is_symlink():
                shutil.rmtree(old)
    if target.exists():
        return None  # this crash was already handled; the cache here is newer
    os.replace(cache, target)
    log(f'order1886 cache: the last boot crashed replaying the {title_id} pipeline cache; '
        f'moved it to {target.name} so this launch rebuilds it')
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def export_shader_cache_seed(cache: Path, out: Path, title_id: str, log=print, abi=None) -> Path:
    """Bundle a captured cache directory as <out>/blobs + <out>/bundle.json.

    Run against <state>/gpu/<abi>/cache/<TITLE_ID> after playing; the driver's
    own binary files (*.bin, keyed by the capturing device) are left out — every
    other blob is engine-SPIR-V and pipeline keys, which replay on any device
    whose Shader::Profile matches (the runtime enforces that at load).
    """
    abi = _abi(abi)
    cache, out = Path(cache), Path(out)
    blobs = out / 'blobs'
    if blobs.exists():
        shutil.rmtree(blobs)
    blobs.mkdir(parents=True)
    files = {}
    for entry in sorted(cache.iterdir()):
        # *.bin are driver pipeline binaries keyed by the capturing driver; the
        # profile is deliberately shipped: a matching device replays the seed on
        # its very first boot, and on a mismatching one the engine's own
        # CheckCacheProfile discards and rebuilds, exactly as with an empty cache.
        if not entry.is_file() or (entry.suffix == '.bin' and entry.name != 'profile.bin'):
            continue
        shutil.copy2(entry, blobs / entry.name)
        files[entry.name] = _sha256(entry)
    manifest = {
        'title_id': title_id,
        'shader_cache_abi': abi,
        'created_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'files': files,
    }
    (out / 'bundle.json').write_text(json.dumps(manifest, indent=1), encoding='utf-8')
    log(f'shader cache seed: {len(files)} blobs -> {out}')
    return out


def import_shader_cache_seeds(state, install_root=None, log=print, abi=None) -> list:
    """Place shipped seed bundles into empty per-title caches, before first play.

    A bundle is <install>/shader-cache/<TITLE_ID>/{bundle.json,blobs/} written by
    export_shader_cache_seed. Imports are all-or-nothing per bundle (verified
    against the manifest hashes), go through a staging directory and a rename,
    and never touch a cache that already has a profile.bin (a real session ran
    there). An ABI-tagged bundle that does not match this build is refused.
    Returns one receipt dict per bundle seen.
    """
    abi = _abi(abi)
    state = Path(state).absolute()
    roots = [Path(install_root)] if install_root else []
    roots += [state.parent.parent, Path.cwd()]
    seed_home = next((root / 'shader-cache' for root in roots
                      if (root / 'shader-cache').is_dir()), None)
    receipts = []
    if seed_home is None:
        return receipts
    for bundle in sorted(p for p in seed_home.iterdir() if p.is_dir()):
        title_id = bundle.name
        receipt = {'title_id': title_id, 'bundle': str(bundle)}
        receipts.append(receipt)
        manifest_path = bundle / 'bundle.json'
        if not manifest_path.is_file():
            receipt['skipped'] = 'no bundle.json'
            continue
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest.get('shader_cache_abi') != abi:
            receipt['skipped'] = f"built for {manifest.get('shader_cache_abi')}"
            continue
        target = title_cache_dir(state, title_id, abi)
        _check_ancestors(target)
        if (target / 'profile.bin').exists():
            receipt['skipped'] = 'cache already in use'
            continue
        blobs = bundle / 'blobs'
        staged = target.with_name(target.name + '.importing')
        try:
            if staged.exists():
                shutil.rmtree(staged)
            staged.mkdir(parents=True)
            for name, digest in manifest['files'].items():
                source = blobs / name
                if not source.is_file() or _sha256(source) != digest:
                    raise ValueError(f'seed bundle blob failed verification: {title_id}/{name}')
                shutil.copy2(source, staged / name)
            if target.exists():
                shutil.rmtree(target)  # never: only an unprofiled partial dir lives here
            os.replace(staged, target)
            receipt['imported'] = len(manifest['files'])
            log(f'shader cache seed: imported {receipt["imported"]} blobs for {title_id}')
        except (OSError, ValueError) as error:  # read-only media, bad manifest, failed hashes
            receipt['skipped'] = str(error) if isinstance(error, ValueError) \
                else f'import failed: {error}'
        finally:
            shutil.rmtree(staged, ignore_errors=True)
    receipt_path = state / 'gpu' / 'shader-cache-import.json'
    try:
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipts, indent=1), encoding='utf-8')
    except OSError:
        pass
    return receipts


def prepare_cache_for_launch(state, install_root=None, log=print):
    """One launch-time step: keep the cache in the package, set aside a cache
    whose replay crashed the last boot, and import any shipped seed. Never
    fails a launch over cache work."""
    try:
        ensure_cache_home(state)
        if quarantine_crashed_cache(state, log):
            return []  # a seed may be what crashed; this boot rebuilds from scratch
        return import_shader_cache_seeds(state, install_root, log)
    except Exception as error:  # noqa: BLE001 - a broken seed must not stop the game
        log(f'order1886 cache: {error}')
        return []


def main(argv=None):
    """Capture or install a seed bundle without the launcher:

    export:  order1886_cache.py --export <state>/gpu/<abi>/cache/<TITLE_ID> \
                 --out <install>/shader-cache/<TITLE_ID>
    import:  order1886_cache.py --import --state <install>/user/order1886
    """
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--export', type=Path, help='cache directory captured by playing')
    mode.add_argument('--import', dest='do_import', action='store_true',
                      help='import every bundle under <install>/shader-cache')
    parser.add_argument('--out', type=Path, help='bundle directory for --export')
    parser.add_argument('--title', help='TITLE_ID of the --export cache (its folder name)')
    parser.add_argument('--state', type=Path, help='launcher state dir (user/order1886)')
    parser.add_argument('--install', type=Path, help='package root holding shader-cache/')
    parser.add_argument('--abi', default=None, help='shader cache ABI (default: this build)')
    args = parser.parse_args(argv)
    if args.export:
        if not args.out or not args.title:
            parser.error('--export needs --out and --title')
        export_shader_cache_seed(args.export, args.out, args.title, abi=args.abi)
    else:
        if not args.state:
            parser.error('--import needs --state')
        receipts = import_shader_cache_seeds(args.state, args.install, abi=args.abi)
        for receipt in receipts:
            print(json.dumps(receipt))
        if not receipts:
            print('no bundles under <install>/shader-cache')


if __name__ == '__main__':
    main()
