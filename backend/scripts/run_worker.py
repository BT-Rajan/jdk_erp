"""Run the background-job worker (docs/modules/background_jobs.md #9).

Usage:
    python -m scripts.run_worker

Runs until interrupted (Ctrl-C / SIGTERM). No microservice, no separate
queue technology -- one process, polling the `jobs` table.
"""
import signal
import sys
import threading
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import app.jobs  # noqa: F401 -- registers every job handler
from app.services.job_worker import run_worker


def main() -> None:
    stop_event = threading.Event()

    def _handle_signal(signum, frame) -> None:  # noqa: ANN001
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    print("Worker started. Press Ctrl-C to stop.")
    run_worker(stop_event=stop_event)
    print("Worker stopped.")


if __name__ == "__main__":
    main()
