import argparse
import html
import json
from pathlib import Path


def build_card(item: dict, uid: str, base_url: str) -> str:
    t = html.escape(item["title"])
    c = html.escape(item["caption"])
    p = html.escape(item["pin"])
    fname = html.escape(item["clip"])
    hook = html.escape(item.get("hook", ""))
    score = item.get("viralityScore")
    why = html.escape(item.get("why", ""))
    dl_url = f"{base_url.rstrip('/')}/{fname}" if base_url else fname
    score_html = f'<span class="vscore">🔥 {int(score)}/100</span>' if score is not None else ""
    hook_html = f'<div class="hook">{hook}</div>' if hook else ""
    why_html = f'<div class="why">{why}</div>' if why else ""
    return f"""
      <div class="card" data-id="{uid}">
        <div class="hdr">
          <span class="num">{fname} {score_html}</span>
          <button type="button" class="mark-btn" onclick="togglePosted('{uid}', this)">Mark Posted</button>
        </div>
        {hook_html}
        {why_html}
        <a class="dl" href="{dl_url}" download="{fname}">Download Video</a>
        <div class="row">
          <div class="lbl">Title</div>
          <div class="val" id="t-{uid}">{t}</div>
          <button type="button" onclick="cp('t-{uid}', this)">Copy Title</button>
        </div>
        <div class="row">
          <div class="lbl">Caption &amp; Hashtags</div>
          <div class="val" id="c-{uid}">{c}</div>
          <button type="button" onclick="cp('c-{uid}', this)">Copy Caption</button>
        </div>
        <div class="row">
          <div class="lbl">Pinned Comment</div>
          <div class="val" id="p-{uid}">{p}</div>
          <button type="button" onclick="cp('p-{uid}', this)">Copy Comment</button>
        </div>
      </div>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build folder-structured 1-tap Mobile Upload Hub HTML.")
    parser.add_argument("--config", type=Path, required=True, help="JSON config describing folders -> batches -> manifests.")
    parser.add_argument("--output", type=Path, required=True, help="Output HTML path.")
    args = parser.parse_args()

    folders = json.loads(args.config.read_text(encoding="utf-8"))
    folder_blocks = []

    for f_idx, folder in enumerate(folders):
        f_name = html.escape(folder["folder"])
        f_sub = html.escape(folder.get("subtitle", ""))
        batch_blocks = []
        for b_idx, batch in enumerate(folder["batches"]):
            b_name = html.escape(batch["batch"])
            base_url = batch.get("baseUrl", "")
            items = json.loads(Path(batch["manifest"]).read_text(encoding="utf-8"))
            cards = [
                build_card(it, f"f{f_idx}-b{b_idx}-c{c_idx}", base_url)
                for c_idx, it in enumerate(items, 1)
            ]
            batch_blocks.append(
                f"""
      <details class="batch" {'open' if f_idx == 0 and b_idx == 0 else ''}>
        <summary>
          <span>📦 {b_name}</span>
          <span class="badge" data-batch="f{f_idx}-b{b_idx}">{len(items)} clips</span>
        </summary>
        <div class="batch-body">
          {''.join(cards)}
        </div>
      </details>"""
            )
        folder_blocks.append(
            f"""
    <details class="folder" {'open' if f_idx == 0 else ''}>
      <summary>
        <div>
          <div class="f-title">📁 {f_name}</div>
          <div class="f-sub">{f_sub}</div>
        </div>
      </summary>
      <div class="folder-body">
        {''.join(batch_blocks)}
      </div>
    </details>"""
        )

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Clipper Hub — Mobile Upload Manager</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background:#090d16; color:#f1f5f9; margin:0; padding:14px; padding-bottom:48px; }}
  h1 {{ font-size:19px; margin:0 0 10px; color:#facc15; }}
  .tabs {{ display:flex; gap:8px; margin-bottom:14px; position:sticky; top:0; background:#090d16; padding:8px 0; z-index:10; }}
  .tab {{ flex:1; padding:10px 8px; border-radius:10px; border:1px solid #26314a; background:#131a2a; color:#cbd5e1; font-weight:700; font-size:13px; cursor:pointer; }}
  .tab.active {{ background:#2563eb; border-color:#3b82f6; color:#fff; }}
  details.folder {{ background:#111827; border:1px solid #26314a; border-radius:14px; margin-bottom:14px; overflow:hidden; }}
  details.folder > summary {{ list-style:none; padding:14px; cursor:pointer; display:flex; justify-content:space-between; align-items:center; background:#162033; }}
  .f-title {{ font-size:16px; font-weight:800; color:#f8fafc; }}
  .f-sub {{ font-size:12px; color:#94a3b8; margin-top:2px; }}
  .folder-body {{ padding:10px; }}
  details.batch {{ background:#0d1320; border:1px solid #1f2a40; border-radius:12px; margin-bottom:10px; overflow:hidden; }}
  details.batch > summary {{ list-style:none; padding:11px 12px; cursor:pointer; display:flex; justify-content:space-between; align-items:center; font-weight:700; font-size:14px; color:#38bdf8; }}
  .badge {{ background:#1e293b; color:#cbd5e1; font-size:11px; padding:3px 8px; border-radius:999px; }}
  .batch-body {{ padding:10px; }}
  .card {{ background:#151c2c; border:1px solid #26314a; border-radius:12px; padding:12px; margin-bottom:12px; }}
  .card.is-posted {{ opacity:0.65; border-color:#16a34a; }}
  .hdr {{ display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:8px; }}
  .num {{ font-size:12px; color:#94a3b8; word-break:break-all; font-weight:600; }}
  .mark-btn {{ width:auto; padding:6px 10px; font-size:12px; border-radius:8px; background:#16a34a; color:#fff; border:0; font-weight:700; cursor:pointer; white-space:nowrap; }}
  .card.is-posted .mark-btn {{ background:#475569; }}
  .vscore {{ display:inline-block; background:#7c2d12; color:#fed7aa; padding:2px 7px; border-radius:999px; font-size:11px; font-weight:800; margin-left:4px; }}
  .hook {{ font-size:12px; font-weight:700; color:#facc15; margin-bottom:5px; }}
  .why {{ font-size:11px; color:#94a3b8; margin-bottom:8px; line-height:1.35; }}
  .dl {{ display:block; text-align:center; text-decoration:none; padding:10px; border-radius:8px; background:#facc15; color:#000; font-weight:800; font-size:14px; margin-bottom:8px; }}
  .row {{ background:#0b101b; border:1px solid #222c44; border-radius:9px; padding:9px; margin-top:7px; }}
  .lbl {{ font-size:10px; text-transform:uppercase; letter-spacing:.06em; color:#38bdf8; margin-bottom:3px; font-weight:700; }}
  .val {{ font-size:13px; line-height:1.4; margin-bottom:7px; white-space:pre-wrap; }}
  .row button {{ width:100%; padding:9px; border:0; border-radius:7px; background:#2563eb; color:#fff; font-weight:700; font-size:13px; cursor:pointer; }}
  .row button.ok {{ background:#16a34a; }}
  .hidden {{ display:none !important; }}
</style>
</head>
<body>
  <h1>Clipper Hub — Upload Manager</h1>
  <div class="tabs">
    <button class="tab active" id="tab-pending" onclick="setFilter('pending')">To Post (<span id="cnt-pending">0</span>)</button>
    <button class="tab" id="tab-posted" onclick="setFilter('posted')">Posted (<span id="cnt-posted">0</span>)</button>
    <button class="tab" id="tab-all" onclick="setFilter('all')">All</button>
  </div>
  {''.join(folder_blocks)}
<script>
const KEY = 'clipper_posted_v1';
let filterMode = 'pending';
function getPosted() {{
  try {{ return JSON.parse(localStorage.getItem(KEY) || '{{}}'); }} catch {{ return {{}}; }}
}}
function savePosted(map) {{
  localStorage.setItem(KEY, JSON.stringify(map));
}}
function togglePosted(id) {{
  const map = getPosted();
  if (map[id]) delete map[id]; else map[id] = Date.now();
  savePosted(map);
  renderState();
}}
function setFilter(mode) {{
  filterMode = mode;
  document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + mode).classList.add('active');
  renderState();
}}
function renderState() {{
  const map = getPosted();
  let pending = 0, posted = 0;
  document.querySelectorAll('.card').forEach(card => {{
    const id = card.dataset.id;
    const isP = !!map[id];
    const btn = card.querySelector('.mark-btn');
    if (isP) {{
      posted++;
      card.classList.add('is-posted');
      btn.innerText = 'Restore';
    }} else {{
      pending++;
      card.classList.remove('is-posted');
      btn.innerText = '✓ Mark Posted & Hide';
    }}
    const show = (filterMode === 'all') || (filterMode === 'pending' && !isP) || (filterMode === 'posted' && isP);
    card.classList.toggle('hidden', !show);
  }});
  document.getElementById('cnt-pending').innerText = pending;
  document.getElementById('cnt-posted').innerText = posted;
}}
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
renderState();
</script>
</body>
</html>"""

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(page, encoding="utf-8")
    print("Wrote folder-structured Mobile Upload Hub ->", args.output)


if __name__ == "__main__":
    main()
