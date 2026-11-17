import argparse
import html
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build 1-tap Mobile Upload Hub HTML.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(r"D:\Freelance Projects\video-engine\output\expedia-ishowspeed\manifest_batch2.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(r"D:\Freelance Projects\video-engine\output\expedia-ishowspeed\mobile_upload_pack.html"),
    )
    parser.add_argument(
        "--base-url",
        default="",
        help="Optional base URL prefix for video downloads (e.g. GitHub Release download URL).",
    )
    args = parser.parse_args()

    items = json.loads(args.manifest.read_text(encoding="utf-8"))
    base_url = args.base_url.rstrip("/")

    cards = []
    for i, it in enumerate(items, 1):
        t = html.escape(it["title"])
        c = html.escape(it["caption"])
        p = html.escape(it["pin"])
        fname = html.escape(it["clip"])
        dl_url = f"{base_url}/{fname}" if base_url else fname
        cards.append(
            f"""
    <div class="card" id="card-{i}">
      <div class="hdr">
        <span class="num">Clip {i}</span>
        <span class="fname">{fname}</span>
      </div>
      <a class="dl" href="{dl_url}" download="{fname}">Download Video ({fname})</a>
      <div class="row">
        <div class="lbl">Title</div>
        <div class="val" id="t-{i}">{t}</div>
        <button type="button" onclick="cp('t-{i}', this)">Copy Title</button>
      </div>
      <div class="row">
        <div class="lbl">Caption &amp; Hashtags</div>
        <div class="val" id="c-{i}">{c}</div>
        <button type="button" onclick="cp('c-{i}', this)">Copy Caption</button>
      </div>
      <div class="row">
        <div class="lbl">Pinned Comment</div>
        <div class="val" id="p-{i}">{p}</div>
        <button type="button" onclick="cp('p-{i}', this)">Copy Comment</button>
      </div>
    </div>"""
        )

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Expedia x IShowSpeed — Mobile Upload Hub</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background:#0b0f19; color:#f1f5f9; margin:0; padding:14px; }}
  h1 {{ font-size:18px; margin:0 0 12px; color:#facc15; }}
  .card {{ background:#151c2c; border:1px solid #26314a; border-radius:14px; padding:14px; margin-bottom:16px; }}
  .hdr {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; gap:8px; }}
  .num {{ background:#facc15; color:#000; font-weight:800; padding:3px 9px; border-radius:999px; font-size:12px; }}
  .fname {{ font-size:12px; color:#94a3b8; word-break:break-all; }}
  .dl {{ display:block; text-align:center; text-decoration:none; padding:11px; border-radius:8px; background:#facc15; color:#000; font-weight:800; font-size:14px; margin-bottom:8px; }}
  .row {{ background:#0e1422; border:1px solid #222c44; border-radius:10px; padding:10px; margin-top:8px; }}
  .lbl {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:#38bdf8; margin-bottom:4px; font-weight:700; }}
  .val {{ font-size:14px; line-height:1.4; margin-bottom:8px; white-space:pre-wrap; }}
  button {{ width:100%; padding:10px; border:0; border-radius:8px; background:#2563eb; color:#fff; font-weight:700; font-size:14px; cursor:pointer; }}
  button.ok {{ background:#16a34a; }}
</style>
</head>
<body>
  <h1>Expedia x IShowSpeed — Mobile Upload Hub</h1>
  {''.join(cards)}
<script>
function cp(id, btn) {{
  const txt = document.getElementById(id).innerText;
  const done = () => {{
    const orig = btn.innerText;
    btn.innerText = 'Copied!';
    btn.classList.add('ok');
    setTimeout(() => {{ btn.innerText = orig; btn.classList.remove('ok'); }}, 1400);
  }};
  if (navigator.clipboard && window.isSecureContext) {{
    navigator.clipboard.writeText(txt).then(done).catch(() => fallbackCopy(txt, done));
  }} else {{
    fallbackCopy(txt, done);
  }}
}}
function fallbackCopy(txt, done) {{
  const ta = document.createElement('textarea');
  ta.value = txt;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  document.execCommand('copy');
  document.body.removeChild(ta);
  done();
}}
</script>
</body>
</html>"""

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(page, encoding="utf-8")
    print("Wrote:", args.output)


if __name__ == "__main__":
    main()
