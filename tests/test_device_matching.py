"""Tests for matching device files to library books, and for device scanning,
device identity and cache migration."""
import sys
import types
import unittest
from pathlib import Path

plugin = types.ModuleType('test_xteink_match')
plugin.__path__ = [str(Path(__file__).resolve().parents[1] / 'crosspoint_reader')]
sys.modules[plugin.__name__] = plugin
from test_xteink_match import devicelogic, matching
from test_xteink_match.matching import LibraryIndex, fold, norm, parse_filename, uninvert


def row(bid, title, authors, title_sort=None, author_sort=None):
    return {'id': bid, 'title': title, 'authors': authors,
            'title_sort': title_sort or title, 'author_sort': author_sort or ''}


LIBRARY = [
    row(1, 'The Kite Runner', ['Khaled Hosseini'], 'Kite Runner, The', 'Hosseini, Khaled'),
    row(2, 'A Little Life', ['Hanya Yanagihara'], 'Little Life, A', 'Yanagihara, Hanya'),
    row(3, 'Johannes Cabal the Necromancer', ['Jonathan L. Howard'], None, 'Howard, Jonathan L.'),
    row(4, "Harry Potter and the Sorcerer's Stone", ['J. K. Rowling'], None, 'Rowling, J. K.'),
    row(5, 'The Villainess Malfoy', ['Gosokdoru'], 'Villainess Malfoy, The', 'Gosokdoru'),
    row(6, 'Shōgun', ['James Clavell'], None, 'Clavell, James'),
    row(7, 'The Mahabharata', ['Ramesh Menon'], 'Mahabharata, The', 'Menon, Ramesh'),
    row(8, 'Mahabharata', ['C. Rajagopalachari'], None, 'Rajagopalachari, C.'),
    row(9, 'Anna Karenina', ['Leo Tolstoy'], None, 'Tolstoy, Leo'),
    row(10, 'Anna Karenina', ['Leo Tolstoy'], None, 'Tolstoy, Leo'),     # exact duplicate
    row(11, 'It', ['Stephen King'], None, 'King, Stephen'),
    row(12, 'It', ['Someone Else'], None, 'Else, Someone'),
    row(13, 'Wolf Hall: A Novel of Thomas Cromwell', ['Hilary Mantel'], None, 'Mantel, Hilary'),
    row(14, 'The Extraordinarily Long Title That Calibre Will Truncate When Saving',
        ['Some Author'], None, 'Author, Some'),
    row(15, 'தமிழ் இலக்கியம்', ['கல்கி'], None, 'கல்கி'),
]
INDEX = LibraryIndex(LIBRARY)


def match(path):
    m = INDEX.match(path)
    return m.book_id if m else None


class NormTests(unittest.TestCase):
    def test_fold_drops_latin_accents_only(self):
        self.assertEqual(fold('Shōgun'), 'shogun')
        self.assertEqual(fold('Ça va'), 'ca va')
        tamil = 'தமிழ்'
        self.assertEqual(fold(tamil), tamil)        # vowel signs/pulli kept

    def test_norm_ignores_punctuation_and_quotes(self):
        self.assertEqual(norm("Harry Potter & the Sorcerer's Stone"),
                         'harry potter and the sorcerers stone')
        self.assertEqual(norm('Howard, Jonathan L_'), 'howard jonathan l')
        self.assertEqual(norm('Jonathan L. Howard'), 'jonathan l howard')

    def test_uninvert(self):
        self.assertEqual(uninvert('Kite Runner, The'), 'The Kite Runner')
        self.assertEqual(uninvert('Little Life, A'), 'A Little Life')
        self.assertEqual(uninvert('Smith, John'), 'Smith, John')   # not an article
        self.assertEqual(uninvert('Hello'), 'Hello')


class MatchTests(unittest.TestCase):
    def test_sort_form_names(self):
        self.assertEqual(match('/books/Historical Fiction/Kite Runner, The - Hosseini, Khaled.epub'), 1)
        self.assertEqual(match('/books/Modern Literary Fiction/Little Life, A - Yanagihara, Hanya.epub'), 2)
        self.assertEqual(match('/books/Fan Fiction/Villainess Malfoy, The - Gosokdoru.epub'), 5)

    def test_underscore_substitutions(self):
        self.assertEqual(match('/books/Fantasy/Johannes Cabal the Necromancer - Howard, Jonathan L_.epub'), 3)
        self.assertEqual(match("/books/Young Adult/Harry Potter and the Sorcerer's Stone - Rowling, J. K_.epub"), 4)

    def test_accents(self):
        self.assertEqual(match('/books/Classics/Shogun - Clavell, James.epub'), 6)

    def test_plain_title_only_and_title_author(self):
        self.assertEqual(match('/books/Kite Runner, The.epub'), 1)
        self.assertEqual(match('/books/The Kite Runner.epub'), 1)
        self.assertEqual(match('/books/The Kite Runner - Khaled Hosseini.epub'), 1)
        self.assertEqual(match('/books/Khaled Hosseini - The Kite Runner.epub'), 1)

    def test_same_title_different_author_is_told_apart(self):
        self.assertEqual(match('/books/It - King, Stephen.epub'), 11)
        self.assertEqual(match('/books/It - Else, Someone.epub'), 12)

    def test_name_with_wrong_author_is_not_matched(self):
        # Library has an "It", but by neither of these people.
        self.assertIsNone(match('/books/It - Nobody, Known.epub'))

    def test_similar_titles_are_not_confused(self):
        self.assertEqual(match('/books/Classics/The Mahabharata - Ramesh Menon.epub'), 7)
        self.assertEqual(match('/books/Mahabharata, The - Menon, Ramesh.epub'), 7)
        self.assertEqual(match('/books/Mahabharata - Rajagopalachari, C_.epub'), 8)

    def test_indistinguishable_duplicates_are_left_alone(self):
        self.assertIsNone(match('/books/Classics/Anna Karenina - Tolstoy, Leo.epub'))

    def test_author_in_folder_disambiguates(self):
        self.assertEqual(match('/books/Stephen King/It.epub'), 11)
        self.assertEqual(match('/books/Someone Else/It.epub'), 12)
        self.assertIsNone(match('/books/It.epub'))            # ambiguous, no hint

    def test_subtitle_after_dash_is_not_taken_for_an_author(self):
        idx = LibraryIndex([row(1, 'Harry Potter - The Sorcerer', ['J. K. Rowling'])])
        self.assertEqual(idx.match('/books/Harry Potter - The Sorcerer.epub').book_id, 1)

    def test_calibre_truncated_name_matches_by_unique_prefix(self):
        self.assertEqual(match('/books/The Extraordinarily Long Title That Calibre.epub'), 14)

    def test_short_prefix_is_not_enough(self):
        self.assertIsNone(match('/books/The Extra.epub'))

    def test_unknown_book(self):
        self.assertIsNone(match('/books/Something Not In The Library - Nobody, Known.epub'))

    def test_windows_separators(self):
        self.assertEqual(match('\\books\\Fantasy\\Kite Runner, The - Hosseini, Khaled.epub'), 1)

    def test_indic_titles(self):
        self.assertEqual(match('/books/தமிழ் இலக்கியம் - கல்கி.epub'), 15)
        self.assertEqual(match('/books/தமிழ் இலக்கியம்.epub'), 15)


class ParseFilenameTests(unittest.TestCase):
    def test_sort_form(self):
        self.assertEqual(parse_filename('Kite Runner, The - Hosseini, Khaled'),
                         ('The Kite Runner', ['Khaled Hosseini']))

    def test_title_author(self):
        self.assertEqual(parse_filename('The Mahabharata - Ramesh Menon'),
                         ('The Mahabharata', ['Ramesh Menon']))

    def test_title_only(self):
        self.assertEqual(parse_filename('Dune'), ('Dune', []))

    def test_subtitle_not_an_author(self):
        self.assertEqual(parse_filename("Harry Potter - The Sorcerer's Stone"),
                         ("Harry Potter - The Sorcerer's Stone", []))


class DeviceIdTests(unittest.TestCase):
    def test_serial_wins_over_ip(self):
        a = devicelogic.stable_device_id('X3TEST0000000001', '192.168.1.50')
        b = devicelogic.stable_device_id('X3TEST0000000001', '192.168.1.99')
        self.assertEqual(a, b)
        self.assertFalse(devicelogic.is_legacy_id(a))

    def test_falls_back_to_host(self):
        self.assertEqual(devicelogic.stable_device_id(None, '192.168.1.50'),
                         'crosspoint-192-168-1-50')
        self.assertEqual(devicelogic.stable_device_id('  ', '192.168.4.1'),
                         'crosspoint-192-168-4-1')
        self.assertTrue(devicelogic.is_legacy_id('crosspoint-192-168-1-50'))

    def test_different_devices_differ(self):
        self.assertNotEqual(devicelogic.stable_device_id('AAA1', 'h'),
                            devicelogic.stable_device_id('BBB2', 'h'))


class FakeDevice(object):
    """Fake /api/files: dict of directory -> entries, with optional failures."""

    def __init__(self, tree, fail=None):
        self.tree, self.fail, self.calls = tree, dict(fail or {}), []

    def __call__(self, path):
        self.calls.append(path)
        left = self.fail.get(path, 0)
        if left:
            self.fail[path] = left - 1 if left != 99 else 99
            raise OSError('timed out')
        return self.tree[path]


TREE = {
    '/': [{'name': 'books', 'isDirectory': True}, {'name': 'notes.txt', 'size': 3, 'isEpub': False},
          {'name': 'top.epub', 'size': 10, 'isEpub': True}],
    '/books': [{'name': 'Fantasy', 'isDirectory': True}, {'name': 'a.epub', 'size': 11, 'isEpub': True}],
    '/books/Fantasy': [{'name': 'b.epub', 'size': 12, 'isEpub': True}],
}


class ScanTests(unittest.TestCase):
    def test_lists_epubs_recursively_only(self):
        res = devicelogic.scan_device(FakeDevice(TREE), sleep=lambda s: None)
        self.assertTrue(res.complete)
        self.assertEqual(sorted(res.files), [('/books/Fantasy/b.epub', 12), ('/books/a.epub', 11),
                                             ('/top.epub', 10)])

    def test_transient_failure_is_retried(self):
        dev = FakeDevice(TREE, fail={'/books/Fantasy': 2})
        res = devicelogic.scan_device(dev, sleep=lambda s: None)
        self.assertTrue(res.complete)
        self.assertIn(('/books/Fantasy/b.epub', 12), res.files)
        self.assertEqual(dev.calls.count('/books/Fantasy'), 3)

    def test_persistent_failure_is_reported_not_hidden(self):
        dev = FakeDevice(TREE, fail={'/books/Fantasy': 99})
        res = devicelogic.scan_device(dev, attempts=3, sleep=lambda s: None)
        self.assertFalse(res.complete)
        self.assertEqual(res.failed_dirs, ['/books/Fantasy'])
        self.assertNotIn(('/books/Fantasy/b.epub', 12), res.files)
        self.assertIn(('/books/a.epub', 11), res.files)       # the rest still listed

    def test_logs_failures(self):
        logged = []
        devicelogic.scan_device(FakeDevice(TREE, fail={'/books': 1}), sleep=lambda s: None,
                                log=logged.append)
        self.assertTrue(any('/books' in m for m in logged))

    def test_stale_cached_files_under_failed_dir(self):
        cache = {'/books/Fantasy/b.epub': {'size': 12}, '/books/a.epub': {'size': 11},
                 '/books/Fantasy/deep/c.epub': {'size': 5}, '/other/d.epub': {'size': 1}}
        out = devicelogic.stale_cached_files(cache, {'/books/a.epub'}, ['/books/Fantasy'])
        self.assertEqual(sorted(out), [('/books/Fantasy/b.epub', 12), ('/books/Fantasy/deep/c.epub', 5)])


class AdoptLegacyTests(unittest.TestCase):
    def entry(self, size, uuid):
        return {'size': size, 'uuid': uuid, 'title': 't', 'authors': ['a']}

    def test_adopts_same_path_and_size_and_cleans_up(self):
        books = {
            'crosspoint-192-168-1-5': {'/books/a.epub': self.entry(100, 'U1'),
                                       '/books/gone.epub': self.entry(7, 'U9')},
            'crosspoint-192-168-1-6': {'/books/b.epub': self.entry(200, 'U2'),
                                       '/books/c.epub': self.entry(999, 'U3')},
            'crosspoint-192-168-1-7': {'/books/only-here.epub': self.entry(1, 'U8')},
        }
        files = [('/books/a.epub', 100), ('/books/b.epub', 200), ('/books/c.epub', 300)]
        n = devicelogic.adopt_legacy(books, 'crosspoint-sn-x3', files)
        self.assertEqual(n, 2)
        dev = books['crosspoint-sn-x3']
        self.assertEqual(dev['/books/a.epub']['uuid'], 'U1')
        self.assertEqual(dev['/books/b.epub']['uuid'], 'U2')
        self.assertNotIn('/books/c.epub', dev)            # size differs: a different file
        # Adopted entries leave the legacy caches; unrelated ones stay.
        self.assertNotIn('/books/a.epub', books['crosspoint-192-168-1-5'])
        self.assertIn('/books/gone.epub', books['crosspoint-192-168-1-5'])
        self.assertIn('/books/c.epub', books['crosspoint-192-168-1-6'])

    def test_empty_legacy_cache_is_dropped(self):
        books = {'crosspoint-192-168-1-5': {'/books/a.epub': self.entry(100, 'U1')}}
        devicelogic.adopt_legacy(books, 'crosspoint-sn-x3', [('/books/a.epub', 100)])
        self.assertNotIn('crosspoint-192-168-1-5', books)

    def test_existing_entry_is_not_overwritten(self):
        books = {'crosspoint-sn-x3': {'/books/a.epub': self.entry(100, 'NEW')},
                 'crosspoint-192-168-1-5': {'/books/a.epub': self.entry(100, 'OLD')}}
        n = devicelogic.adopt_legacy(books, 'crosspoint-sn-x3', [('/books/a.epub', 100)])
        self.assertEqual(n, 0)
        self.assertEqual(books['crosspoint-sn-x3']['/books/a.epub']['uuid'], 'NEW')

    def test_never_touches_other_serial_devices(self):
        books = {'crosspoint-sn-other': {'/books/a.epub': self.entry(100, 'U1')}}
        n = devicelogic.adopt_legacy(books, 'crosspoint-sn-x3', [('/books/a.epub', 100)])
        self.assertEqual(n, 0)
        self.assertIn('/books/a.epub', books['crosspoint-sn-other'])


if __name__ == '__main__':
    unittest.main()
