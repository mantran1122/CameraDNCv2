import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dahua_client  # noqa: E402


class DahuaEventParserTest(unittest.TestCase):
    def test_parses_semicolon_separated_event_record(self):
        listener = dahua_client.DahuaNVRListener()
        with patch.object(dahua_client.config, "ACTIVE_CHANNELS", [5]), \
             patch.object(dahua_client.database, "save_event", return_value=42) as save_event, \
             patch.object(dahua_client.database, "get_event_by_id", return_value=None):
            listener.process_event_block("Code=HumanTrait;action=Start;index=4")

        self.assertEqual(save_event.call_count, 1)
        self.assertEqual(save_event.call_args.kwargs["event_code"], "HumanTrait")
        self.assertEqual(save_event.call_args.kwargs["channel"], 5)
        self.assertEqual(save_event.call_args.kwargs["metadata_dict"]["action"], "Start")

    def test_accepts_case_variants_from_nvr_firmware(self):
        listener = dahua_client.DahuaNVRListener()
        with patch.object(dahua_client.config, "ACTIVE_CHANNELS", [1]), \
             patch.object(dahua_client.database, "save_event", return_value=43) as save_event, \
             patch.object(dahua_client.database, "get_event_by_id", return_value=None):
            listener.process_event_block("code=HumanTrait;Action=START;Index=0")
        self.assertEqual(save_event.call_args.kwargs["event_code"], "HumanTrait")

    def test_selected_metadata_behavior_is_queued_as_anomaly_for_clip_capture(self):
        audio_job_callback = Mock()
        listener = dahua_client.DahuaNVRListener(audio_job_callback=audio_job_callback)
        with patch.object(dahua_client.config, "ACTIVE_CHANNELS", [1]), \
             patch.object(dahua_client.config, "ABNORMAL_EVENT_CODES", ["HumanTrait"]), \
             patch.object(dahua_client.database, "save_event", return_value=42) as save_event, \
             patch.object(dahua_client.database, "get_event_by_id", return_value=None), \
             patch.object(dahua_client.database, "create_audio_analysis") as create_audio_analysis:
            listener.process_event_block("Code=HumanTrait;action=Start;index=0")

        self.assertEqual(save_event.call_args.kwargs["event_type"], "video_anomaly")
        self.assertNotIn("clip_filename", save_event.call_args.kwargs)
        create_audio_analysis.assert_called_once_with(42, status="not_analyzed")
        audio_job_callback.assert_called_once_with(42)
