import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from caption_styles import CAPTION_PRESETS, build_styled_ass
from hook_renderer import HOOK_STYLES, compute_hook_y, create_hook_image
from viral_selector import (
    build_transcript_windows,
    clip_count_targets,
    dedupe_overlapping,
    score_batches,
    shortlist_target,
    snap_clip_to_words,
    trim_to_best,
)


class ViralPipelineUnitTests(unittest.TestCase):
    def test_windowing_and_batching(self) -> None:
        segments = []
        t = 0.0
        for i in range(15):
            segments.append(
                {
                    "id": i + 1,
                    "start": t,
                    "end": t + 20.0,
                    "text": f"Segment {i + 1} crazy moment wait look at that!",
                    "words": [
                        {"word": "Segment", "start": t + 0.1, "end": t + 0.5},
                        {"word": "crazy", "start": t + 1.0, "end": t + 1.4},
                        {"word": "look!", "start": t + 18.0, "end": t + 18.8},
                    ],
                }
            )
            t += 20.0
        energies = [0.2] * 300
        energies[45] = 0.95

        windows = build_transcript_windows({"segments": segments}, video_duration=300.0, energies=energies)
        self.assertGreaterEqual(len(windows), 3)
        self.assertAlmostEqual(windows[0]["peak_audio_energy"], 0.95, places=2)

        batches = score_batches(windows, batch_size=2)
        self.assertTrue(all(len(b) >= 1 for b in batches))
        self.assertEqual(sum(len(b) for b in batches), len(windows))
        self.assertGreaterEqual(shortlist_target(300.0), 3)
        low, high = clip_count_targets(len(windows), top_n=5)
        self.assertLessEqual(low, high)

    def test_dedupe_snap_and_trim(self) -> None:
        words = [
            {"word": "Wait", "start": 10.2, "end": 10.6},
            {"word": "what", "start": 10.7, "end": 11.0},
            {"word": "just", "start": 25.0, "end": 25.4},
            {"word": "happened", "start": 34.0, "end": 34.8},
        ]
        s, e = snap_clip_to_words(10.3, 34.5, words, video_duration=120.0, min_duration=15.0, max_duration=45.0)
        self.assertLess(s, 10.2)
        self.assertGreater(e, 34.8)

        clips = [
            {"start": 10.0, "end": 40.0, "predicted_score": 82},
            {"start": 12.0, "end": 42.0, "predicted_score": 91},  # overlaps heavily, higher score wins
            {"start": 60.0, "end": 90.0, "predicted_score": 76},
        ]
        deduped = dedupe_overlapping(clips, ratio=0.25)
        self.assertEqual(len(deduped), 2)
        self.assertEqual([c["predicted_score"] for c in deduped], [91, 76])

        best = trim_to_best(deduped, max_clips=1)
        self.assertEqual(len(best), 1)
        self.assertEqual(best[0]["predicted_score"], 91)

    def test_hook_renderer_styles_and_placement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for style in ("pill", "yellow", "outline"):
                self.assertIn(style, HOOK_STYLES)
                out = Path(tmp) / f"hook_{style}.png"
                path, w, h = create_hook_image("HE ACTUALLY LOST IT OVER THIS 😭🔥", out, style=style)
                self.assertTrue(path.exists())
                self.assertGreater(w, 200)
                self.assertGreater(h, 60)
                with Image.open(path) as img:
                    self.assertEqual(img.mode, "RGBA")

            self.assertEqual(compute_hook_y("split", 160), 724)
            cy = compute_hook_y("center", 160)
            self.assertGreaterEqual(cy, 220)
            self.assertLessEqual(cy + 160, 1280)

    def test_caption_presets_generate_ass(self) -> None:
        words = [
            {"word": "WAIT", "start": 0.0, "end": 0.35},
            {"word": "BRO", "start": 0.4, "end": 0.75},
            {"word": "LOOK!", "start": 0.8, "end": 1.3},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for preset in CAPTION_PRESETS:
                ass_path = Path(tmp) / f"{preset}.ass"
                ok = build_styled_ass(words, clip_start=0.0, ass_path=ass_path, preset=preset, layout="split")
                self.assertTrue(ok)
                txt = ass_path.read_text(encoding="utf-8")
                self.assertIn("Dialogue: 0,", txt)
                if preset in ("pill", "lime"):
                    self.assertIn("CaptionActiveBox", txt)

    def test_mobile_pack_renders_with_and_without_virality(self) -> None:
        from build_mobile_pack import build_card

        legacy = {"clip": "a.mp4", "title": "T", "caption": "C", "pin": "P", "hook": "H"}
        html_legacy = build_card(legacy, "id1", "https://example.com")
        self.assertIn("a.mp4", html_legacy)
        self.assertNotIn("vscore", html_legacy)

        viral = {**legacy, "viralityScore": 91, "why": "Huge payoff at 0:14"}
        html_viral = build_card(viral, "id2", "https://example.com")
        self.assertIn("91/100", html_viral)
        self.assertIn("Huge payoff at 0:14", html_viral)

    def test_selector_fallback_and_strict_schema(self) -> None:
        from viral_selector import DetailResponse, _strict_json_schema, build_gemini_model_candidates

        models = build_gemini_model_candidates("gemini-3.5-flash")
        self.assertEqual(models[0], "gemini-3.5-flash")
        self.assertEqual(len(models), len(set(models)))
        self.assertIn("gemini-3.6-flash", models)
        self.assertEqual(shortlist_target(300.0), 3)
        self.assertEqual(shortlist_target(900.0), 4)

        from auto_batch_worker import _daily_clip_count, _record_daily_clips
        st: dict = {}
        _record_daily_clips(st, 4, day_key="2026-11-20")
        _record_daily_clips(st, 3, day_key="2026-11-20")
        self.assertEqual(_daily_clip_count(st, day_key="2026-11-20"), 7)
        self.assertEqual(_daily_clip_count(st, day_key="2026-11-21"), 0)

        schema = _strict_json_schema(DetailResponse)
        self.assertFalse(schema.get("additionalProperties", True))
        clip_def = schema["$defs"]["DetailClipModel"]
        self.assertFalse(clip_def.get("additionalProperties", True))
        self.assertEqual(set(clip_def["required"]), set(clip_def["properties"].keys()))

    def test_socialclaw_slot_spacing_and_payloads(self) -> None:
        from datetime import datetime, timezone
        from socialclaw_publish import build_platform_post, compute_next_slot, provider_daily_cap

        now = datetime(2026, 11, 20, 14, 0, tzinfo=timezone.utc)
        existing = [
            datetime(2026, 11, 20, 14, 15, tzinfo=timezone.utc),
            datetime(2026, 11, 20, 14, 45, tzinfo=timezone.utc),
        ]
        slot = compute_next_slot(existing, now_utc=now, spacing_minutes=30, daily_cap=45)
        self.assertEqual(slot, datetime(2026, 11, 20, 15, 15, tzinfo=timezone.utc))

        # Daily cap + rolling 24h window rollover
        capped_slot = compute_next_slot(existing, now_utc=now, spacing_minutes=30, daily_cap=2)
        self.assertGreaterEqual(capped_slot, datetime(2026, 11, 21, 14, 20, tzinfo=timezone.utc))
        self.assertEqual(provider_daily_cap("youtube"), 9)
        self.assertEqual(provider_daily_cap("tiktok"), 45)

        item = {
            "title": "Lacy Loses It in GTA 6!",
            "caption": "Wild GTA 6 robbery! #GTA6 #LACY",
            "tiktokCaption": "Bro tried a minivan getaway 💀 #GTA6 #LACY",
            "instagramCaption": "Minivan chase goes wrong 😭 #GTA6 #Reels",
            "youtubeTitle": "He Stole a Minivan in GTA 6!",
            "pin": "Best moment yet",
        }
        tt = build_platform_post("tiktok", "tiktok:@ishowspeedfan177", item, "https://example.com/a.mp4", "2026-11-20T15:15:00.000Z")
        self.assertNotIn("name", tt)
        self.assertEqual(tt["settings"]["privacyLevel"], "PUBLIC_TO_EVERYONE")

        ig = build_platform_post("instagram", "instagram:standalone:123", item, "https://example.com/a.mp4", "2026-11-20T15:15:00.000Z")
        self.assertEqual(ig["settings"]["instagramPublishMode"], "reel")

        yt = build_platform_post("youtube", "youtube:channel:abc", item, "https://example.com/a.mp4", "2026-11-20T15:15:00.000Z")
        self.assertIn("#Shorts", yt["name"])
        self.assertEqual(yt["settings"]["privacyStatus"], "public")


if __name__ == "__main__":
    unittest.main()
