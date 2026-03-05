"""Background extraction worker with queue-based progress reporting.

Runs file discovery and extraction in a daemon thread, posting
structured WorkerMessage objects to a queue that the main UI thread
polls via ``root.after()``.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

from bi_extractor.core.engine import discover_files, extract_file
from bi_extractor.core.models import ExtractionResult
from bi_extractor.core.registry import get_registry


class MessageType(Enum):
    """Types of messages the worker posts to the UI thread."""

    DISCOVERY_COMPLETE = auto()
    FILE_START = auto()
    FILE_COMPLETE = auto()
    ALL_COMPLETE = auto()
    ERROR = auto()


@dataclass(slots=True)
class WorkerMessage:
    """A progress message from the extraction worker to the UI."""

    msg_type: MessageType
    current: int = 0
    total: int = 0
    file_name: str = ""
    result: ExtractionResult | None = None
    error: str = ""


class ExtractionWorker:
    """Runs extraction in a background thread with progress reporting.

    Usage::

        q: queue.Queue[WorkerMessage] = queue.Queue()
        worker = ExtractionWorker(paths, recursive=True, message_queue=q)
        worker.start()
        # Poll q from the main thread via root.after()
    """

    def __init__(
        self,
        paths: list[Path],
        recursive: bool = True,
        message_queue: queue.Queue[WorkerMessage] | None = None,
        extensions: set[str] | None = None,
    ) -> None:
        self._paths = paths
        self._recursive = recursive
        self._queue: queue.Queue[WorkerMessage] = (
            message_queue if message_queue is not None else queue.Queue()
        )
        self._extensions = extensions
        self._cancel_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def queue(self) -> queue.Queue[WorkerMessage]:
        """The message queue for polling progress."""
        return self._queue

    def start(self) -> None:
        """Start extraction in a background daemon thread."""
        self._cancel_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def is_alive(self) -> bool:
        """Check if the worker thread is still running."""
        return self._thread is not None and self._thread.is_alive()

    def request_cancel(self) -> None:
        """Signal the worker to stop after the current file."""
        self._cancel_event.set()

    def _post(self, msg: WorkerMessage) -> None:
        """Post a message to the queue."""
        self._queue.put(msg)

    def _run(self) -> None:
        """Worker thread body — discovers files, extracts each, posts messages."""
        try:
            # Ensure registry is initialized on the worker thread
            registry = get_registry()

            # Phase 1: Discover files
            all_files: list[Path] = []
            for path in self._paths:
                if self._cancel_event.is_set():
                    break
                if path.is_file():
                    all_files.append(path)
                elif path.is_dir():
                    try:
                        discovered = discover_files(
                            path,
                            recursive=self._recursive,
                            extensions=self._extensions,
                        )
                        all_files.extend(discovered)
                    except PermissionError as e:
                        self._post(
                            WorkerMessage(
                                msg_type=MessageType.ERROR,
                                error=f"Permission denied: {e}",
                            )
                        )
                        return

            total = len(all_files)
            self._post(
                WorkerMessage(
                    msg_type=MessageType.DISCOVERY_COMPLETE,
                    total=total,
                )
            )

            if total == 0:
                self._post(WorkerMessage(msg_type=MessageType.ALL_COMPLETE))
                return

            # Phase 2: Extract each file
            for idx, file_path in enumerate(all_files, start=1):
                if self._cancel_event.is_set():
                    break

                self._post(
                    WorkerMessage(
                        msg_type=MessageType.FILE_START,
                        current=idx,
                        total=total,
                        file_name=file_path.name,
                    )
                )

                result = extract_file(file_path, registry)

                self._post(
                    WorkerMessage(
                        msg_type=MessageType.FILE_COMPLETE,
                        current=idx,
                        total=total,
                        file_name=file_path.name,
                        result=result,
                    )
                )

            self._post(WorkerMessage(msg_type=MessageType.ALL_COMPLETE))

        except Exception as e:
            self._post(
                WorkerMessage(
                    msg_type=MessageType.ERROR,
                    error=f"Unexpected error: {e}",
                )
            )
