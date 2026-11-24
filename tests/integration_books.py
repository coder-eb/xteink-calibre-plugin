"""Integration test for CrossPointDevice.books(), run inside Calibre's Python:

    CALIBRE_CONFIG_DIRECTORY=$(mktemp -d) QT_QPA_PLATFORM=offscreen \
        /Applications/calibre.app/Contents/MacOS/calibre-debug tests/integration_books.py

Uses an isolated config directory (never your real plugin cache) and fakes the
device's HTTP API and the Calibre library.
"""
import os
import sys
import tempfile

if 'CALIBRE_CONFIG_DIRECTORY' not in os.environ:
    os.environ['CALIBRE_CONFIG_DIRECTORY'] = tempfile.mkdtemp(prefix='calcfg-')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qt.core import QApplication  # noqa: E402
app = QApplication([])

from crosspoint_reader import metadata_cache as mc  # noqa: E402
from crosspoint_reader.driver import CrossPointDevice  # noqa: E402
from crosspoint_reader.matching import LibraryIndex  # noqa: E402

LIB = [
    {'id': 1, 'title': 'The Kite Runner', 'title_sort': 'Kite Runner, The',
     'authors': ['Khaled Hosseini'], 'author_sort': 'Hosseini, Khaled', 'uuid': 'UUID-KITE'},
]


class FakeApi(object):
    def field_for(self, field, bid):
        row = next(r for r in LIB if r['id'] == bid)
        return {'sort': row['title_sort']}.get(field, row.get(field))


TREE = {
    '/': [{'name': 'books', 'isDirectory': True}],
    '/books': [{'name': 'Fantasy', 'isDirectory': True},
               {'name': 'Kite Runner, The - Hosseini, Khaled.epub', 'size': 500, 'isEpub': True},
               {'name': 'Side Loaded, A - Writer, Some.epub', 'size': 600, 'isEpub': True}],
    '/books/Fantasy': [{'name': 'Wyrd Sisters - Pratchett, Terry.epub', 'size': 700, 'isEpub': True}],
}
state = {'failing': set(), 'tree': TREE}


def fake_get_json(path, params=None, timeout=5):
    p = (params or {}).get('path', path)
    if p in state['failing']:
        raise OSError('timed out')
    return state['tree'][p]


def make_device(host, serial):
    dev = CrossPointDevice(None)
    dev.device_host, dev.device_serial = host, serial
    dev._http_get_json = fake_get_json
    dev._build_library_index = lambda: (FakeApi(), LibraryIndex(LIB))
    return dev


def titles(bl):
    return {b.lpath: (b.title, list(b.authors), getattr(b, 'uuid', None)) for b in bl}


failures = []


def check(cond, msg):
    print(('PASS  ' if cond else 'FAIL  ') + msg)
    if not cond:
        failures.append(msg)


# A previous session at another IP remembered the Fantasy book (sent from this machine).
mc.put_many('crosspoint-192-168-1-5', [('/books/Fantasy/Wyrd Sisters - Pratchett, Terry.epub',
            {'size': 700, 'uuid': 'UUID-WYRD', 'title': 'Wyrd Sisters', 'authors': ['Terry Pratchett']})])

# --- 1. First connect at a new IP, with a serial.
dev = make_device('192.168.1.77', 'X3TEST0000000001')
check(dev._device_id() == 'crosspoint-sn-x3test0000000001', 'device id comes from the serial')
check(dev.get_device_information()[4]['main']['device_store_uuid'] == dev._device_id(),
      "Calibre's device_store_uuid is stable too")
t = titles(dev.books())
check(len(t) == 3, 'all 3 books listed (got %d)' % len(t))
check(t['/books/Kite Runner, The - Hosseini, Khaled.epub'][2] == 'UUID-KITE',
      'sort-form filename matched to the library book (uuid set)')
check(t['/books/Kite Runner, The - Hosseini, Khaled.epub'][0] == 'The Kite Runner',
      'device view shows the library title')
check(t['/books/Fantasy/Wyrd Sisters - Pratchett, Terry.epub'][2] == 'UUID-WYRD',
      'identity recovered from the old IP-keyed cache')
side = t['/books/Side Loaded, A - Writer, Some.epub']
check(side[0] == 'A Side Loaded' and side[1] == ['Some Writer'] and side[2] is None,
      'book not in library shows a clean title/author, no uuid (got %r)' % (side,))
check('crosspoint-192-168-1-5' not in mc._books(), 'adopted legacy cache was cleaned up')

# --- 2. Same device, new IP: nothing is lost.
dev2 = make_device('192.168.1.200', 'X3TEST0000000001')
t2 = titles(dev2.books())
check(t2['/books/Fantasy/Wyrd Sisters - Pratchett, Terry.epub'][2] == 'UUID-WYRD',
      'identity survives a new IP address')

# --- 3. A folder times out: its book must stay listed and cached.
state['failing'] = {'/books/Fantasy'}
dev2.books  # noqa: B018
t3 = titles(dev2.books())
check('/books/Fantasy/Wyrd Sisters - Pratchett, Terry.epub' in t3,
      'book in an unreadable folder is still shown (from cache)')
check(t3['/books/Fantasy/Wyrd Sisters - Pratchett, Terry.epub'][2] == 'UUID-WYRD',
      '... with its identity intact')
check('/books/Fantasy/Wyrd Sisters - Pratchett, Terry.epub' in mc.get_all(dev2._device_id()),
      'a failed listing does not wipe that folder from the cache')

# --- 4. The book is genuinely deleted: now it goes.
state['failing'] = set()
state['tree'] = dict(TREE, **{'/books/Fantasy': []})
t4 = titles(dev2.books())
check('/books/Fantasy/Wyrd Sisters - Pratchett, Terry.epub' not in t4, 'deleted book is gone from the list')
check('/books/Fantasy/Wyrd Sisters - Pratchett, Terry.epub' not in mc.get_all(dev2._device_id()),
      '... and pruned from the cache')

print('\n%s' % ('ALL PASSED' if not failures else '%d FAILED' % len(failures)))
sys.exit(1 if failures else 0)
