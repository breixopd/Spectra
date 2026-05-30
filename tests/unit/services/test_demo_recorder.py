"""Tests for the DemoRecorder service."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra_mission.demo_recorder import DemoRecorder


@pytest.fixture
def recorder():
    return DemoRecorder(mission_id="test-mission-001", target="192.168.1.1")


class TestDemoRecorderLifecycle:
    def test_initial_state(self, recorder):
        assert not recorder.is_recording
        assert recorder.event_count == 0
        assert recorder.duration == 0

    def test_start_recording(self, recorder):
        recorder.start()
        assert recorder.is_recording
        assert recorder.event_count > 0  # start() adds header events

    def test_stop_recording(self, recorder):
        recorder.start()
        recorder.stop()
        assert not recorder.is_recording

    def test_duration_while_recording(self, recorder):
        recorder.start()
        assert recorder.duration > 0

    def test_duration_zero_when_stopped(self, recorder):
        recorder.start()
        recorder.stop()
        assert recorder.duration == 0


class TestEventRecording:
    def test_add_output_while_recording(self, recorder):
        recorder.start()
        initial = recorder.event_count
        recorder.add_output("test output")
        assert recorder.event_count == initial + 1

    def test_add_output_ignored_when_stopped(self, recorder):
        recorder.start()
        recorder.stop()
        count_after_stop = recorder.event_count
        recorder.add_output("should be ignored")
        assert recorder.event_count == count_after_stop

    def test_record_tool_start(self, recorder):
        recorder.start()
        initial = recorder.event_count
        recorder.record_tool_start("nmap", "192.168.1.1", {"ports": "1-1000"})
        assert recorder.event_count > initial

    def test_record_tool_output(self, recorder):
        recorder.start()
        initial = recorder.event_count
        recorder.record_tool_output("PORT   STATE SERVICE")
        assert recorder.event_count > initial

    def test_record_tool_result_success(self, recorder):
        recorder.start()
        initial = recorder.event_count
        recorder.record_tool_result("nmap", success=True, findings=5)
        assert recorder.event_count > initial

    def test_record_tool_result_failure(self, recorder):
        recorder.start()
        recorder.record_tool_result("nmap", success=False, findings=0)
        last_event = recorder.events[-1]
        assert "Failed" in last_event[2]

    def test_record_finding(self, recorder):
        recorder.start()
        recorder.record_finding("critical", "SQL Injection in login form")
        last_event = recorder.events[-1]
        assert "CRITICAL" in last_event[2]
        assert "SQL Injection" in last_event[2]

    def test_record_finding_severity_colors(self, recorder):
        recorder.start()
        for sev in ["critical", "high", "medium", "low", "info"]:
            recorder.record_finding(sev, f"Test {sev}")
        assert recorder.event_count > 5

    def test_events_are_tuples(self, recorder):
        recorder.start()
        recorder.record_tool_output("test")
        for ev in recorder.events:
            assert len(ev) == 3
            assert isinstance(ev[0], float)
            assert ev[1] == "o"
            assert isinstance(ev[2], str)


class TestSaveRecording:
    @pytest.mark.asyncio
    async def test_save_creates_cast_file(self, recorder):
        recorder.start()
        recorder.record_tool_output("test output")
        recorder.stop()

        mock_storage = MagicMock()
        mock_storage.upload = AsyncMock(return_value="s3://spectra-missions/test-mission-001/demo.cast")
        with patch("spectra_mission.demo_recorder.get_storage_service", return_value=mock_storage):
            result = await recorder.save()
            assert result is not None
            mock_storage.upload.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_empty_recording_returns_none(self):
        rec = DemoRecorder("m1", "t1")
        assert await rec.save() is None

    @pytest.mark.asyncio
    async def test_save_writes_asciinema_v2_format(self, recorder):
        recorder.start()
        recorder.record_tool_output("hello")
        recorder.stop()

        captured_data = {}

        async def capture_upload(bucket, key, data):
            captured_data["content"] = data.decode()
            return f"s3://{bucket}/{key}"

        mock_storage = MagicMock()
        mock_storage.upload = AsyncMock(side_effect=capture_upload)
        with patch("spectra_mission.demo_recorder.get_storage_service", return_value=mock_storage):
            await recorder.save()

        content = captured_data["content"]
        lines = content.strip().split("\n")
        parsed_header = json.loads(lines[0])
        assert parsed_header["version"] == 2
        assert parsed_header["width"] == 120

    def test_event_count_property(self, recorder):
        assert recorder.event_count == 0
        recorder.start()
        assert recorder.event_count > 0
