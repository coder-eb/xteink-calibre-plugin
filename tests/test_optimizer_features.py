"""Tests for the 4-level tone mapping, cover handling, CSS pruning and
section-size options added to the optimizer."""
import io
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path

# Import the optimizer without initializing the Calibre device driver.
plugin = types.ModuleType('test_xteink_reader')
plugin.__path__ = [str(Path(__file__).resolve().parents[1] / 'crosspoint_reader')]
sys.modules[plugin.__name__] = plugin
from test_xteink_reader import cssprune, textsplit
from test_xteink_reader.optimizer import (
    DEVICE_PROFILES, GRAY_LEVELS, Options, _find_cover_path, _tone_lut,
    optimize_epub, process_image)

X3 = DEVICE_PROFILES['X3']


def _png(size, color):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, 'PNG')
    return buf.getvalue()


def _decode(jpeg):
    from PIL import Image
    return Image.open(io.BytesIO(jpeg))


class ToneTests(unittest.TestCase):
    def test_no_op_is_none(self):
        self.assertIsNone(_tone_lut(1.0, False))
        self.assertIsNone(_tone_lut(0, False))

    def test_quantize_snaps_to_four_levels(self):
        lut = _tone_lut(1.0, True)
        self.assertEqual(set(lut), set(GRAY_LEVELS))
        self.assertEqual((lut[0], lut[63], lut[64], lut[127], lut[128],
                          lut[191], lut[192], lut[255]),
                         (0, 0, 85, 85, 170, 170, 255, 255))

    def test_contrast_is_monotonic_and_clamped(self):
        lut = _tone_lut(1.2, False)
        self.assertEqual(lut[128], 128)
        self.assertEqual((lut[0], lut[255]), (0, 255))
        self.assertTrue(all(a <= b for a, b in zip(lut, lut[1:])))
        self.assertLess(lut[100], 100)      # darks get darker
        self.assertGreater(lut[160], 160)   # lights get lighter

    def test_contrast_applies_before_snapping(self):
        # 100 -> 94 after x1.2 -> level 85; without contrast 100 is also 85,
        # but 124 -> 123 -> 85 and 135 -> 136 -> 170, so contrast moves the cut.
        plain = _tone_lut(1.0, True)
        boosted = _tone_lut(1.2, True)
        self.assertEqual(plain[133], 170)
        self.assertEqual(boosted[133], 170)
        self.assertEqual(plain[126], 85)
        self.assertEqual(boosted[126], 85)
        self.assertNotEqual(plain, boosted)


class ImageTests(unittest.TestCase):
    def test_quantized_grayscale_output(self):
        opts = Options(quality=90, grayscale=True, contrast=1.2, quantize=True)
        jpeg, meta = process_image(_png((64, 64), (100, 100, 100)), X3, opts)
        img = _decode(jpeg)
        self.assertEqual(img.mode, 'L')
        # (100-128)*1.2+128 = 94.4 -> level 85 (JPEG may wobble by a couple)
        self.assertAlmostEqual(img.getpixel((32, 32)), 85, delta=3)

    def test_default_options_leave_tones_alone(self):
        opts = Options(quality=95, grayscale=True)
        jpeg, _ = process_image(_png((64, 64), (100, 100, 100)), X3, opts)
        self.assertAlmostEqual(_decode(jpeg).getpixel((32, 32)), 100, delta=3)

    def test_cover_keeps_colour_and_uses_cover_box(self):
        opts = Options(quality=90, grayscale=True, contrast=1.2, quantize=True,
                       cover_color=True)
        jpeg, meta = process_image(_png((1000, 1600), (200, 40, 40)), X3, opts,
                                   'OEBPS/cover.png', is_cover=True)
        img = _decode(jpeg)
        self.assertEqual(img.mode, 'RGB')
        self.assertEqual((meta['final_w'], meta['final_h']), (500, 800))
        r, g, b = img.getpixel((10, 10))
        self.assertGreater(r, g + 80)      # still red, not grey

    def test_non_cover_uses_screen_box_and_grey(self):
        opts = Options(quality=90, grayscale=True, cover_color=True)
        jpeg, meta = process_image(_png((1000, 1600), (200, 40, 40)), X3, opts,
                                   'OEBPS/fig.png', is_cover=False)
        self.assertEqual(_decode(jpeg).mode, 'L')
        self.assertEqual((meta['final_w'], meta['final_h']), (495, 792))

    def test_cover_without_option_is_normal(self):
        opts = Options(quality=90, grayscale=True, cover_color=False)
        jpeg, meta = process_image(_png((1000, 1600), (200, 40, 40)), X3, opts,
                                   'OEBPS/cover.png', is_cover=True)
        self.assertEqual(_decode(jpeg).mode, 'L')
        self.assertEqual((meta['final_w'], meta['final_h']), (495, 792))


class CoverLookupTests(unittest.TestCase):
    def test_meta_cover(self):
        opf = ('<package><metadata><meta name="cover" content="c"/></metadata>'
               '<manifest><item id="c" href="img/cover.jpg" media-type="image/jpeg"/>'
               '<item id="o" href="other.jpg"/></manifest></package>')
        self.assertEqual(_find_cover_path('OEBPS/content.opf', opf), 'OEBPS/img/cover.jpg')

    def test_epub3_property(self):
        opf = ('<package><manifest>'
               '<item id="x" href="../Images/c.png" properties="cover-image"/>'
               '</manifest></package>')
        self.assertEqual(_find_cover_path('OEBPS/Text/content.opf', opf), 'OEBPS/Images/c.png')

    def test_none(self):
        self.assertIsNone(_find_cover_path('content.opf', '<package/>'))
        self.assertIsNone(_find_cover_path('content.opf', None))


class SelectorTests(unittest.TestCase):
    def setUp(self):
        self.u = cssprune.Usage()
        self.u.add('<html><body><p class="note big" id="x">a</p><h1>t</h1></body></html>')

    def test_matches(self):
        m = lambda s: cssprune.selector_can_match(s, self.u)
        self.assertTrue(m('p'))
        self.assertTrue(m('p.note'))
        self.assertTrue(m('.big'))
        self.assertTrue(m('#x'))
        self.assertTrue(m('body'))
        self.assertTrue(m('*'))
        self.assertTrue(m('a:hover'))            # pseudo -> kept
        self.assertTrue(m('img[src]'))           # attribute -> kept
        self.assertTrue(m('h2, h1'))             # any alternative
        self.assertTrue(m('div p'))              # one known element

    def test_drops(self):
        m = lambda s: cssprune.selector_can_match(s, self.u)
        self.assertFalse(m('.missing'))
        self.assertFalse(m('p.note.missing'))
        self.assertFalse(m('#nope'))
        self.assertFalse(m('table'))
        self.assertFalse(m('.a, .b'))

    def test_comma_inside_brackets_does_not_split(self):
        self.assertTrue(cssprune.selector_can_match('a[title="x,y"]', self.u))

    def test_unicode_class_names(self):
        u = cssprune.Usage()
        u.add('<p class="தமிழ்">x</p>')
        self.assertTrue(cssprune.selector_can_match('.தமிழ்', u))
        self.assertFalse(cssprune.selector_can_match('.மற்றது', u))


class PruneRulesTests(unittest.TestCase):
    def setUp(self):
        self.u = cssprune.Usage()
        self.u.add('<body><p class="keep">a</p></body>')

    def test_removes_only_dead_rules(self):
        css = ('/* c */ .keep{color:red} .dead{color:blue} '
               '@media print{.dead{x:y}} p,.dead{margin:0} '
               '@font-face{font-family:F;src:url(f.ttf)}')
        out, n = cssprune.prune_rules(css, self.u)
        self.assertEqual(n, 1)                      # only `.dead{...}`
        self.assertIn('.keep{color:red}', out)
        self.assertNotIn('.dead{color:blue}', out)
        self.assertIn('@media print', out)          # at-rules kept whole
        self.assertIn('p,.dead{margin:0}', out)     # `p` can match
        self.assertIn('@font-face', out)

    def test_leading_import_does_not_shield_a_dead_rule(self):
        css = '@charset "utf-8"; @import url(b.css); .dead{x:y} .keep{z:w}'
        out, n = cssprune.prune_rules(css, self.u)
        self.assertEqual(n, 1)
        self.assertIn('@import url(b.css);', out)
        self.assertNotIn('.dead', out)
        self.assertIn('.keep{z:w}', out)

    def test_unbalanced_css_is_left_alone(self):
        css = '.keep{color:red} .broken{'
        out, n = cssprune.prune_rules(css, self.u)
        self.assertEqual(n, 0)
        self.assertIn('.broken{', out)


XHTML = ('<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><head>'
         '<title>t</title>%s</head><body><p class="keep">hello</p></body></html>')
OPF = ('<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0" '
       'unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
       '<dc:identifier id="id">x</dc:identifier><dc:title>T</dc:title></metadata>'
       '<manifest><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>'
       '<item id="s" href="style.css" media-type="text/css"/>'
       '<item id="u" href="unused.css" media-type="text/css"/>'
       '<item id="e" href="empty.css" media-type="text/css"/></manifest>'
       '<spine><itemref idref="c1"/></spine></package>')


def _make_epub(path, link_tags):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('mimetype', 'application/epub+zip', zipfile.ZIP_STORED)
        z.writestr('META-INF/container.xml',
                   '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                   '<rootfile full-path="OEBPS/content.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr('OEBPS/content.opf', OPF)
        z.writestr('OEBPS/c1.xhtml', XHTML % link_tags)
        z.writestr('OEBPS/style.css', '.keep{color:#000} .dead{color:#f00} p{margin:0}')
        z.writestr('OEBPS/unused.css', '.keep{color:#111}')
        z.writestr('OEBPS/empty.css', '.dead{color:#222}')


class PlanTests(unittest.TestCase):
    def test_plan_drops_unlinked_and_empty_sheets(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / 'b.epub'
            _make_epub(src, '<link rel="stylesheet" type="text/css" href="style.css"/>'
                            '<link rel="stylesheet" href="empty.css"/>')
            with zipfile.ZipFile(src) as z:
                names = z.namelist()
                plan = cssprune.plan_css(names, lambda n: z.read(n).decode('utf-8'))
        self.assertEqual(plan.drop, {'OEBPS/unused.css', 'OEBPS/empty.css'})
        self.assertEqual(plan.rules_removed, 2)     # .dead in style.css and empty.css
        self.assertIn('.keep{color:#000}', plan.text['OEBPS/style.css'])
        self.assertNotIn('.dead', plan.text['OEBPS/style.css'])

    def test_import_chain_keeps_imported_sheet(self):
        names = ['a.xhtml', 'main.css', 'base.css', 'orphan.css']
        files = {
            'a.xhtml': '<html><head><link rel="stylesheet" href="main.css"/></head>'
                       '<body><p>x</p></body></html>',
            'main.css': '@import url("base.css"); p{a:b}',
            'base.css': 'p{c:d}',
            'orphan.css': 'p{e:f}',
        }
        plan = cssprune.plan_css(names, files.__getitem__)
        self.assertEqual(plan.drop, {'orphan.css'})

    def test_xml_stylesheet_pi_counts_as_linked(self):
        names = ['a.xhtml', 's.css']
        files = {'a.xhtml': '<?xml-stylesheet type="text/css" href="s.css"?><html><body>'
                            '<p>x</p></body></html>',
                 's.css': 'p{a:b}'}
        self.assertEqual(cssprune.plan_css(names, files.__getitem__).drop, set())

    def test_strip_links_and_manifest(self):
        dropped = {'OEBPS/unused.css'}
        markup = ('<head><link rel="stylesheet" href="unused.css"/>'
                  '<link rel="stylesheet" href="style.css"/></head>')
        out = cssprune.strip_links(markup, 'OEBPS/c1.xhtml', dropped)
        self.assertNotIn('unused.css', out)
        self.assertIn('style.css', out)
        out = cssprune.strip_manifest(OPF, 'OEBPS/content.opf', dropped)
        self.assertNotIn('unused.css', out)
        self.assertIn('style.css', out)
        self.assertIn('empty.css', out)


class EndToEndTests(unittest.TestCase):
    def test_prune_css_in_optimize_epub(self):
        with tempfile.TemporaryDirectory() as d:
            src, out = Path(d) / 'in.epub', Path(d) / 'out.epub'
            _make_epub(src, '<link rel="stylesheet" type="text/css" href="style.css"/>')
            summary = optimize_epub(str(src), str(out), X3,
                                    Options(split_text=False, prune_css=True))
            with zipfile.ZipFile(out) as z:
                names = z.namelist()
                self.assertEqual(names[0], 'mimetype')
                self.assertNotIn('OEBPS/unused.css', names)
                self.assertNotIn('OEBPS/empty.css', names)
                css = z.read('OEBPS/style.css').decode()
                html = z.read('OEBPS/c1.xhtml').decode()
                opf = z.read('OEBPS/content.opf').decode()
        self.assertNotIn('.dead', css)
        self.assertIn('hello', html)
        self.assertNotIn('unused.css', html)
        self.assertNotIn('unused.css', opf)
        self.assertNotIn('empty.css', opf)
        self.assertIn('style.css', opf)
        self.assertEqual(summary['css_files_removed'], 2)

    def test_prune_css_off_changes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            src, out = Path(d) / 'in.epub', Path(d) / 'out.epub'
            _make_epub(src, '<link rel="stylesheet" href="style.css"/>')
            optimize_epub(str(src), str(out), X3, Options(split_text=False))
            with zipfile.ZipFile(out) as z:
                self.assertIn('OEBPS/unused.css', z.namelist())
                self.assertIn('.dead', z.read('OEBPS/style.css').decode())


class SectionLimitTests(unittest.TestCase):
    def test_default_is_stock(self):
        self.assertEqual(textsplit.section_limits(None),
                         (textsplit.SPLIT_LIMIT, textsplit.CHUNK_TARGET))
        self.assertEqual(textsplit.section_limits(Options()),
                         (textsplit.SPLIT_LIMIT, textsplit.CHUNK_TARGET))

    def test_larger_sections(self):
        limit, target = textsplit.section_limits(Options(section_kb=32))
        self.assertEqual(limit, 32 * 1024)
        self.assertLess(target, limit)
        self.assertGreater(target, textsplit.CHUNK_TARGET)

    def test_never_below_stock(self):
        self.assertEqual(textsplit.section_limits(Options(section_kb=1)),
                         (textsplit.SPLIT_LIMIT, int(textsplit.SPLIT_LIMIT *
                          textsplit.CHUNK_TARGET / float(textsplit.SPLIT_LIMIT))))

    def test_larger_limit_means_fewer_files(self):
        para = '<p>%s</p>' % ('word ' * 40)            # ~200 bytes, under PARA_LIMIT
        doc = ('<html><head><title>t</title></head><body>%s</body></html>'
               % (para * 400))                         # ~80 KB of body
        stock = textsplit.split_xhtml_doc(doc, 'c.xhtml')
        big = textsplit.split_xhtml_doc(doc, 'c.xhtml', *textsplit.section_limits(Options(section_kb=32)))
        self.assertGreater(len(stock), len(big))
        self.assertGreater(len(big), 1)
        self.assertEqual(''.join(c.split('<body>', 1)[1].rsplit('</body>', 1)[0] for _n, c in big),
                         para * 400)


if __name__ == '__main__':
    unittest.main()
