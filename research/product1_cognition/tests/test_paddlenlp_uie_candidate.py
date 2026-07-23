from __future__ import annotations

import unittest

from experimental_providers.paddlenlp_uie_interaction_candidate import PaddleNLPUIEInteractionCandidateProvider


class PaddleNLPUIECandidateTests(unittest.TestCase):
    def test_candidate_keeps_per_label_confidence_and_evidence_spans(self) -> None:
        def fake_taskflow(_: str):
            return [{
                "困惑表达": [{"text": "不明白", "probability": 0.96}],
                "提示请求": [{"text": "给一点提示", "probability": 0.42}],
            }]

        candidate = PaddleNLPUIEInteractionCandidateProvider(fake_taskflow).classify(
            source_event_id="conversation-1", text="我不明白，给一点提示",
        )
        payload = candidate.as_interaction_payload()
        self.assertEqual(payload["candidate_source_event_id"], "conversation-1")
        self.assertTrue(payload["interaction_labels"]["confusion_risk"])
        self.assertEqual(payload["interaction_label_confidences"]["hint_dependency"], 0.42)
        self.assertEqual(payload["candidate_evidence_spans"]["confusion_risk"], ["不明白"])
        self.assertEqual(payload["candidate_model_version"], "uie-mini")


if __name__ == "__main__":
    unittest.main()
