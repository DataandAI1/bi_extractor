"""Tests for the GUI extraction worker (headless, no tkinter required)."""

from __future__ import annotations

import queue
from pathlib import Path

import pytest

from bi_extractor.gui.worker import ExtractionWorker, MessageType, WorkerMessage


FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestWorkerMessageSequence:
    """Verify the worker posts messages in the correct order."""

    def test_single_file_extraction(self) -> None:
        """Worker processes a single file and posts correct message sequence."""
        fixture = FIXTURES_DIR / "tableau" / "sample.twb"
        if not fixture.exists():
            pytest.skip("Fixture file not found")

        q: queue.Queue[WorkerMessage] = queue.Queue()
        worker = ExtractionWorker(
            paths=[fixture], recursive=False, message_queue=q
        )
        worker.start()

        # Wait for completion
        messages: list[WorkerMessage] = []
        while True:
            try:
                msg = q.get(timeout=10)
                messages.append(msg)
                if msg.msg_type in (MessageType.ALL_COMPLETE, MessageType.ERROR):
                    break
            except queue.Empty:
                pytest.fail("Worker timed out")

        # Verify message sequence
        msg_types = [m.msg_type for m in messages]
        assert msg_types[0] == MessageType.DISCOVERY_COMPLETE
        assert msg_types[-1] == MessageType.ALL_COMPLETE

        # Should have FILE_START and FILE_COMPLETE for the single file
        assert MessageType.FILE_START in msg_types
        assert MessageType.FILE_COMPLETE in msg_types

    def test_directory_extraction(self) -> None:
        """Worker discovers and processes files in a directory."""
        q: queue.Queue[WorkerMessage] = queue.Queue()
        worker = ExtractionWorker(
            paths=[FIXTURES_DIR], recursive=True, message_queue=q
        )
        worker.start()

        messages: list[WorkerMessage] = []
        while True:
            try:
                msg = q.get(timeout=15)
                messages.append(msg)
                if msg.msg_type in (MessageType.ALL_COMPLETE, MessageType.ERROR):
                    break
            except queue.Empty:
                pytest.fail("Worker timed out")

        # First message should be DISCOVERY_COMPLETE
        assert messages[0].msg_type == MessageType.DISCOVERY_COMPLETE
        total = messages[0].total
        assert total > 0

        # Count FILE_COMPLETE messages
        file_completes = [
            m for m in messages if m.msg_type == MessageType.FILE_COMPLETE
        ]
        assert len(file_completes) == total

        # Each FILE_COMPLETE should have a result
        for msg in file_completes:
            assert msg.result is not None

        # Last message should be ALL_COMPLETE
        assert messages[-1].msg_type == MessageType.ALL_COMPLETE

    def test_file_start_before_complete(self) -> None:
        """FILE_START always precedes its matching FILE_COMPLETE."""
        fixture = FIXTURES_DIR / "tableau" / "sample.twb"
        if not fixture.exists():
            pytest.skip("Fixture file not found")

        q: queue.Queue[WorkerMessage] = queue.Queue()
        worker = ExtractionWorker(
            paths=[fixture], recursive=False, message_queue=q
        )
        worker.start()

        messages: list[WorkerMessage] = []
        while True:
            try:
                msg = q.get(timeout=10)
                messages.append(msg)
                if msg.msg_type in (MessageType.ALL_COMPLETE, MessageType.ERROR):
                    break
            except queue.Empty:
                pytest.fail("Worker timed out")

        # Find pairs
        starts = [
            i for i, m in enumerate(messages)
            if m.msg_type == MessageType.FILE_START
        ]
        completes = [
            i for i, m in enumerate(messages)
            if m.msg_type == MessageType.FILE_COMPLETE
        ]

        assert len(starts) == len(completes)
        for s, c in zip(starts, completes):
            assert s < c


class TestWorkerEmptyInput:
    """Verify worker handles empty/missing input gracefully."""

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Worker posts DISCOVERY_COMPLETE with total=0 for empty directory."""
        q: queue.Queue[WorkerMessage] = queue.Queue()
        worker = ExtractionWorker(
            paths=[tmp_path], recursive=True, message_queue=q
        )
        worker.start()

        messages: list[WorkerMessage] = []
        while True:
            try:
                msg = q.get(timeout=5)
                messages.append(msg)
                if msg.msg_type in (MessageType.ALL_COMPLETE, MessageType.ERROR):
                    break
            except queue.Empty:
                pytest.fail("Worker timed out")

        assert messages[0].msg_type == MessageType.DISCOVERY_COMPLETE
        assert messages[0].total == 0
        assert messages[-1].msg_type == MessageType.ALL_COMPLETE

    def test_nonexistent_file(self) -> None:
        """Worker handles non-existent file path without crashing."""
        fake_path = Path("/nonexistent/file.twb")
        q: queue.Queue[WorkerMessage] = queue.Queue()
        worker = ExtractionWorker(
            paths=[fake_path], recursive=False, message_queue=q
        )
        worker.start()

        messages: list[WorkerMessage] = []
        while True:
            try:
                msg = q.get(timeout=5)
                messages.append(msg)
                if msg.msg_type in (MessageType.ALL_COMPLETE, MessageType.ERROR):
                    break
            except queue.Empty:
                pytest.fail("Worker timed out")

        # Non-existent file is added directly, then extract_file handles it
        assert messages[-1].msg_type == MessageType.ALL_COMPLETE


class TestWorkerCancel:
    """Verify cancel behavior."""

    def test_cancel_stops_extraction(self) -> None:
        """Cancelling the worker stops processing after the current file."""
        q: queue.Queue[WorkerMessage] = queue.Queue()
        worker = ExtractionWorker(
            paths=[FIXTURES_DIR], recursive=True, message_queue=q
        )
        worker.start()

        # Wait for discovery, then cancel
        msg = q.get(timeout=10)
        assert msg.msg_type == MessageType.DISCOVERY_COMPLETE

        # Cancel immediately
        worker.request_cancel()

        messages: list[WorkerMessage] = [msg]
        while True:
            try:
                msg = q.get(timeout=5)
                messages.append(msg)
                if msg.msg_type in (MessageType.ALL_COMPLETE, MessageType.ERROR):
                    break
            except queue.Empty:
                pytest.fail("Worker timed out after cancel")

        # Should end with ALL_COMPLETE
        assert messages[-1].msg_type == MessageType.ALL_COMPLETE

        # May have fewer FILE_COMPLETE messages than total
        total = messages[0].total
        file_completes = [
            m for m in messages if m.msg_type == MessageType.FILE_COMPLETE
        ]
        assert len(file_completes) <= total


class TestWorkerIsAlive:
    """Verify the is_alive check."""

    def test_alive_during_processing(self) -> None:
        """Worker reports alive while processing."""
        q: queue.Queue[WorkerMessage] = queue.Queue()
        worker = ExtractionWorker(
            paths=[FIXTURES_DIR], recursive=True, message_queue=q
        )
        assert not worker.is_alive()
        worker.start()
        assert worker.is_alive()

        # Drain to completion
        while True:
            try:
                msg = q.get(timeout=10)
                if msg.msg_type in (MessageType.ALL_COMPLETE, MessageType.ERROR):
                    break
            except queue.Empty:
                break

        # Give thread time to finish
        import time
        time.sleep(0.2)
        assert not worker.is_alive()
