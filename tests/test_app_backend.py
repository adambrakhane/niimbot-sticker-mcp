import unittest

from niimbot.app_backend.agent import extract_requested_count, normalize_drafts
from niimbot.app_backend.protocol import draft_from_dict


class AppBackendTests(unittest.TestCase):
    def test_extract_requested_count_supports_digits(self):
        self.assertEqual(extract_requested_count("make me 3 stickers for launch"), 3)

    def test_extract_requested_count_supports_words(self):
        self.assertEqual(extract_requested_count("I want three stickers"), 3)

    def test_normalize_drafts_trims_to_requested_count(self):
        payload = {
            "drafts": [
                {"category": "ticket", "title": "One"},
                {"category": "idea", "title": "Two"},
                {"category": "urgent", "title": "Three"},
            ]
        }
        normalized = normalize_drafts(payload, 2, "niimbot")
        self.assertEqual(len(normalized), 2)
        self.assertEqual(normalized[1]["title"], "Two")

    def test_normalize_drafts_pads_when_agent_returns_too_few(self):
        payload = {"drafts": [{"category": "idea", "title": "BLE reconnect"}]}
        normalized = normalize_drafts(payload, 3, "niimbot")
        self.assertEqual(len(normalized), 3)
        self.assertEqual(normalized[0]["project"], "niimbot")
        self.assertEqual(normalized[2]["title"], "BLE reconnect (3)")

    def test_draft_from_dict_preserves_expected_fields(self):
        draft = draft_from_dict(
            {
                "id": "abc",
                "category": "urgent",
                "title": "Fix prod",
                "body": "now",
                "project": "niimbot",
                "reference": "OPS-1",
                "preview_png_base64": "zzz",
                "is_dirty": True,
                "status": "failed",
                "error_message": "printer offline",
            }
        )
        self.assertEqual(draft.id, "abc")
        self.assertEqual(draft.reference, "OPS-1")
        self.assertTrue(draft.is_dirty)
