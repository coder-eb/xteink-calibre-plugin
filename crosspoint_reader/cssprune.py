"""Prune unused CSS from an EPUB.

The e-reader firmware parses every stylesheet a chapter links before it lays
the chapter out, so rules that match nothing in the book cost time for no
visual effect. This is a port of the CSS pass in the Inky browser optimizer:

    * a stylesheet that no XHTML file links (``<link>``, ``xml-stylesheet`` or
      ``@import`` from a linked sheet) is dropped, along with its ``<link>``
      tags and OPF manifest entry;
    * in the remaining sheets, a style rule is dropped when its selector can
      never match: it names a class or id that appears nowhere in the book, or
      a bare element that appears nowhere. At-rules (``@media``, ``@font-face``
      and so on) are kept whole, as are ``*``/``html``/``body`` selectors and
      anything with a pseudo-class, pseudo-element or attribute selector;
    * a stylesheet left empty is dropped like an unlinked one.

Everything here is text-level (regex), so a book with markup the lxml/DOM
route would reject is still handled, and the pass never raises on odd input:
the caller treats any failure as "leave the CSS alone".
"""

import posixpath
import re
from urllib.parse import unquote

CSS_RE = re.compile(r'\.css$', re.IGNORECASE)
XHTML_RE = re.compile(r'\.(xhtml|html|htm)$', re.IGNORECASE)

_CLASS_ATTR = re.compile(r'''\bclass\s*=\s*(?:"([^"]*)"|'([^']*)')''', re.IGNORECASE)
_ID_ATTR = re.compile(r'''\bid\s*=\s*(?:"([^"]*)"|'([^']*)')''', re.IGNORECASE)
_TAG = re.compile(r'<([A-Za-z][\w:.-]*)')
_LINK_TAG = re.compile(r'<link\b[^>]*>(?:\s*</link>)?', re.IGNORECASE)
_STYLE_PI = re.compile(r'<\?xml-stylesheet\b[^>]*\?>', re.IGNORECASE)
_STYLE_BLOCK = re.compile(r'<style\b[^>]*>(.*?)</style>', re.IGNORECASE | re.DOTALL)
_HREF = re.compile(r'''\bhref\s*=\s*(?:"([^"]*)"|'([^']*)')''', re.IGNORECASE)
_REL = re.compile(r'''\brel\s*=\s*(?:"([^"]*)"|'([^']*)')''', re.IGNORECASE)
_TYPE = re.compile(r'''\btype\s*=\s*(?:"([^"]*)"|'([^']*)')''', re.IGNORECASE)
_IMPORT = re.compile(r'''@import\s+(?:url\(\s*)?["']?([^'")\s;]+)''', re.IGNORECASE)
_COMMENT = re.compile(r'/\*.*?\*/', re.DOTALL)
_LEADING_STATEMENT = re.compile(r'\s*(@[^{};]*;)')
# CSS identifiers: a letter or underscore, then anything that is not a selector
# delimiter. (``\w`` is not enough: it excludes the combining vowel signs and
# viramas that Indic class names such as ``.தமிழ்`` are full of.)
_IDENT = r'[^\W\d][^\s.#:,>+~\[\](){}*="\'|\\]*'
_SEL_CLASS = re.compile(r'\.(' + _IDENT + ')')
_SEL_ID = re.compile(r'#(' + _IDENT + ')')
_SEL_ELEMENT = re.compile(r'(?:^|[\s>+~])([A-Za-z][\w-]*)')
_MANIFEST_ITEM = re.compile(r'<(?:\w+:)?item\b[^>]*?(?:/>|>\s*</(?:\w+:)?item>)', re.IGNORECASE)


def _attr(rx, tag):
    m = rx.search(tag)
    if not m:
        return ''
    return m.group(1) if m.group(1) is not None else (m.group(2) or '')


def resolve(base_path, href):
    """Resolve ``href`` (as written in ``base_path``) to an archive path."""
    href = unquote(href.split('#', 1)[0].split('?', 1)[0]).strip()
    if not href or '://' in href or href.startswith(('data:', 'mailto:')):
        return None
    if href.startswith('/'):
        return posixpath.normpath(href.lstrip('/'))
    base = posixpath.dirname(base_path)
    return posixpath.normpath(posixpath.join(base, href))


def _is_stylesheet_link(tag):
    rel = _attr(_REL, tag).lower().split()
    typ = _attr(_TYPE, tag).lower()
    return 'stylesheet' in rel or typ == 'text/css'


class Usage(object):
    """Every class, id and element name that occurs in the book's markup."""

    def __init__(self):
        self.classes = set()
        self.ids = set()
        self.elements = set()

    def add(self, markup):
        for m in _CLASS_ATTR.finditer(markup):
            self.classes.update((m.group(1) if m.group(1) is not None else m.group(2) or '').split())
        for m in _ID_ATTR.finditer(markup):
            value = (m.group(1) if m.group(1) is not None else m.group(2) or '').strip()
            if value:
                self.ids.add(value)
        for m in _TAG.finditer(markup):
            self.elements.add(m.group(1).lower())


def _split_selector_list(selector):
    """Split on top-level commas (not inside [...] or (...))."""
    out, cur, square, paren = [], [], 0, 0
    for ch in selector:
        if ch == '[':
            square += 1
        elif ch == ']':
            square = max(0, square - 1)
        elif ch == '(':
            paren += 1
        elif ch == ')':
            paren = max(0, paren - 1)
        if ch == ',' and not square and not paren:
            out.append(''.join(cur))
            cur = []
            continue
        cur.append(ch)
    out.append(''.join(cur))
    return out


def selector_can_match(selector, usage):
    """True unless ``selector`` provably matches nothing in the book."""
    for part in _split_selector_list(selector):
        part = part.strip()
        if not part or part in ('*', 'html', 'body'):
            return True
        classes = _SEL_CLASS.findall(part)
        ids = _SEL_ID.findall(part)
        if classes or ids:
            if all(c in usage.classes for c in classes) and all(i in usage.ids for i in ids):
                return True
            continue
        if ':' in part or '[' in part:
            return True
        elements = [e.lower() for e in _SEL_ELEMENT.findall(part)]
        if not elements or any(e in usage.elements for e in elements):
            return True
    return False


def _matching_brace(text, open_idx):
    depth = 0
    for i in range(open_idx, len(text)):
        ch = text[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return i
    return -1


def prune_rules(css, usage):
    """Return ``(new_css, rules_removed)``."""
    text = _COMMENT.sub('', css)
    out = []
    removed = 0
    pos = 0
    while pos < len(text):
        brace = text.find('{', pos)
        if brace == -1:
            out.append(text[pos:])
            break
        end = _matching_brace(text, brace)
        if end == -1:
            out.append(text[pos:])
            break
        head = text[pos:brace]
        # Peel off statement at-rules (@charset/@import ...;) that precede the
        # rule, so they are never mistaken for part of its selector.
        start = 0
        while True:
            m = _LEADING_STATEMENT.match(head, start)
            if not m:
                break
            start = m.end()
        out.append(head[:start])
        selector = head[start:].strip()
        block = head[start:] + text[brace:end + 1]
        if not selector or selector.startswith('@') or selector_can_match(selector, usage):
            out.append(block)
        else:
            removed += 1
        pos = end + 1
    return ''.join(out).strip(), removed


class CssPlan(object):
    def __init__(self):
        self.drop = set()          # archive paths of stylesheets to delete
        self.text = {}             # archive path -> pruned CSS text (kept sheets only)
        self.rules_removed = 0

    @property
    def active(self):
        return bool(self.drop) or self.rules_removed > 0


def plan_css(names, read_text):
    """Work out what to prune.

    ``names`` is the archive's file list; ``read_text(name)`` returns decoded
    text for a member. Returns a :class:`CssPlan`.
    """
    plan = CssPlan()
    css_files = [n for n in names if CSS_RE.search(n)]
    if not css_files:
        return plan
    css_set = set(css_files)

    usage = Usage()
    linked = set()
    for n in names:
        if not XHTML_RE.search(n):
            continue
        markup = read_text(n)
        usage.add(markup)
        for tag in _LINK_TAG.findall(markup):
            if _is_stylesheet_link(tag):
                target = resolve(n, _attr(_HREF, tag))
                if target in css_set:
                    linked.add(target)
        for pi in _STYLE_PI.findall(markup):
            target = resolve(n, _attr(_HREF, pi))
            if target in css_set:
                linked.add(target)
        for block in _STYLE_BLOCK.findall(markup):
            for ref in _IMPORT.findall(block):
                target = resolve(n, ref)
                if target in css_set:
                    linked.add(target)

    css_text = {n: read_text(n) for n in css_files}
    changed = True
    while changed:                      # follow @import chains
        changed = False
        for n in list(linked):
            for ref in _IMPORT.findall(css_text.get(n, '')):
                target = resolve(n, ref)
                if target in css_set and target not in linked:
                    linked.add(target)
                    changed = True

    for n in css_files:
        if n not in linked:
            plan.drop.add(n)
            continue
        pruned, removed = prune_rules(css_text[n], usage)
        plan.rules_removed += removed
        if not pruned.strip():
            plan.drop.add(n)
        else:
            plan.text[n] = pruned
    return plan


def strip_links(markup, path, dropped):
    """Remove ``<link>``/``xml-stylesheet`` references to dropped sheets."""
    if not dropped:
        return markup

    def link(m):
        tag = m.group(0)
        if _is_stylesheet_link(tag) and resolve(path, _attr(_HREF, tag)) in dropped:
            return ''
        return tag

    def pi(m):
        tag = m.group(0)
        return '' if resolve(path, _attr(_HREF, tag)) in dropped else tag

    return _STYLE_PI.sub(pi, _LINK_TAG.sub(link, markup))


def strip_manifest(opf_text, opf_path, dropped):
    """Remove OPF manifest ``<item>`` entries that point at dropped sheets."""
    if not dropped:
        return opf_text

    def item(m):
        tag = m.group(0)
        href = _attr(_HREF, tag)
        return '' if resolve(opf_path, href) in dropped else tag

    return _MANIFEST_ITEM.sub(item, opf_text)
