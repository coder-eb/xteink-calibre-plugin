"""Device-side bookkeeping that does not need Calibre: identity, scanning, cache.

Pure Python (no Calibre imports) so it can be unit tested on its own.
"""

import re
import time

ID_PREFIX = 'crosspoint-'
_NON_ID = re.compile(r'[^a-z0-9]+')


def stable_device_id(serial, host):
    """Id that keys the per-device book cache.

    The device reports a hardware ``serial`` on ``/api/status``. Using it keeps
    the cache valid when the router hands the device a new IP address; keying by
    IP (the old behaviour) made every new address look like a brand-new device
    and threw away everything the plugin knew. Falls back to the host when the
    serial is unavailable.
    """
    serial = _NON_ID.sub('-', (serial or '').strip().lower()).strip('-')
    if serial:
        return ID_PREFIX + 'sn-' + serial
    return ID_PREFIX + (host or '').replace('.', '-')


def is_legacy_id(device_id):
    """True for the old IP-based ids (``crosspoint-192-168-1-50``)."""
    return (device_id.startswith(ID_PREFIX)
            and not device_id.startswith(ID_PREFIX + 'sn-'))


class ScanResult(object):
    def __init__(self):
        self.files = []          # [(lpath, size)]
        self.failed_dirs = []    # directories that could not be listed

    @property
    def complete(self):
        return not self.failed_dirs


def scan_device(get_json, root='/', attempts=4, sleep=time.sleep, log=None):
    """List every EPUB under ``root``, retrying transient failures.

    ``get_json(path)`` returns the decoded ``/api/files`` listing for ``path``
    and raises on error. The device is a single-threaded ESP32 on Wi-Fi, so a
    request can time out for no good reason; each directory is retried with a
    growing pause. A directory that still fails is recorded in
    ``failed_dirs`` instead of being silently dropped, so the caller can avoid
    treating its books as deleted.
    """
    result = ScanResult()
    pending = [root]
    while pending:
        path = pending.pop(0)
        entries = None
        last_exc = None
        for attempt in range(attempts):
            try:
                entries = get_json(path)
                break
            except Exception as exc:    # noqa: BLE001 - any transport/JSON failure
                last_exc = exc
                if log:
                    log('[CrossPoint] listing %s failed (try %d/%d): %s'
                        % (path, attempt + 1, attempts, exc))
                if attempt + 1 < attempts:
                    sleep(0.5 * (attempt + 1))
        if entries is None:
            result.failed_dirs.append(path)
            continue
        for entry in entries:
            name = entry.get('name', '')
            if not name:
                continue
            child = '/' + name if path == '/' else path.rstrip('/') + '/' + name
            if entry.get('isDirectory'):
                pending.append(child)
            elif entry.get('isEpub'):
                result.files.append((child, entry.get('size', 0)))
    return result


def adopt_legacy(all_books, device_id, files):
    """Move known identities from old IP-keyed caches to ``device_id``.

    ``all_books`` is the whole cache (``{device_id: {lpath: entry}}``) and is
    modified in place. For each device file that has no entry yet, an entry
    from any legacy cache with the same path *and* size is adopted (same path
    and size means the same file). Adopted entries are removed from the legacy
    cache, and empty legacy caches are dropped. Returns the number adopted.
    """
    dev = all_books.setdefault(device_id, {})
    legacy_ids = [k for k in all_books if k != device_id and is_legacy_id(k)]
    adopted = 0
    for lpath, size in files:
        if lpath in dev:
            continue
        for lid in legacy_ids:
            entry = all_books[lid].get(lpath)
            if entry and entry.get('size') == size:
                dev[lpath] = entry
                del all_books[lid][lpath]
                adopted += 1
                break
    for lid in legacy_ids:
        if not all_books[lid]:
            del all_books[lid]
    return adopted


def stale_cached_files(cache_entries, scanned_paths, failed_dirs):
    """Cached files that sit under a directory we failed to list.

    Returned as ``[(lpath, size)]`` so they can still be shown (and kept in the
    cache) instead of vanishing because a request timed out.
    """
    out = []
    for lpath, entry in cache_entries.items():
        if lpath in scanned_paths:
            continue
        folder = lpath.rsplit('/', 1)[0] or '/'
        for bad in failed_dirs:
            bad = bad.rstrip('/') or '/'
            if folder == bad or (bad == '/') or folder.startswith(bad + '/'):
                out.append((lpath, entry.get('size', 0)))
                break
    return out
