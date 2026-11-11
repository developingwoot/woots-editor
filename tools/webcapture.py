"""B-roll from a web page: the host pastes a URL on a clip and gets a short video of that page, optionally with words on it highlighted.

Two styles:
  still  - a picture of the page (scrolled to the words when given) with a slow push-in
  scroll - a recording of the page scrolling down to the words, which are then highlighted like a marker pen
The clip is 1920x1080, 30 fps, no sound, written into the video's work folder (never into the footage folder). The page's address and title are kept
so publishing can credit it.

Safety: only http and https addresses on the public internet. Every request the page makes is checked too, so a page cannot reach this computer
or the local network. Nothing is signed in to and nothing is clicked: cookie banners are hidden, never accepted.

Usage (the app runs this in its own process):  python webcapture.py '<json: {"url", "out", "style", "find", "seconds"}>'
Prints one line of JSON: {"ok": true, "file", "still", "title", "url", "found"} or {"ok": false, "error"}.
"""
import hashlib
import ipaddress
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

STYLES = ("still", "scroll")
W, H, FPS = 1920, 1080, 30
MIN_S, MAX_S = 2.0, 12.0
LOAD_TIMEOUT_MS = 30000


def check_url(url: str, allow_local: bool = False) -> str:
    """The address as given when it may be opened; ValueError with a plain sentence when not. `allow_local` is for the tests' own page only."""
    url = str(url or "").strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError("give a web address that starts with http:// or https://")
    if parts.username or parts.password:
        raise ValueError("give the address without a user name or password in it")
    host = parts.hostname
    if not host:
        raise ValueError("that web address has no site in it")
    if not allow_local and not host_is_public(host):
        raise ValueError("that address is on this computer or a private network, so it is not opened")
    return url


_seen: dict = {}


def host_is_public(host: str) -> bool:
    """True when every address the name resolves to is on the public internet (cached for one capture)."""
    if host in _seen:
        return _seen[host]
    try:
        infos = socket.getaddrinfo(host, None)
        ips = {i[4][0].split("%")[0] for i in infos}
        ok = bool(ips) and all(ipaddress.ip_address(ip).is_global for ip in ips)
    except (OSError, ValueError):
        ok = False
    _seen[host] = ok
    return ok


def out_name(url: str, style: str, find: str) -> str:
    """The same page, style and words always give the same file name (a capture is not repeated by accident)."""
    return "web-" + hashlib.sha1(f"{url}|{style}|{find}".encode("utf-8")).hexdigest()[:12]


def seconds_of(x) -> float:
    try:
        s = float(x)
    except (TypeError, ValueError):
        s = 5.0
    return round(min(MAX_S, max(MIN_S, s)), 1)


# Runs in the page: hide what covers it (cookie and sign-up banners), find the words, scroll to them, draw the highlight over them.
HIDE_JS = r"""() => {
  const bad = /cookie|consent|gdpr|onetrust|didomi|cmp-|truste|usercentrics|newsletter|subscribe|paywall/i;
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if ((cs.position === 'fixed' || cs.position === 'sticky') && (bad.test(el.id + ' ' + el.className + ' ' + (el.getAttribute('aria-label') || '')) || bad.test((el.innerText || '').slice(0, 300)))) {
      el.style.setProperty('display', 'none', 'important');
    }
  }
  document.documentElement.style.setProperty('overflow', 'auto', 'important');
  document.body.style.setProperty('overflow', 'auto', 'important');
}"""

FIND_JS = r"""(needle) => {
  // A range over the first place the words appear, ignoring case and spacing. Returns its top in the page, or null.
  const norm = s => s.toLowerCase().replace(/\s+/g, ' ');
  const want = norm(needle).trim();
  if (!want) return null;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, { acceptNode: n => n.parentElement && n.parentElement.offsetParent !== null ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT });
  const nodes = [], map = [];
  let text = '';
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const s = n.nodeValue;
    for (let i = 0; i < s.length; i++) {
      const ch = /\s/.test(s[i]) ? ' ' : s[i].toLowerCase();
      if (ch === ' ' && text.endsWith(' ')) continue;
      text += ch; map.push([nodes.length, i]);
    }
    nodes.push(n);
  }
  const at = text.indexOf(want);
  if (at < 0) return null;
  const [n0, i0] = map[at], [n1, i1] = map[at + want.length - 1];
  const r = document.createRange();
  r.setStart(nodes[n0], i0); r.setEnd(nodes[n1], i1 + 1);
  window.__wrRange = r;
  const box = r.getBoundingClientRect();
  return box.top + window.scrollY;
}"""

MARK_JS = r"""(ms) => {
  // Marker-pen boxes over each line of the found words, drawn left to right one line after another (ms = how long the whole sweep takes; 0 = drawn at once).
  const r = window.__wrRange;
  if (!r) return false;
  const rects = [...r.getClientRects()].filter(x => x.width > 2 && x.height > 2);
  const each = rects.length ? ms / rects.length : 0;
  rects.forEach((x, i) => {
    const m = document.createElement('div');
    m.style.cssText = `position:absolute;left:${x.left + window.scrollX - 4}px;top:${x.top + window.scrollY - 2}px;height:${x.height + 4}px;width:${ms ? 0 : x.width + 8}px;`
      + `background:rgba(255,214,0,.45);border-radius:3px;mix-blend-mode:multiply;pointer-events:none;z-index:2147483647;`
      + (ms ? `transition:width ${each}ms ease-out ${i * each}ms;` : '');
    document.body.appendChild(m);
    if (ms) requestAnimationFrame(() => requestAnimationFrame(() => { m.style.width = (x.width + 8) + 'px'; }));
  });
  return rects.length > 0;
}"""

SCROLL_JS = r"""([y, ms]) => new Promise(done => {
  // Ease the page down to y (the words a third of the way down the screen) over ms.
  const from = window.scrollY, to = Math.max(0, y - window.innerHeight / 3), t0 = performance.now();
  const ease = t => t < .5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
  const step = now => { const t = Math.min(1, (now - t0) / ms); window.scrollTo(0, from + (to - from) * ease(t)); t < 1 ? requestAnimationFrame(step) : done(); };
  requestAnimationFrame(step);
})"""


def ffmpeg() -> str:
    try:
        import platformx
        for d in platformx.ffmpeg_dirs():
            p = Path(d) / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
            if p.is_file():
                return str(p)
    except Exception:                       # noqa: BLE001  (fall back to the PATH)
        pass
    return "ffmpeg"


def still_cmd(png: Path, out: Path, seconds: float) -> list:
    """A picture of the page becomes a clip with a slow push-in toward the middle (8 % over the clip)."""
    frames = int(round(seconds * FPS))
    zoom = f"min(1+0.08*on/{max(1, frames - 1)},1.08)"
    vf = (f"scale={W * 2}:-2,crop={W * 2}:{H * 2},zoompan=z='{zoom}':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},format=yuv420p")
    return [ffmpeg(), "-y", "-loglevel", "error", "-loop", "1", "-i", str(png), "-vf", vf, "-frames:v", str(frames), "-an",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(out)]


def video_cmd(webm: Path, out: Path, start: float, seconds: float) -> list:
    """The browser's recording (from when the page was ready) becomes a clip of `seconds`; the last frame is held if the recording is short."""
    vf = f"fps={FPS},scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:white,tpad=stop_mode=clone:stop_duration={seconds},format=yuv420p"
    return [ffmpeg(), "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-i", str(webm), "-vf", vf, "-t", f"{seconds:.2f}", "-an",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(out)]


def capture(url: str, out_dir: Path, style: str = "scroll", find: str = "", seconds=5.0, allow_local: bool = False) -> dict:
    """Open the page, capture it, write <out_dir>/<name>.mp4 and .png. Returns {file, still, title, url, found}. Raises ValueError with a plain sentence."""
    from playwright.sync_api import Error as PwError
    from playwright.sync_api import sync_playwright
    url = check_url(url, allow_local)
    if style not in STYLES:
        raise ValueError("unknown style")
    seconds = seconds_of(seconds)
    find = " ".join(str(find or "").split())[:300]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / out_name(url, style, find)
    mp4, png = base.with_suffix(".mp4"), base.with_suffix(".png")
    rec_dir = out_dir / (base.name + "-rec")

    def guard(route):                       # every request of the page: never this computer or the local network
        host = urlsplit(route.request.url).hostname or ""
        scheme = urlsplit(route.request.url).scheme
        if scheme in ("data", "blob") or (scheme in ("http", "https") and (allow_local or host_is_public(host))):
            return route.continue_()
        return route.abort()

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except PwError as e:
            raise ValueError("the browser for web pages is not installed: run setup again (it installs it)") from e
        try:
            opts = {"viewport": {"width": W, "height": H}, "device_scale_factor": 1, "locale": "en-US", "java_script_enabled": True}
            if style == "scroll":
                opts.update(record_video_dir=str(rec_dir), record_video_size={"width": W, "height": H})
            ctx = browser.new_context(**opts)
            t0 = time.monotonic()
            page = ctx.new_page()
            page.route("**/*", guard)
            try:
                page.goto(url, wait_until="load", timeout=LOAD_TIMEOUT_MS)
            except PwError as e:
                raise ValueError(f"the page could not be opened ({str(e).splitlines()[0][:120]})") from e
            page.wait_for_timeout(800)                      # late layout and web fonts
            page.evaluate(HIDE_JS)
            title = (page.title() or "").strip()[:200]
            final_url = page.url
            y = page.evaluate(FIND_JS, find) if find else None
            found = y is not None
            ready = time.monotonic() - t0
            if style == "still":
                if found:
                    page.evaluate(f"window.scrollTo(0, Math.max(0, {y} - window.innerHeight / 3))")
                    page.wait_for_timeout(300)
                    page.evaluate(MARK_JS, 0)
                page.screenshot(path=str(png))
                ctx.close()
            else:
                travel = seconds * (0.45 if found else 0.8)
                if found:
                    page.evaluate(SCROLL_JS, [y, int(travel * 1000)])
                    page.evaluate(MARK_JS, int(seconds * 0.25 * 1000))
                else:                                       # no words to find: a gentle scroll down the page
                    page.evaluate(SCROLL_JS, [H * 1.5, int(travel * 1000)])
                page.wait_for_timeout(int(max(0.5, seconds - travel - (seconds * 0.25 if found else 0)) * 1000))
                page.screenshot(path=str(png))
                video = page.video
                ctx.close()                                 # the recording is written when the context closes
                webm = Path(video.path())
        finally:
            browser.close()
    if style == "still":
        cmd = still_cmd(png, mp4, seconds)
    else:
        cmd = video_cmd(webm, mp4, max(0.0, ready - 0.2), seconds)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if style == "scroll":
        import shutil
        shutil.rmtree(rec_dir, ignore_errors=True)
    if r.returncode != 0 or not mp4.is_file():
        raise ValueError(f"the clip could not be made: {(r.stderr or '').strip()[-200:]}")
    return {"file": str(mp4), "still": str(png), "title": title, "url": final_url, "found": found, "seconds": seconds, "style": style}


def capture_apart(url: str, out_dir, style: str, find: str, seconds, env=None, timeout: int = 180) -> dict:
    """capture() in a process of its own (the browser never runs inside the app's server): {"ok", ...capture's result} or {"ok": False, "error"}."""
    import platformx
    arg = json.dumps({"url": url, "out": str(out_dir), "style": style, "find": find, "seconds": seconds})
    try:
        p = subprocess.run([sys.executable, os.path.abspath(__file__), arg], cwd=os.path.dirname(os.path.abspath(__file__)), env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, creationflags=platformx.NO_WINDOW)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "the page took too long to capture"}
    out = (p.stdout or "").strip()
    return json.loads(out.splitlines()[-1]) if out else {"ok": False, "error": (p.stderr or "")[-300:] or "the page could not be captured"}


def main(argv: list) -> int:
    try:
        a = json.loads(argv[1])
        out = capture(a["url"], Path(a["out"]), a.get("style", "scroll"), a.get("find", ""), a.get("seconds", 5.0))
        print(json.dumps({"ok": True, **out}))
        return 0
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    except Exception as e:                  # noqa: BLE001  (anything else: one plain line, not a traceback in the job bar)
        print(json.dumps({"ok": False, "error": f"the page could not be captured ({type(e).__name__}: {str(e)[:160]})"}))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
