"""Walk every quality variant of a movie page to its final driveseed URL."""
import re, sys, json, subprocess
sys.path.insert(0, '.')
from resolve import make_opener, fetch, UA, AutoPost  # noqa
import resolve

def walk(sid):
    opener = make_opener()
    st, hdr, html, url = fetch(opener, 'https://en.thenaukriadda.in/?sid=' + sid, referer='https://links.modpro.blog/')
    p = AutoPost(); p.feed(html)
    st, hdr, html, url = fetch(opener, p.action, data=p.fields, referer='https://en.thenaukriadda.in/?sid=' + sid)
    m = re.search(r'<form id="lp-s1-form"[^>]*action="([^"]+)"', html)
    if not m: return {'error': 'no lp-s1-form'}
    action1 = m.group(1)
    block = html[m.start():html.find('</form>', m.start())]
    fields = resolve.hidden_fields(block)
    st, hdr, html, url = fetch(opener, action1, data=fields, referer='https://en.thenaukriadda.in/')
    m2 = re.search(r'sc\("([^"]+)"\s*,\s*"([^"]+)"', html)
    m3 = re.search(r'lp_go=(lp-[a-z0-9]+)', html)
    if not (m2 and m3): return {'error': 'no gateway cookie'}
    key, val = m2.group(1), m2.group(2).replace('\\/', '/')
    import http.cookiejar
    jar = None
    for h in opener.handlers:
        if isinstance(h, resolve.HTTPCookieProcessor): jar = h.cookiejar
    ck = http.cookiejar.Cookie(0, key, val, None, False, 'en.thenaukriadda.in', True, True, '/', True, False, None, False, None, None, {})
    jar.set_cookie(ck)
    st, hdr, html, url = fetch(opener, 'https://en.thenaukriadda.in/?lp_go=' + m3.group(1), referer='https://en.thenaukriadda.in/')
    m4 = re.search(r'replace\("([^"]+)"\)', html)
    if not m4: return {'error': 'no final redirect'}
    final = m4.group(1).replace('\\/', '/')
    # driveseed: follow /r -> /file/<id>, read filename
    st, hdr, html2, url = fetch(opener, final, referer='https://en.thenaukriadda.in/')
    m5 = re.search(r'window\.location\.replace\("([^"]+)"\)', html2)
    name = ''
    file_id = None
    if m5:
        file_url = m5.group(1).replace('\\/', '/')
        file_url = file_url if file_url.startswith('http') else 'https://driveseed.org' + file_url
        st, hdr, html2, url = fetch(opener, file_url, referer=final)
        name = (re.findall(r'<title>([^<]*)', html2) or [''])[0]
        fm = re.search(r'/file/([A-Za-z0-9]+)', url)
        file_id = fm.group(1) if fm else None
        return {'final': final, 'file_url': url, 'name': name, 'key': file_id}
    return {'final': final, 'name': name}

def main():
    movie_url = 'https://moviesmod.tw/download-monstrous-2020-english-hindi-480p-720p-1080p/'
    st, hdr, html, url = fetch(make_opener(), movie_url, referer='https://moviesmod.tw/')
    parts = re.split(r'(<h4[^>]*>.*?</h4>)', html, flags=re.S)
    out = []
    for i in range(1, len(parts), 2):
        head = re.sub(r'<[^>]+>', '', parts[i]).strip()[:80]
        lm = re.search(r'href="(https://links\.modpro\.blog/[^"]+)"', parts[i+1])
        if not lm: continue
        st, hdr, lp_html, url = fetch(make_opener(), lm.group(1), referer=movie_url)
        sidm = re.search(r'href="https://en\.thenaukriadda\.in/\?sid=([^"]+)"', lp_html)
        print(head, flush=True)
        r = walk(sidm.group(1))
        print('   ', json.dumps(r)[:220], flush=True)
        out.append({'label': head, **r})
    json.dump(out, open('quality_map.json', 'w'), indent=1)

if __name__ == '__main__':
    main()
