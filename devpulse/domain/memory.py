"""Retrieval values with explicit source provenance."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MemoryChunk:
    path: str
    kind: str
    start: int
    end: int
    text: str


@dataclass
class IndexReport:
    documents: int = 0
    chunks: int = 0
    skipped: list[str] = field(default_factory=list)
    fingerprint: str = ''
