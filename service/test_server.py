"""Unit tests: parsers and helpers only; no network."""
import os
import unittest

import server
from server import (Options, drive_step, human, is_movie_host, parse_final_redirect,
                    parse_gateway, parse_lp_anchors, parse_movie, parse_sid,
                    parse_stage1, quality_of, safe_filename)

RESEARCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                        'research')
MOVIE_URL = 'https://moviesmod.tw/download-monstrous-2020-english-hindi-480p-720p-1080p/'
UHD_URL = 'https://uhdmovies.beauty/download-dexter-resurrection-2025-season-2-dual-audio-hindi-english-1080p-x264-web-dl-esubs/'


def read(name):
    path = os.path.join(RESEARCH, name)
    return open(path, encoding='utf-8', errors='replace').read() if os.path.exists(path) else None


class TestMovieParsing(unittest.TestCase):
    def test_quality_pairing_and_deduplication(self):
        parser = Options(MOVIE_URL)
        parser.feed('<h4>720p [500MB]</h4><a href="https://links.modpro.blog/archives/1">Download</a>'
                    '<a href="https://links.modpro.blog/archives/1">Duplicate</a>'
                    '<h4>1080p [1GB]</h4><a href="https://links.modpro.blog/archives/2">Download</a>')
        self.assertEqual([x['label'] for x in parser.items],
                         ['720p [500MB]', '1080p [1GB]'])

    def test_ignores_ad_links(self):
        parser = Options(MOVIE_URL)
        parser.feed('<h4>720p</h4><a href="https://ads.example/">Download</a>')
        self.assertEqual(parser.items, [])

    def test_live_movie_page_fixture(self):
        html = read('movie.html')
        if not html:
            self.skipTest('fixture missing')
        items = parse_movie(html, MOVIE_URL)
        self.assertGreaterEqual(len(items), 5)
        self.assertTrue(all(x['label'].strip() for x in items))
        self.assertTrue(all(x['url'].startswith('https://links.modpro.blog/archives/')
                            for x in items))
        self.assertEqual(len({x['url'] for x in items}), len(items))


class TestUhdParsing(unittest.TestCase):
    def test_uhd_anchor_pairing_and_dedup(self):
        html = ('<p>in <a href="https://en.thenaukriadda.in/?sid=AAA">1080p HEVC</a></p>'
                '<a class="mb" href="https://en.thenaukriadda.in/?sid=AAA">Duplicate</a>'
                '<a href="https://en.thenaukriadda.in/?sid=BBB">4k HDR</a>'
                '<a href="https://en.thenaukriadda.in/?sid=CCC">UHDMOVIES</a>'
                '<a href="https://ads.example/?sid=DDD">720p</a>')
        items = parse_lp_anchors(html)
        self.assertEqual([x['label'] for x in items], ['1080p HEVC', '4k HDR'])
        self.assertEqual([x['sid'] for x in items], ['AAA', 'BBB'])
        self.assertEqual([x['id'] for x in items], ['0', '1'])

    def test_uhd_live_page_fixture(self):
        html = read('uhdmovies.html')
        if not html:
            self.skipTest('fixture missing')
        items = parse_lp_anchors(html)
        labels = ' | '.join(x['label'] for x in items)
        self.assertIn('4k HDR', labels)
        self.assertIn('4k 2160p', labels)
        self.assertGreaterEqual(len(items), 5)
        self.assertTrue(all(x['url'].startswith('https://en.thenaukriadda.in/?sid=')
                            for x in items))
        self.assertEqual(len({x['sid'] for x in items}), len(items))
        # Site/category noise never becomes an item.
        self.assertNotIn('3D Movies', labels)
        self.assertNotIn('UHDMOVIES', labels)

    def test_item_state_ranking(self):
        self.assertEqual(server.item_state({'url': 'x'}), 2)
        self.assertEqual(server.item_state({'url': 'x', 'note': 'opens a host'}), 1)
        self.assertEqual(server.item_state({'url': 'x', 'error': 'stale'}), 0)
        self.assertEqual(server.item_state({'url': 'x', 'error': 'e', 'note': 'n'}), 0)

    def test_quality_labels_and_tiers(self):
        self.assertEqual(quality_of('Download X {Hindi} 2160p 4K HDR [16 GB]'), '4K')
        self.assertEqual(quality_of('4k 2160p SDR'), '4K')
        self.assertEqual(quality_of('1080p x264'), '1080p')
        self.assertEqual(quality_of('Episode 1'), '')
        self.assertEqual(server.TIER['4K'] > server.TIER['1080p'] > server.TIER['720p']
                         > server.TIER['480p'], True)

    def test_movie_hosts(self):
        self.assertEqual(is_movie_host('moviesmod.tw'), True)
        self.assertEqual(is_movie_host('www.moviesmod.tw'), True)
        self.assertEqual(is_movie_host('uhdmovies.beauty'), True)
        self.assertEqual(is_movie_host('uhdmovies.my'), True)
        self.assertEqual(is_movie_host('uhdmovies.beauty.evil.test'), False)
        self.assertEqual(is_movie_host('moviesmod.tw.evil.test'), False)
        self.assertEqual(is_movie_host('notmoviesmod.tw'), False)


class TestChainParsers(unittest.TestCase):
    def test_sid_from_link_page_fixture(self):
        html = read('lp.html')
        if not html:
            self.skipTest('fixture missing')
        sid = parse_sid(html)
        self.assertTrue(sid and len(sid) > 40)

    def test_landing_form_fields(self):
        html = ('<form id="lp-land" method="POST" action="https://en.thenaukriadda.in/">'
                '<input type="hidden" name="_lp_http" value="abc=="></form>')
        fields = dict(__import__('re').findall(
            r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', html))
        self.assertEqual(fields, {'_lp_http': 'abc=='})

    def test_stage1_fields(self):
        html = ('<form id="lp-s1-form" method="POST" style="display:none" '
                'action="https://en.thenaukriadda.in/gateway/">'
                '<input type="hidden" name="_lp_http2" value="v2">'
                '<input type="hidden" name="_lp_token" value="tok">'
                '<input type="hidden" name="_lp_chain" value="chain">'
                '<input type="hidden" name="_lp_hop_index" value="1">'
                '<button class="lp-btn">Continue</button></form>')
        stage = parse_stage1(html)
        self.assertEqual(stage['action'], 'https://en.thenaukriadda.in/gateway/')
        self.assertEqual(stage['fields'],
                         {'_lp_http2': 'v2', '_lp_token': 'tok',
                          '_lp_chain': 'chain', '_lp_hop_index': '1'})

    def test_gateway_cookie_and_go(self):
        html = 'sc("lp-6af8ce58d9f2e","eJwF\\/abc==");lp_go=lp-6af8ce58d9f2e'
        info = parse_gateway(html)
        self.assertEqual(info['cookie_key'], 'lp-6af8ce58d9f2e')
        self.assertEqual(info['cookie_value'], 'eJwF/abc==')
        self.assertEqual(info['lp_go'], 'lp-6af8ce58d9f2e')

    def test_final_redirect_unescapes(self):
        self.assertEqual(parse_final_redirect('replace("https:\\/\\/driveseed.org\\/r?key=a")'),
                         'https://driveseed.org/r?key=a')

    def test_drive_step_kinds(self):
        self.assertEqual(drive_step('<script>window.location.replace("/file/abc")</script>'),
                         ('replace', '/file/abc'))
        kind, info = drive_step('<title>Monstrous.2020.480p.mkv</title>'
                                '<a href="https://cdn.video-gen.xyz/aa::bb">Instant Download</a>')
        self.assertEqual(kind, 'file')
        self.assertEqual(info['title'], 'Monstrous.2020.480p.mkv')
        self.assertEqual(info['direct'], 'https://cdn.video-gen.xyz/aa::bb')

    def test_lp_chain_page_fixture_stage1(self):
        html = read('post_response.html')
        if not html:
            self.skipTest('fixture missing')
        stage = parse_stage1(html)
        self.assertTrue(stage)
        self.assertIn('_lp_http2', stage['fields'])
        self.assertIn('_lp_token', stage['fields'])


class TestHelpers(unittest.TestCase):
    def test_human(self):
        self.assertEqual(human(0), '')
        self.assertEqual(human(500), '500 B')
        self.assertEqual(human(1024), '1.0 KB')
        self.assertEqual(human(1606728081), '1.5 GB')

    def test_safe_filename(self):
        self.assertEqual(safe_filename('Monstrous.2020.480p.mkv'), 'Monstrous.2020.480p.mkv')
        self.assertEqual(safe_filename('a/b\\c:d*e?.mkv'), 'a_b_c_d_e_.mkv')
        self.assertEqual(safe_filename(''), 'movie')


class TestGuards(unittest.TestCase):
    def test_resolve_rejects_foreign_urls(self):
        for url in ['http://moviesmod.tw/', 'https://localhost/', 'https://moviesmod.tw.evil.test/',
                    'https://user@moviesmod.tw/', 'https://moviesmod.tw:8443/']:
            with self.assertRaises(ValueError):
                server.resolve_movie(url)


if __name__ == '__main__':
    unittest.main()
