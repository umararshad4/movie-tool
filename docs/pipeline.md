# MoviesMod download pipeline (verified 2026-11-15, plain HTTP end to end)

1. Movie page `https://moviesmod.tw/download-...` — `<h4>` per quality, first
   `links.modpro.blog/archives/<id>` link after each heading.
2. Archive page — anchors `https://en.thenaukriadda.in/?sid=<b64>`; two servers
   (Fast Server G-Drive / Google Drive Server 2) point to the same file.
3. LP chain (all server-rendered, timers are client-side only):
   a. `GET en.thenaukriadda.in/?sid=<b64>` (Referer: links page) → auto-POST form
      (`_lp_http`, action `/`).
   b. `POST /` with `_lp_http` → page contains hidden `lp-s1-form`:
      action = random gateway post, fields `_lp_http2`, `_lp_token`, `_lp_chain`,
      `_lp_hop_index`.
   c. `POST <gateway post>` with those fields → page contains `sc("lp-<key>","<val>")`
      (cookie value = base64(zlib(b64 sid))) and `lp_go=lp-<key>` href.
   d. `GET /?lp_go=lp-<key>` with Cookie `lp-<key>=<val>` → "Please wait" page with
      `window.location.replace("https://driveseed.org/r?key=..&id=..")`.
4. `GET driveseed.org/r?...` → `replace("/file/<id>")` → `GET /file/<id>`:
   - `<title>` = filename
   - "Instant Download" anchor = `https://cdn.video-gen.xyz/<hex>::<hex>` (no login)
5. `GET cdn.video-gen.xyz/...` → 302 → `video-seed.dev/?url=<final>`; final = `url`
   param (googleusercontent, signed, time-limited).
6. `GET <final>` → real file. Supports Range. Example verified:
   `content-type: video/mkv`, `content-length: 1606728081`,
   `content-disposition: filename="Monstrous.2020.1080p.10Bit....mkv"`,
   first bytes `1a 45 df a3` (EBML/Matroska).

Notes
- The driveseed `generate()` API (POST /file/<id> with action=original|direct) is
  login-gated ("Session Not Found Please Login!") — do NOT use it.
- No cookies needed beyond the LP chain's own (carry a CookieJar through steps 3a-3d).
- The `?sid=` token is single-use; fetch a fresh link page per resolve.
- Server 2 sid resolves to the same driveseed key as server 1 (mirror).

## UHDMovies (4K) variant (verified 2026-11-16)

4K lives on the sister site, not MoviesMod itself (which posts 480p-1080p only):

1. Movie page `https://uhdmovies.<tld>/download-...` (.beauty/.my/.food/.mov) —
   no quality headings; instead direct anchors
   `https://en.thenaukriadda.in/?sid=<b64>` whose link text is the quality
   ("4k HDR", "4k 2160p", "1080p x265 10Bit", "Episode 1"…). Same LP chain from
   step 3 above, no modpro.blog hop.
2. Boilerplate/category anchors (site-name links, "3D Movies", menu items) are
   dropped by text filter; anchors dedupe by sid.
3. Not every pack link is alive: some sids' LP chain final hop lands on the
   site's own (parked) domain, e.g. `uhdmovies.mov/2160p-movies/` →
   "Coming Soon". The service marks those items with the error
   "This quality pack is no longer available (stale link)."
   Per-episode sids on the same page may still resolve to real files
   (a ~4 GB per-episode file is typically the 2160p encode).
4. Items are tagged `quality` ("4K"/"1080p"/…), `tier` (4K=4, 1440p/1080p=3,
   720p=2, 480p and below=1) and `state` (2 = fully resolved with a direct URL,
   1 = the LP hop ended on an unresolvable host, and the item hands back that
   host page URL, 0 = failed). Result lists sort working items first, then by
   tier, then page order.
5. The direct-URL probe (cdn.video-gen.xyz) sometimes answers HTTP 500; the
   service retries once before giving up on that item.
