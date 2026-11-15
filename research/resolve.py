"""Trace the full MoviesMod link chain with plain HTTP. Research library + CLI."""
import base64, re, sys, time, zlib
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def make_opener():
    return build_opener(HTTPCookieProcessor(CookieJar()), NoRedirect())

def fetch(opener, url, data=None, referer=None):
    headers = {'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
               'Accept-Language': 'en-US,en;q=0.9'}
    if referer: headers['Referer'] = referer
    if data is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
        headers['Origin'] = urlparse(url).scheme + '://' + urlparse(url).hostname
    req = Request(url, data=urlencode(data).encode() if data else None, headers=headers)
    try:
        with opener.open(req, timeout=25) as r:
            return r.status, dict(r.headers), r.read().decode('utf-8', 'replace'), r.url
    except Exception as e:
        return 0, {}, str(e), url

def hidden_fields(html):
    return dict(re.findall(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', html))

class AutoPost(HTMLParser):
    def __init__(self):
        super().__init__(); self.action = None; self.fields = {}
        self.in_form = False
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'form': self.in_form = True; self.action = a.get('action')
        if tag == 'input' and self.in_form and a.get('type') == 'hidden' and a.get('name'):
            self.fields[a['name']] = a.get('value', '')

def main():
    sid = sys.argv[1] if len(sys.argv) > 1 else None
    if not sid: sys.exit('usage: resolve.py <sid-url or sid>')
    if sid.startswith('http'):
        sid = re.search(r'sid=([^&]+)', sid).group(1)
    print('sid:', sid[:40], '...')
    opener = make_opener()
    st, hdr, html, url = fetch(opener, 'https://en.thenaukriadda.in/?sid=' + sid, referer='https://links.modpro.blog/')
    print(f'[landing] {st}')
    p = AutoPost(); p.feed(html)
    st, hdr, html, url = fetch(opener, p.action or 'https://en.thenaukriadda.in/', data=p.fields, referer='https://en.thenaukriadda.in/?sid=' + sid)
    m = re.search(r'<form id="lp-s1-form"[^>]*action="([^"]+)"', html)
    if not m: sys.exit('no lp-s1-form')
    action1 = m.group(1)
    fields = hidden_fields(html[m.start():html.find('</form>', m.start())])
    print('[stage1]', action1)
    st, hdr, html, url = fetch(opener, action1, data=fields, referer='https://en.thenaukriadda.in/')
    m2 = re.search(r'sc\("([^"]+)"\s*,\s*"([^"]+)"', html)
    m3 = re.search(r'lp_go=(lp-[a-z0-9]+)', html)
    if not (m2 and m3): sys.exit('no gateway cookie/lp_go')
    key, val = m2.group(1), m2.group(2).replace('\\/', '/')
    print('[gateway] key:', key)
    import http.cookiejar
    jar = None
    for h in opener.handlers:
        if isinstance(h, HTTPCookieProcessor): jar = h.cookiejar
    ck = http.cookiejar.Cookie(0, key, val, None, False, 'en.thenaukriadda.in', True, True, '/', True, False, None, False, None, None, {})
    jar.set_cookie(ck)
    st, hdr, html, url = fetch(opener, 'https://en.thenaukriadda.in/?lp_go=' + m3.group(1), referer='https://en.thenaukriadda.in/')
    m4 = re.search(r'replace\("([^"]+)"\)', html)
    print('[final]', m4.group(1).replace('\\/', '/') if m4 else '(none)')
    open('final_step.html', 'w').write(html)

if __name__ == '__main__':
    main()
