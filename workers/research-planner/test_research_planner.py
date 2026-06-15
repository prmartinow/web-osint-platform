import unittest

import research_planner as planner


class ResearchPlannerTests(unittest.TestCase):
    def test_user_seed_candidate_has_high_priority_task(self):
        evidence = {
            "evidence_id": "user_input/note-1",
            "source_kind": "user_input",
            "title": "Agent harness lead",
            "text_preview": "Look into new coding agent harness benchmarks.",
            "topics": ["Agent Harnesses"],
            "entities": ["OpenCode"],
        }
        annotations = [
            {"annotation_id": "ann-1", "label_id": "source.user.input"},
            {"annotation_id": "ann-2", "label_id": "quality.user_supplied"},
            {"annotation_id": "ann-3", "label_id": "topic.agent_harnesses"},
        ]

        candidate = planner.classify_candidate(evidence, annotations)

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["signal"]["signal_type"], "user_seed")
        self.assertEqual(candidate["question"]["question_type"], "research_direction")
        self.assertEqual(candidate["task"]["task_type"], "expand_user_seed")
        self.assertGreater(candidate["task"]["priority"], 0.8)
        self.assertEqual(candidate["signal"]["topic_label_id"], "topic.agent_harnesses")

    def test_compare_candidate_is_deterministic(self):
        evidence = {
            "evidence_id": "web_document/doc-1",
            "source_kind": "web_page",
            "title": "Leaderboard",
            "text_preview": "Benchmark score table.",
            "topics": ["Benchmarks"],
            "entities": ["Model X"],
        }
        annotations = [
            {"annotation_id": "ann-1", "label_id": "action.compare"},
            {"annotation_id": "ann-2", "label_id": "topic.benchmarks"},
        ]

        first = planner.classify_candidate(evidence, annotations)
        second = planner.classify_candidate(evidence, annotations)

        self.assertEqual(first["signal"]["signal_id"], second["signal"]["signal_id"])
        self.assertEqual(first["question"]["question_id"], second["question"]["question_id"])
        self.assertEqual(first["task"]["dedupe_key"], second["task"]["dedupe_key"])
        self.assertEqual(first["task"]["task_type"], "collect_comparison_evidence")

    def test_build_outputs_skips_unlabeled_evidence(self):
        outputs = planner.build_outputs(
            [{"evidence_id": "capture/1", "topics": [], "entities": []}],
            {},
        )
        self.assertEqual(outputs, [])


if __name__ == "__main__":
    unittest.main()
