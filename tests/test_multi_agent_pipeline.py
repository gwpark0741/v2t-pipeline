import unittest

from v2t_single.clients.gemini_client import _build_video_part
from v2t_single.pipeline.nodes.multi_agent import (
    apply_routing,
    build_timestamp_tasks,
    finalize_draft_tracks,
)
from v2t_single.pipeline.schema import DraftTrackOutputModel


def _draft_tracks():
    return {
        "action_tracks": [
            {
                "event_type": "table_tennis_rally",
                "segments": [{"start": 2.0, "end": 18.5}],
                "description": "Fast paddle and ball impacts with sharp indoor reflections.",
                "audio_type": "sfx",
                "sound_layers": [
                    {
                        "layer_label": "paddle_ball_impacts",
                        "sound_type": "onset",
                        "onsets": [],
                        "coarse_segments": [{"start": 2.0, "end": 18.5}],
                        "description": "Sharp paddle and ball impact transients.",
                        "timing_strategy": "repeated_event",
                        "timing_confidence": "medium",
                        "sync_sensitivity": "high",
                    },
                    {
                        "layer_label": "serve_hit",
                        "sound_type": "onset",
                        "onsets": [],
                        "coarse_segments": [{"start": 2.0, "end": 4.0}],
                        "description": "Single bright serve impact.",
                        "timing_strategy": "single_event",
                        "coarse_event_time": 3.0,
                        "timing_confidence": "high",
                        "sync_sensitivity": "medium",
                    },
                ],
            }
        ],
        "background_tracks": [
            {
                "ambience_type": "indoor_room_tone",
                "segments": [{"start": 0.0, "end": 20.0}],
                "description": "Steady indoor air tone with mild room reflections.",
                "audio_type": "ambience",
                "sound_layers": [
                    {
                        "layer_label": "room_air_bed",
                        "sound_type": "continuous",
                        "segments": [{"start": 0.0, "end": 20.0}],
                        "description": "Low steady indoor room tone.",
                        "timing_strategy": "continuous",
                        "timing_confidence": "high",
                        "sync_sensitivity": "low",
                    }
                ],
            }
        ],
    }


class MultiAgentPipelineTests(unittest.TestCase):
    def test_video_part_supports_fps_and_offsets(self):
        part = _build_video_part(
            "files/video",
            video_fps=10,
            start_offset="1.500s",
            end_offset="3.500s",
        )

        self.assertEqual(part.video_metadata.fps, 10)
        self.assertEqual(part.video_metadata.start_offset, "1.500s")
        self.assertEqual(part.video_metadata.end_offset, "3.500s")

    def test_draft_schema_accepts_unrouted_empty_onsets(self):
        model = DraftTrackOutputModel.model_validate(_draft_tracks())

        self.assertEqual(len(model.action_tracks), 1)
        self.assertEqual(model.action_tracks[0].sound_layers[0].onsets, [])

    def test_timestamp_task_planning_skips_continuous_and_chunks_repeated(self):
        tasks = build_timestamp_tasks(
            draft_tracks=_draft_tracks(),
            duration=20.0,
            refinement_fps=10,
            single_event_padding_seconds=1.5,
            repeated_chunk_seconds=12.0,
            chunk_overlap_seconds=0.25,
        )

        repeated_tasks = [
            task for task in tasks
            if task["layer_label"] == "paddle_ball_impacts"
        ]
        single_tasks = [
            task for task in tasks
            if task["layer_label"] == "serve_hit"
        ]

        self.assertEqual(len(tasks), 3)
        self.assertEqual(len(repeated_tasks), 2)
        self.assertEqual(repeated_tasks[0]["start"], 2.0)
        self.assertEqual(repeated_tasks[0]["end"], 14.0)
        self.assertEqual(repeated_tasks[1]["start"], 13.75)
        self.assertEqual(repeated_tasks[1]["end"], 18.5)
        self.assertEqual(single_tasks[0]["start"], 1.5)
        self.assertEqual(single_tasks[0]["end"], 4.5)

    def test_routing_and_finalize_produce_strict_output(self):
        draft = _draft_tracks()
        draft["action_tracks"][0]["sound_layers"][0]["onsets"] = [2.5, 3.0, 3.5, 4.0, 4.5]
        draft["action_tracks"][0]["sound_layers"][0]["timestamp_confidence"] = "medium"
        draft["action_tracks"][0]["sound_layers"][1]["onsets"] = [3.05]
        draft["action_tracks"][0]["sound_layers"][1]["timestamp_confidence"] = "high"

        routed = apply_routing(draft)
        finalized = finalize_draft_tracks(routed)

        self.assertEqual(finalized["action_tracks"][0]["generation_model"], "v2a")
        layer_payload = finalized["action_tracks"][0]["sound_layers"][0]
        self.assertNotIn("timing_strategy", layer_payload)
        self.assertNotIn("coarse_segments", layer_payload)
        self.assertEqual(layer_payload["sound_type"], "onset")
        self.assertEqual(layer_payload["onsets"], [2.5, 3.0, 3.5, 4.0, 4.5])
        self.assertEqual(layer_payload["layer_id"], "act_001_layer_001")


if __name__ == "__main__":
    unittest.main()
