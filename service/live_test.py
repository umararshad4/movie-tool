#!/usr/bin/env python3
"""Live end-to-end check of resolve_movie() against real pages (same process, no HTTP hop)."""
import json, sys, time
sys.path.insert(0, '.')
import server

URLS = [
    ("UHD 4K (Dexter S2)", "https://uhdmovies.beauty/download-dexter-resurrection-2025-season-2-dual-audio-hindi-english-1080p-x264-web-dl-esubs/"),
    ("MoviesMod (Monstrous 2020)", "https://moviesmod.tw/download-monstrous-2020-english-hindi-480p-720p-1080p/"),
]

for name, url in URLS:
    print(f"\n{'='*70}\n{name}\n{url}\n{'='*70}", flush=True)
    t0 = time.time()
    try:
        out = server.resolve_movie(url)
    except Exception as e:
        print(f"ERROR after {time.time()-t0:.1f}s: {type(e).__name__}: {e}", flush=True)
        continue
    print(f"ok in {time.time()-t0:.1f}s  title={out.get('title')!r} count={len(out.get('items', []))}", flush=True)
    for it in out.get('items', []):
        print(f"  [{it.get('tier')}] {it.get('quality','?'):7} {it.get('label')[:70]}")
        print(f"        url={it.get('url','')[:110]}")
        print(f"        size={it.get('size','?')} note={it.get('note','')}", flush=True)
    with open(f"/tmp/live_{'uhd' if 'UHD' in name else 'mm'}.json", "w") as f:
        json.dump(out, f, indent=2)
