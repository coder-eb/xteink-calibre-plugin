"""Match files on the device to books in the Calibre library.

The device only stores raw files, so Calibre has nothing but a file name (and
folder) to go on when it decides which library books are "on device". Names
come from the send-to-device template, which commonly renders Calibre's *sort*
forms::

    Kite Runner, The - Hosseini, Khaled.epub      (title_sort - author_sort)
    Johannes Cabal the Necromancer - Howard, Jonathan L_.epub
    The Mahabharata - Ramesh Menon.epub           (title - authors)

so a plain "file name == library title" comparison misses many of them. This
module does the comparison on a normalized form that ignores case, accents,
punctuation (Calibre replaces characters such as ``.`` or ``?`` with ``_`` in
file names) and the "Title, The" article inversion, and uses the author, when
the name or folder carries one, to tell same-titled books apart.

Pure Python with no Calibre imports, so it can be unit tested on its own.
"""

import re
import unicodedata

# "Kite Runner, The" -> "The Kite Runner". Only the article words Calibre's
# title sorting moves to the end.
_INVERTED = re.compile(
    r"^(?P<rest>.+?),\s*(?P<art>the|a|an|der|die|das|le|la|les|el|los|las|il|lo|l')\s*$",
    re.IGNORECASE)
_QUOTES = re.compile(r"['‘’‛`´]")
# Words that make a "- <words>" tail look like part of a title rather than an author.
_TITLE_WORDS = frozenset(
    'the a an of and in on to for with from at by or vs part book volume vol'.split())
MIN_PREFIX_LEN = 24


def fold(text):
    """Lower-case and drop accents from Latin letters.

    Combining marks that follow a non-Latin base (the vowel signs and viramas
    of Tamil, Devanagari and so on) are kept: they are part of the letters.
    """
    if not text:
        return ''
    out = []
    for ch in unicodedata.normalize('NFKD', text):
        if unicodedata.combining(ch) and out and ord(out[-1]) < 0x250:
            continue
        out.append(ch)
    return ''.join(out).casefold()


def norm(text):
    """Comparison key: folded, '&' -> 'and', quotes dropped, punctuation -> space."""
    text = fold(text).replace('&', ' and ')
    text = _QUOTES.sub('', text)
    out = []
    for ch in text:
        if ch.isalnum() or unicodedata.category(ch) in ('Mn', 'Mc'):
            out.append(ch)
        else:
            out.append(' ')
    return ' '.join(''.join(out).split())


def uninvert(text):
    """'Kite Runner, The' -> 'The Kite Runner'; anything else is returned as is."""
    m = _INVERTED.match((text or '').strip())
    if not m:
        return (text or '').strip()
    art = m.group('art')
    sep = '' if art.endswith("'") else ' '
    return '%s%s%s' % (art, sep, m.group('rest').strip())


def _keys(text):
    """Normalized keys for a title: as written and with the article restored."""
    keys = []
    for variant in (text, uninvert(text)):
        k = norm(variant)
        if k and k not in keys:
            keys.append(k)
    return keys


def flip_name(name):
    """'Hosseini, Khaled' -> 'Khaled Hosseini' (only for exactly one comma)."""
    parts = [p.strip() for p in (name or '').split(',')]
    if len(parts) == 2 and parts[0] and parts[1]:
        return '%s %s' % (parts[1], parts[0])
    return (name or '').strip()


def _looks_like_author(text):
    """Is ``text`` plausibly an author name rather than the rest of a title?"""
    text = (text or '').strip()
    if not text or any(c.isdigit() for c in text):
        return False
    if text.count(',') == 1:                       # "Last, First" (author_sort)
        last, first = [p.strip() for p in text.split(',')]
        return bool(last and first and len(text.split()) <= 6)
    words = text.split()
    if not 2 <= len(words) <= 4:
        return False
    return not any(w.lower().strip('.,') in _TITLE_WORDS for w in words)


def split_filename(stem):
    """Split a file-name stem into ``(title_candidates, author_text)``.

    ``title_candidates`` are the strings that may be the title (most likely
    first); ``author_text`` is the part that looks like an author, or ''.
    Handles ``Title - Author`` and ``Author - Title``.
    """
    stem = (stem or '').strip()
    parts = [p.strip() for p in stem.split(' - ') if p.strip()]
    titles = [stem]
    author = ''
    if len(parts) >= 2:
        head, tail = ' - '.join(parts[:-1]), parts[-1]
        if _looks_like_author(tail):
            titles = [head, stem]
            author = tail
        elif parts[0].count(',') == 1 and _looks_like_author(parts[0]):
            # Author-first only when unmistakable ("Last, First - Title"):
            # "Harry Potter - The Stone" must stay a title.
            titles = [' - '.join(parts[1:]), stem]
            author = parts[0]
        else:
            titles = [stem, head, ' - '.join(parts[1:])]
    return titles, author


def parse_filename(stem):
    """Best-effort ``(title, [authors])`` for a file that is not in the library."""
    titles, author = split_filename(stem)
    title = uninvert(titles[0]) or stem
    return title, ([flip_name(author)] if author else [])


class Match(object):
    __slots__ = ('book_id', 'how')

    def __init__(self, book_id, how):
        self.book_id = book_id
        self.how = how

    def __repr__(self):
        return 'Match(%r, %r)' % (self.book_id, self.how)


class LibraryIndex(object):
    """Title index over the library.

    ``rows`` is an iterable of dicts with ``id``, ``title``, ``title_sort``
    (optional), ``authors`` (list) and ``author_sort`` (optional).
    """

    def __init__(self, rows):
        self.by_key = {}
        self.books = {}
        for row in rows:
            bid = row['id']
            authors = list(row.get('authors') or [])
            self.books[bid] = {
                'title': row.get('title') or '',
                'authors': authors,
                'author_tokens': self._author_token_sets(authors, row.get('author_sort')),
            }
            for text in (row.get('title'), row.get('title_sort')):
                for k in _keys(text or ''):
                    self.by_key.setdefault(k, [])
                    if bid not in self.by_key[k]:
                        self.by_key[k].append(bid)
        self._prefix_keys = sorted(self.by_key, key=len, reverse=True)

    @staticmethod
    def _author_token_sets(authors, author_sort):
        sets = []
        for a in authors:
            toks = frozenset(norm(a).split())
            if toks:
                sets.append(toks)
        # author_sort may join several authors with ' & '; each is "Last, First".
        for chunk in (author_sort or '').split('&'):
            toks = frozenset(norm(chunk).split())
            if toks and toks not in sets:
                sets.append(toks)
        return sets

    def _author_hits(self, bid, tokens):
        """Does any author of ``bid`` have all its name tokens in ``tokens``?"""
        return any(s <= tokens for s in self.books[bid]['author_tokens'])

    @staticmethod
    def _options(stem):
        """Ways to read a file-name stem as (title text, author text).

        The whole stem is tried first (a title may itself contain " - "), then
        ``Title - Author`` and ``Author - Title``. Which reading is right is
        decided by the library: a title that exists *and* whose author checks
        out. No guessing about what "looks like" an author.
        """
        parts = [p.strip() for p in stem.split(' - ') if p.strip()]
        options = [(stem, '')]
        if len(parts) >= 2:
            options.append((' - '.join(parts[:-1]), parts[-1]))
            options.append((' - '.join(parts[1:]), parts[0]))
        return options

    def _prefix_hits(self, text):
        """Books whose title starts with ``text`` (Calibre truncates long names)."""
        hits = []
        for k in _keys(text):
            if len(k) < MIN_PREFIX_LEN:
                continue
            for key in self._prefix_keys:
                if key.startswith(k):
                    for bid in self.by_key[key]:
                        if bid not in hits:
                            hits.append(bid)
            if hits:
                break
        return hits

    def match(self, lpath):
        """Return a :class:`Match` for a device path, or None if unsure."""
        norm_path = lpath.replace('\\', '/')
        stem = norm_path.rsplit('/', 1)[-1]
        if '.' in stem:
            stem = stem.rsplit('.', 1)[0]
        folder_tokens = set()
        for comp in norm_path.split('/')[:-1]:
            folder_tokens.update(norm(comp).split())
        options = self._options(stem)

        for how, finder in (('title', lambda t: [b for k in _keys(t) for b in self.by_key.get(k, ())]),
                            ('prefix', self._prefix_hits)):
            for text, other in options:
                candidates = []
                for bid in finder(text):
                    if bid not in candidates:
                        candidates.append(bid)
                if not candidates:
                    continue
                if other:
                    # The name claims an author: a same-titled book by someone
                    # else must not be marked on-device. If the claim does not
                    # hold, this reading is wrong (e.g. it was a subtitle).
                    claim = frozenset(norm(other).split()) | folder_tokens
                    candidates = [b for b in candidates if self._author_hits(b, claim)]
                    if not candidates:
                        continue
                if len(candidates) == 1:
                    return Match(candidates[0], how)
                tokens = frozenset(norm(stem).split()) | folder_tokens
                picked = self._pick(candidates, tokens, how)
                if picked is not None:
                    return picked
        return None

    def _pick(self, candidates, tokens, how):
        narrowed = [b for b in candidates if self._author_hits(b, tokens)]
        if len(narrowed) == 1:
            return Match(narrowed[0], how + '+author')
        return None   # ambiguous: do not guess
