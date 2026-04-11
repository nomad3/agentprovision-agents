"""Thread-safe validation metrics for Phase 2 dual-read/dual-write cutover.

Tracks agreement rates between Python and Rust paths so operators can
monitor convergence before flipping USE_RUST_MEMORY=true.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ValidationMetrics:
    total_reads: int = 0
    matching_reads: int = 0
    divergent_reads: int = 0
    total_writes: int = 0
    successful_rust_writes: int = 0
    failed_rust_writes: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        repr=False,
    )

    def record_read(self, matched: bool) -> None:
        with self._lock:
            self.total_reads += 1
            if matched:
                self.matching_reads += 1
            else:
                self.divergent_reads += 1

    def record_write(self, success: bool) -> None:
        with self._lock:
            self.total_writes += 1
            if success:
                self.successful_rust_writes += 1
            else:
                self.failed_rust_writes += 1

    def report(self) -> dict:
        with self._lock:
            read_match_rate = (
                self.matching_reads / self.total_reads
                if self.total_reads > 0
                else None
            )
            write_success_rate = (
                self.successful_rust_writes / self.total_writes
                if self.total_writes > 0
                else None
            )
            return {
                "started_at": self._started_at,
                "reads": {
                    "total": self.total_reads,
                    "matching": self.matching_reads,
                    "divergent": self.divergent_reads,
                    "match_rate": read_match_rate,
                },
                "writes": {
                    "total": self.total_writes,
                    "successful": self.successful_rust_writes,
                    "failed": self.failed_rust_writes,
                    "success_rate": write_success_rate,
                },
            }


# Module-level singleton — shared across recall.py and record.py
metrics = ValidationMetrics()
