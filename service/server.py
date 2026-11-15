"""Local MoviesMod resolver and downloader.

Pipeline (verified, see docs/pipeline.md): movie page -> per-quality link page
(links.modpro.blog) -> LP chain (en.thenaukriadda.in, three form posts) ->
driveseed file page -> direct CDN URL -> final signed file URL.

Bounded: single movie URL per call, sequential requests, fixed timeout per hop,
no upstream scripts are executed, no cookies besides the chain's own.
"""
import base64
import json
import os
import re
import shutil
import threading
import time
import zlib
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import (HTTPCookieProcessor, HTTPRedirectHandler, Request,
                            build_opener)

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
ACCEPT = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
MOVIE_HOST = 'moviesmod.tw'
# The same network's UHDMovies family carries the 2160p/4K posts.
UHD_NAME = 'uhdmovies'
LINK_HOST = 'links.modpro.blog'
LP_HOST = 'en.thenaukriadda.in'
DRIVE_HOSTS = ('driveseed.org',)
PAGE_LIMIT = 2_000_000
HOP_TIMEOUT = 20
REQUEST_GAP = 0.4          # politeness between upstream requests
CACHE_TTL = 20 * 60        # resolved items are reused for this long
JOB_ROOT = os.path.expanduser('~/Downloads')

_last_request = [0.0]
_gap_lock = threading.Lock()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def polite():
    with _gap_lock:
        wait = REQUEST_GAP - (time.monotonic() - _last_request[0])
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.monotonic()


def make_opener():
    return build_opener(HTTPCookieProcessor(CookieJar()), NoRedirect())


def fetch(opener, url, data=None, referer=None, timeout=HOP_TIMEOUT):
    polite()
    headers = {'User-Agent': UA, 'Accept': ACCEPT, 'Accept-Language': 'en-US,en;q=0.9'}
    if referer:
        headers['Referer'] = referer
    if data is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
        headers['Origin'] = '{0}://{1}'.format(urlparse(url).scheme, urlparse(url).hostname)
    req = Request(url, data=urlencode(data).encode() if data is not None else None,
                  headers=headers)
    try:
        with opener.open(req, timeout=timeout) as response:
            return response.read(PAGE_LIMIT + 1).decode('utf-8', 'replace')
    except ValueError:
        raise
    except Exception as error:
        status = getattr(error, 'code', 0)
        if status:
            raise ValueError('The site answered HTTP {0} for that page.'.format(status))
        raise


def probe(opener, url, referer=None):
    """One bounded hop: the redirect target, else the page body."""
    polite()
    headers = {'User-Agent': UA, 'Accept': ACCEPT}
    if referer:
        headers['Referer'] = referer
    req = Request(url, headers=headers)
    try:
        with opener.open(req, timeout=HOP_TIMEOUT) as response:
            if 300 <= response.status < 400:
                return {'location': response.headers.get('Location', '')}
            return {'body': response.read(PAGE_LIMIT + 1).decode('utf-8', 'replace')}
    except Exception as error:
        status = getattr(error, 'code', 0)
        if 300 <= status < 400:
            return {'location': error.headers.get('Location', '')}
        raise ValueError('The direct link did not answer: HTTP {0}.'.format(status or error))


def size_of(url, referer=None):
    """Content length via a headers-only request; 0 when unknown."""
    polite()
    headers = {'User-Agent': UA}
    if referer:
        headers['Referer'] = referer
    req = Request(url, headers=headers)
    try:
        with build_opener(NoRedirect).open(req, timeout=15) as response:
            response.read(0)
            return int(response.headers.get('Content-Length') or 0)
    except Exception:
        return 0


def human(n):
    if not n:
        return ''
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return '{0:.1f} {1}'.format(n, unit) if unit != 'B' else '{0} B'.format(n)
        n /= 1024.0
    return ''


def is_movie_host(host):
    """MoviesMod itself, or one UHDMovies domain (uhdmovies.<tld>, any www)."""
    labels = host.split('.')
    if labels and labels[0] == 'www':
        labels = labels[1:]
    m = MOVIE_HOST.split('.')
    return tuple(labels) == (m[0], m[1]) or \
        (len(labels) == 2 and labels[0] == UHD_NAME)


def movie_host_words():
    return '{0} or {1}.<tld> (4K)'.format(MOVIE_HOST, UHD_NAME)


# ---------------------------------------------------------------- parsing

class Options(HTMLParser):
    """Quality headings paired with the first link-page link after each."""

    QUALITY = re.compile(r'\b(?:480|540|576|720|1080|1440|2160)p\b|\b4\s?k\b|\buhd\b', re.I)
    HEADINGS = ('h2', 'h3', 'h4', 'h5', 'h6')

    def __init__(self, base):
        super().__init__()
        self.base = base
        self.heading = ''
        self.capture = False
        self.parts = []
        self.items = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in self.HEADINGS:
            self.capture = True
            self.parts = []
        if tag == 'a' and self.heading:
            url = urlparse(attrs.get('href', '') or '')
            if url.hostname == LINK_HOST and url.scheme in ('http', 'https'):
                link = '{0}://{1}{2}'.format(url.scheme, url.hostname, url.path)
                if link not in [i['url'] for i in self.items]:
                    self.items.append({'id': str(len(self.items)), 'label': self.heading,
                                       'url': link})

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag in self.HEADINGS and self.capture:
            value = ' '.join(''.join(self.parts).split())
            self.heading = value if self.QUALITY.search(value) else ''
            self.capture = False


def parse_movie(html, base):
    parser = Options(base)
    parser.feed(html)
    return parser.items


# UHDMovies posts: no per-quality headings. The quality anchors point straight
# at the LP host (en.thenaukriadda.in/?sid=...), labelled by their link text.
LP_ANCHOR = re.compile(r'<a\b[^>]*href="https://{0}/\?sid=([^"]+)"[^>]*>(.*?)</a>'.format(LP_HOST),
                       re.I | re.S)
LP_MEDIA = re.compile(
    r'\b(?:480|540|576|720|1080|1440|2160)p\b|\b4\s?k\b|\buhd\b|\bhevc\b|\bx26[45]\b'
    r'|\b10\s?bit\b|\b60\s?fps\b|\bepisode\b|\bhdrip\b|\bweb-?dl\b|\bbluray\b'
    r'|\bremux\b|\b3d\b', re.I)
# Anchor texts that name the site or a category, never a download pack.
LP_NOISE = re.compile(r'^(?:uhdmovies|moviesmod|3d\s*movies|home|telegram|how to download)\b.*$', re.I)


def parse_lp_anchors(html):
    """Direct sid anchors that name a quality, in page order, deduped by sid."""
    seen, items = set(), []
    for m in LP_ANCHOR.finditer(html):
        sid, inner = m.group(1), m.group(2)
        label = ' '.join(re.sub(r'<[^>]+>', ' ', inner).split())
        if not label or not LP_MEDIA.search(label) or LP_NOISE.match(label) \
                or sid in seen:
            continue
        seen.add(sid)
        items.append({'id': str(len(items)), 'label': label[:120],
                      'url': 'https://{0}/?sid={1}'.format(LP_HOST, sid),
                      'sid': sid})
    return items


def quality_of(text):
    """The short quality label a heading or link text carries ('4K', '1080p')."""
    if re.search(r'\b2160p\b|\b4\s?k\b', text, re.I):
        return '4K'
    m = re.search(r'\b(1440|1080|720|576|540|480)p\b', text, re.I)
    return (m.group(1) + 'p') if m else ''


TIER = {'4K': 4, '1440p': 3, '1080p': 3, '720p': 2, '576p': 1, '540p': 1, '480p': 1}


def parse_sid(html):
    m = re.search(r'href="https://{0}/\?sid=([^"]+)"'.format(LP_HOST), html)
    return m.group(1) if m else None


def parse_stage1(html):
    """The hidden lp-s1-form: gateway action plus its hidden fields."""
    m = re.search(r'<form id="lp-s1-form"[^>]*action="([^"]+)"', html)
    if not m:
        return None
    block = html[m.start():html.find('</form>', m.start())]
    fields = dict(re.findall(
        r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', block))
    return {'action': m.group(1), 'fields': fields}


def parse_gateway(html):
    m = re.search(r'sc\("([^"]+)"\s*,\s*"([^"]+)"', html)
    g = re.search(r'lp_go=(lp-[a-z0-9]+)', html)
    if not (m and g):
        return None
    return {'cookie_key': m.group(1), 'cookie_value': m.group(2).replace('\\/', '/'),
            'lp_go': g.group(1)}


def parse_final_redirect(html):
    m = re.search(r'replace\("([^"]+)"\)', html)
    return m.group(1).replace('\\/', '/') if m else None


def drive_step(html):
    """driveseed /r page -> ('replace', target); /file page -> ('file', info)."""
    m = re.search(r'window\.location\.replace\("([^"]+)"\)', html)
    if m:
        return 'replace', m.group(1).replace('\\/', '/')
    title = (re.findall(r'<title>([^<]*)', html) or [''])[0].strip()
    direct = ''
    for pattern in ('https://cdn\\.video-gen\\.xyz/[^"]+', 'https://instant\\.video-gen\\.xyz/[^"]+'):
        m = re.search(r'href="({0})"'.format(pattern), html)
        if m:
            direct = m.group(1).replace('&amp;', '&')
            break
    return 'file', {'title': title, 'direct': direct}


# ---------------------------------------------------------------- LP chain

def lp_chain(sid, referer):
    """Sid token -> driveseed /r?... URL. Four bounded hops."""
    opener = make_opener()
    landing = fetch(opener, 'https://{0}/?sid={1}'.format(LP_HOST, sid), referer=referer)
    m = re.search(r'<form[^>]*method="POST"[^>]*action="([^"]+)"', landing)
    if not m:
        raise ValueError('The link page changed; no landing form found.')
    fields = dict(re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', landing))
    page = fetch(opener, m.group(1), data=fields, referer='https://{0}/?sid={1}'.format(LP_HOST, sid))
    stage = parse_stage1(page)
    if not stage:
        raise ValueError('The link host did not expose its continue form.')
    gateway = fetch(opener, stage['action'], data=stage['fields'], referer='https://{0}/'.format(LP_HOST))
    info = parse_gateway(gateway)
    if not info:
        raise ValueError('The gateway page did not expose its go key.')
    import http.cookiejar
    jar = None
    for handler in opener.handlers:
        if isinstance(handler, HTTPCookieProcessor):
            jar = handler.cookiejar
    cookie = http.cookiejar.Cookie(
        0, info['cookie_key'], info['cookie_value'], None, False,
        LP_HOST, True, True, '/', True, False, None, False, None, None, {})
    jar.set_cookie(cookie)
    final_page = fetch(opener, 'https://{0}/?lp_go={1}'.format(LP_HOST, info['lp_go']),
                       referer='https://{0}/'.format(LP_HOST))
    target = parse_final_redirect(final_page)
    if not target:
        raise ValueError('The final hop did not redirect to a file host.')
    return target


def resolve_item(label, link_url, movie_url, sid=None):
    """One quality: link page -> LP chain -> driveseed -> direct URL."""
    opener = make_opener()
    if sid:
        target = lp_chain(sid, referer=movie_url)
    else:
        link_html = fetch(opener, link_url, referer=movie_url)
        sid = parse_sid(link_html)
        if not sid:
            return {'label': label, 'url': link_url, 'error': 'No server link on the link page.'}
        try:
            target = lp_chain(sid, referer=link_url)
        except ValueError as error:
            return {'label': label, 'url': link_url, 'error': str(error)}
    host = urlparse(target).hostname or ''
    if is_movie_host(host) or host == LP_HOST:
        # The LP hop landed back on the site's own (often parked) domain:
        # this quality pack's single-use link is stale.
        return {'label': label, 'url': target, 'error':
                'This quality pack is no longer available (stale link).'}
    if not any(host == h or host.endswith('.' + h) for h in DRIVE_HOSTS):
        # A different file host: hand the user its page instead of failing.
        return {'label': label, 'url': target, 'host_page': target,
                'note': 'This quality opens a host the tool does not resolve yet.'}
    page = fetch(opener, target, referer='https://{0}/'.format(LP_HOST))
    kind, info = drive_step(page)
    file_url = target
    hops = 0
    while kind == 'replace' and hops < 2:
        file_url = info if info.startswith('http') else 'https://driveseed.org' + info
        page = fetch(opener, file_url, referer=target)
        kind, info = drive_step(page)
        hops += 1
    if kind != 'file':
        raise ValueError('The file host did not show its file page.')
    filename = info.get('title', '') or 'movie.mkv'
    item = {'label': label, 'url': file_url, 'filename': filename, 'host_page': file_url}
    if info.get('direct'):
        cdn = info['direct']
        final = None
        for attempt in (1, 2):  # the CDN answers 500 now and then; retry once
            try:
                shot = probe(make_opener(), cdn, referer=file_url)
                final = shot.get('location') or parse_final_redirect(shot.get('body', ''))
            except ValueError as error:
                if attempt == 2:
                    item['error'] = str(error)
            if final:
                break
            polite()
        if final:
            params = parse_qs(urlparse(final).query)
            if 'url' in params:
                final = unquote(params['url'][0])
            if final.startswith('http'):
                item['download_url'] = final
                item['size'] = size_of(final, referer=file_url)
    return item


# ---------------------------------------------------------------- resolve

_cache = {}
_cache_lock = threading.Lock()


def item_state(item):
    """2 = fully resolved, 1 = handed a host page, 0 = failed."""
    if 'error' in item:
        return 0
    return 1 if 'note' in item else 2


def resolve_movie(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not is_movie_host(parsed.hostname or '') \
            or parsed.username or parsed.port:
        raise ValueError('Paste an HTTPS movie page from {0}.'.format(movie_host_words()))
    with _cache_lock:
        cached = _cache.get(url)
    if cached and time.time() - cached['ts'] < CACHE_TTL:
        return {'items': cached['items'], 'error': ''}
    opener = make_opener()
    movie_html = fetch(opener, url, referer='https://{0}/'.format(parsed.hostname))
    if len(movie_html) > PAGE_LIMIT:
        raise ValueError('Page exceeds the 2 MB limit.')
    options = parse_movie(movie_html, url)
    if not options:
        options = parse_lp_anchors(movie_html)
    if not options:
        raise ValueError('No supported quality links found on this page.')
    items = []
    for option in options:
        try:
            item = resolve_item(option['label'], option['url'], url,
                                sid=option.get('sid'))
            item['id'] = option['id']
        except Exception as error:  # one quality failing must not kill the rest
            item = {'id': option['id'], 'label': option['label'],
                    'url': option['url'], 'error': str(error)}
        item['label'] = option['label']
        item['quality'] = quality_of(option['label'])
        item['tier'] = TIER.get(item['quality'], 0)
        item['state'] = item_state(item)
        items.append(item)
    items.sort(key=lambda it: (-it['state'], -it['tier'], int(it['id'])))
    with _cache_lock:
        _cache[url] = {'ts': time.time(), 'items': items}
    return {'items': items, 'error': ''}


def cached_item(url, item_id):
    with _cache_lock:
        cached = _cache.get(url)
    if cached and time.time() - cached['ts'] < CACHE_TTL:
        for item in cached['items']:
            if item['id'] == item_id:
                return dict(item)
    return None


# ---------------------------------------------------------------- downloads

_jobs = {}
_jobs_lock = threading.Lock()
_job_seq = [0]


def safe_filename(name):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', name).strip().rstrip('.')
    return name[:150] or 'movie'


def free_path(directory, name):
    base, ext = os.path.splitext(name)
    candidate = name
    index = 1
    while os.path.exists(os.path.join(directory, candidate + '.part')) or \
            os.path.exists(os.path.join(directory, candidate)):
        candidate = '{0} ({1}){2}'.format(base, index, ext)
        index += 1
    return os.path.join(directory, candidate + '.part'), os.path.join(directory, candidate)


def run_job(job):
    part, final = job['part'], job['final']
    headers = {'User-Agent': UA, 'Accept': '*/*'}
    if job.get('referer'):
        headers['Referer'] = job['referer']
    try:
        req = Request(job['url'], headers=headers)
        with build_opener(NoRedirect).open(req, timeout=60) as response:
            total = int(response.headers.get('Content-Length') or 0)
            with _jobs_lock:
                job['total'] = total
            with open(part, 'wb') as out:
                while True:
                    if job['cancel'].is_set():
                        raise ValueError('Cancelled.')
                    chunk = response.read(1 << 16)
                    if not chunk:
                        break
                    out.write(chunk)
                    job['received'] += len(chunk)
        shutil.move(part, final)
        with _jobs_lock:
            job['state'] = 'done'
            job['path'] = final
    except Exception as error:
        status = getattr(error, 'code', 0)
        message = ('The file link expired (HTTP 403). Resolve again and retry.'
                   if status == 403 else
                   'The download failed (HTTP {0}).'.format(status) if status else str(error))
        with _jobs_lock:
            job['state'] = 'error'
            job['error'] = message
        try:
            if os.path.exists(part):
                os.remove(part)
        except OSError:
            pass


def start_job(item):
    url = item.get('download_url')
    if not url:
        raise ValueError('This option has no direct file link to download.')
    filename = safe_filename(item.get('filename') or 'movie.mkv')
    # The final host ignores Range, so a partial file from an earlier run is
    # useless: drop it and start over under this name.
    stale = os.path.join(JOB_ROOT, filename + '.part')
    try:
        if os.path.exists(stale):
            os.remove(stale)
    except OSError:
        pass
    with _jobs_lock:
        _job_seq[0] += 1
        job_id = 'job{0}'.format(_job_seq[0])
        part, final = free_path(JOB_ROOT, filename)
        job = {'id': job_id, 'label': item.get('label', ''), 'filename': filename,
               'state': 'running', 'received': 0, 'total': 0, 'error': '', 'path': '',
               'url': url, 'referer': item.get('host_page', ''), 'part': part,
               'final': final, 'cancel': threading.Event()}
        _jobs[job_id] = job
    thread = threading.Thread(target=run_job, args=(job,), daemon=True)
    thread.start()
    return {'job_id': job_id}


def jobs_snapshot():
    with _jobs_lock:
        out = []
        for job in _jobs.values():
            received, total = job['received'], job['total']
            pct = int(received * 100 / total) if total else 0
            out.append({'id': job['id'], 'label': job['label'], 'filename': job['filename'],
                        'state': job['state'], 'pct': pct, 'received': received,
                        'total': total, 'error': job['error'], 'path': job['path']})
        return {'jobs': out, 'error': ''}


# ---------------------------------------------------------------- server

# Origins whose web pages may call this service. Always the local dev hosts;
# MOVIE_ORIGINS (comma-separated hostnames) and the deployed site's host extend it.
_EXTRA_ORIGINS = tuple(
    h.strip().lower() for h in os.environ.get('MOVIE_ORIGINS', '').split(',') if h.strip())
DEPLOYED_HOST = os.environ.get('MOVIE_DEPLOYED_HOST', 'movie-tool.vercel.app')
ALLOWED_ORIGINS = ('127.0.0.1', 'localhost') + _EXTRA_ORIGINS + \
    ((DEPLOYED_HOST,) if DEPLOYED_HOST else ())


def allowed_origin(origin):
    """A full Origin header value, or '' when it is not from an allowed host."""
    host = urlparse(origin).hostname
    return origin if host and host.lower() in ALLOWED_ORIGINS else ''


class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.reply({}, 200)

    def do_GET(self):
        if self.path == '/health':
            return self.reply({'ok': True})
        if self.path == '/progress':
            return self.reply(jobs_snapshot())
        return self.reply({'error': 'Not found'}, 404)

    def do_POST(self):
        if not allowed_origin(self.headers.get('Origin', '')):
            return self.send_response(403) or self.end_headers()
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 8192:
                raise ValueError('Invalid request size.')
            body = json.loads(self.rfile.read(length))
            if self.path == '/inspect':
                return self.reply(legacy_inspect(body.get('url', '')))
            if self.path == '/resolve':
                return self.reply(resolve_movie(body.get('url', '')))
            if self.path == '/download':
                return self.reply(handle_download(body))
            return self.reply({'error': 'Not found'}, 404)
        except Exception as error:
            self.reply({'error': str(error)}, 400)

    def reply(self, body, status=200):
        origin = allowed_origin(self.headers.get('Origin', ''))
        if self.headers.get('Origin', '') and not origin:
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(status)
        if origin:
            self.send_header('Access-Control-Allow-Origin', origin)
            # The deployed page (public https) calling this local service is a
            # private-network request: Chrome requires this preflight answer.
            self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Access-Control-Allow-Headers', 'content-type')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, *args):
        pass


def handle_download(body):
    url, item_id = body.get('url', ''), body.get('id', '')
    if not url or not item_id:
        raise ValueError('Missing url or id.')
    item = cached_item(url, item_id)
    if not item:
        result = resolve_movie(url)
        item = next((i for i in result['items'] if i['id'] == item_id), None)
        if not item:
            raise ValueError('That option is not on this page anymore; resolve again.')
    if 'error' in item and item['error']:
        raise ValueError(item['error'])
    return start_job(item)


def legacy_inspect(url):
    """Kept from the earlier prototype: options without resolution."""
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not is_movie_host(parsed.hostname or ''):
        raise ValueError('Paste an HTTPS movie page from {0}.'.format(movie_host_words()))
    opener = make_opener()
    html = fetch(opener, url, referer='https://{0}/'.format(MOVIE_HOST))
    return {'items': parse_movie(html, url) or parse_lp_anchors(html),
            'error': '' if html else 'No supported quality links found on this page.'}


if __name__ == '__main__':
    port = int(os.environ.get('PORT') or 8787)
    print('Movie service: http://127.0.0.1:{0}'.format(port), flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
