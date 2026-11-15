# Movie Tool — one-click MoviesMod downloader

Paste a MoviesMod or UHDMovies movie page URL, see every labelled quality with its file size (4K included), and download the one you want straight to `~/Downloads` — no waiting out redirect pages, no clicking through tab farms. Built with [Expo Exact](https://github.com/expo/exact) (revision `777a416004cb22ec1d79aeef82fc4415e592d2b7`, cloned at `exact/`) as the UI framework over a small local Python service that does the link-chain work.

**Live UI:** <https://movie-tool.vercel.app> — the web app is a static site on Vercel. It talks to the Python service running on your machine (see below), so resolving works from the deployed site as long as the service is up locally and your browser allows the public→localhost call (Chrome/Edge do; Safari/Firefox may block it — for those, run the app locally with `./run.sh`).

Personal, local-only tool: one movie URL at a time, sequential polite requests (0.4 s gap), nothing executed upstream, no accounts.

## Run it

```sh
./run.sh                     # starts the service + the web app, prints the URL
```

or by hand:

```sh
python3 service/server.py    # service on http://127.0.0.1:8787
cd movie-tool && bun exact.mjs web   # app on http://127.0.0.1:8765
```

The service needs the Exact checkout beside it only for the app build (`exact.mjs` resolves `../exact`); clone it with the revision above if you want to rebuild the UI or run contract tests.

### Deployed UI + local service

The Vercel site is just the built web app (`movie-tool/dist`):

```sh
cd movie-tool && bun exact.mjs web-build --out dist
cd dist && vercel deploy --prod --yes   # project: movie-tool → movie-tool.vercel.app
```

The deployed page calls `http://127.0.0.1:8787` in *your* browser, so the service must be running locally. Its CORS allow-list is `127.0.0.1`, `localhost`, `movie-tool.vercel.app`, plus anything in `MOVIE_ORIGINS` (comma-separated hostnames); it also answers Chrome's private-network preflight. Point `MOVIE_DEPLOYED_HOST` elsewhere if you rename the Vercel project.

Then: paste a movie page URL → **Find qualities** → per-quality **Download** buttons → live progress → "Saved to ~/Downloads".

Tests:

```sh
python3 -m unittest discover -s service -v   # 18 unit tests
cd movie-tool && bun exact.mjs verify web    # 3 contract tests, clean
```

## How a download actually works

The verified pipeline (full detail in [`docs/pipeline.md`](docs/pipeline.md)):

1. **Movie page** (moviesmod.tw): each quality is a labelled H4 heading followed by an archive link on `links.modpro.blog` (e.g. `/archives/161095`). The parser pairs headings with links and reports size/filename labels.
2. **Archive link**: exposes two servers; we use the first (`en.thenaukriadda.in?sid=…`). `sid` tokens are **single-use** — every resolve fetches fresh link pages.
3. **Landing-page chain** (4 hops, all forms/redirects replayed server-side): `?sid=` auto-POST `_lp_http` → `POST /` → hidden `lp-s1-form` (`_lp_http2`, `_lp_token`, `_lp_chain`, `_lp_hop_index`) → gateway sets cookie `lp-<key>` and lands on a "Please wait" page containing `replace("https://driveseed.org/r?…")`.
4. **Driveseed**: `/r` → `/file/<id>` (page title is the filename) → its **"Instant Download"** anchor points at `cdn.video-gen.xyz`. The `generate()` API is login-gated ("Session Not Found Please Login!") and is deliberately **not** used.
5. **Final URL**: cdn → 302 → `video-seed.dev/?url=<signed googleusercontent URL>` → the signed URL serves the actual video (mkv/mp4). The host ignores HTTP `Range`, so there is **no resume**: a broken download restarts from zero (the `.part` file is deleted and a fresh job re-resolves the link, since signed URLs are time-limited — resolved links are cached 20 min).

## Platforms

| Platform | Where | How |
| --- | --- | --- |
| **Web** (deployed) | <https://movie-tool.vercel.app> | `bun exact.mjs web-build --out dist` → Vercel |
| **macOS** `.app` | CI artifact (and releases) | `bun exact.mjs mac --bundle` — needs full Xcode 26+ |
| **iOS** (simulator) | CI artifact | `bun exact.mjs ios` — needs Xcode; real-device installs via `share` |
| **Linux** x86-64 | CI artifact (and releases) | `bun exact.mjs linux` — cross-builds from macOS too |
| **Windows** x86-64 | CI artifact | `bun exact.mjs windows` — needs an MSVC Windows host |
| **Android** APK | CI artifact | `bun exact.mjs android --no-install` — needs JDK 17 + Android SDK/NDK |

`.github/workflows/build.yml` builds all of them on GitHub Actions: pushes to `main` upload per-platform artifacts; pushing a tag `v*` also publishes them on a GitHub release. Locally this machine has no full Xcode/Android SDK/MSVC, so only `web`, the Linux cross-build, and the contract tests run here; everything else is CI's job. (A native build uses the app's own `app.json` grants, so the desktop/phone apps talk to the local service like the web app does.)

## Status

- **Web app: done and live-verified.** `bun exact.mjs verify web` is clean; end-to-end on [Monstrous (2020)](https://moviesmod.tw/download-monstrous-2020-english-hindi-480p-720p-1080p/) resolved all 5 qualities (161095–161099) and downloaded the 280 MB 720p MKV twice, both files valid (EBML header, ffprobe duration 5165 s), with progress observed 1 % → 53 % → 100 %.
- **Native (iOS/macOS/Android/Linux/Windows): built on CI.** This machine has no full Xcode, Android SDK, or MSVC, so local native builds can't run; `.github/workflows/build.yml` produces every platform's artifact on GitHub Actions (Linux also cross-builds locally: `bun exact.mjs linux`). Exact's share-to-phone path is therefore unverified locally too.

## Known limits

- Single movie URL per resolve; sequential downloads, one job per quality.
- No resume/`Range` support upstream; interrupted downloads restart from zero.
- Signed final URLs expire — resolve again if a cached link 403s (the UI shows "The file link expired. Resolve again and retry.").
- Driveseed's login-gated API is bypassed via the page's Instant Download anchor; if the site changes, `docs/pipeline.md` is the map to update first.
- Fixtures and research scripts live in `research/` (sample HTML for the parser tests).
