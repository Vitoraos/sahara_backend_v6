from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BenchmarkSample:
    audio_path: Path
    reference_transcript: str
    language_pair: str
    reference_fields: dict[str, Any]


def load_manifest(manifest_path: Path) -> Iterator[BenchmarkSample]:
    """Reads a JSONL manifest, one sample per line:
    {"audio_path": "...", "reference_transcript": "...",
     "language_pair": "yo-en", "reference_fields": {...}}

    This project does not bundle the AfriswitchCare dataset itself — build
    a manifest from it (see the Intron-MultimodalBenchmarking repo linked
    in the challenge onboarding) and point this at that file.
    """
    with manifest_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            yield BenchmarkSample(
                audio_path=Path(row["audio_path"]),
                reference_transcript=row["reference_transcript"],
                language_pair=row.get("language_pair", "unknown"),
                reference_fields=row.get("reference_fields", {}),
            )
