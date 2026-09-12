from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from app.benchmark.dataset import load_manifest
from app.benchmark.metrics import clinical_entity_accuracy, word_error_rate
from app.benchmark.providers import STTBenchmarkProvider
from app.config import Settings, get_settings
from app.dialogue.field_schema import RequiredFieldPolicy
from app.dialogue.llm_provider import OpenRouterClient, OpenRouterExtractionProvider

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkResult:
    model_name: str
    language_pair: str
    wer: float
    entity_accuracy: float


async def run_benchmark(
    manifest_path: Path,
    providers: list[STTBenchmarkProvider],
    settings: Settings,
    output_path: Path,
) -> list[BenchmarkResult]:
    """Runs each STT provider over every sample in the manifest, scoring
    WER against the reference transcript and (where reference_fields are
    given) clinical entity accuracy via the same OpenRouter extraction path
    used in the live pipeline — so the benchmark measures what the real
    system would actually recover, not transcription quality alone.
    """
    policy = RequiredFieldPolicy(
        fields=tuple(x.strip() for x in settings.required_triage_fields.split(",") if x.strip())
    )
    extractor = OpenRouterExtractionProvider(
        OpenRouterClient(settings, model=settings.openrouter_extraction_model), policy.fields
    )

    results: list[BenchmarkResult] = []
    for provider in providers:
        for sample in load_manifest(manifest_path):
            try:
                hypothesis = await provider.transcribe_file(sample.audio_path)
            except NotImplementedError:
                logger.warning("skipping %s — provider not yet implemented", provider.name)
                break
            wer = word_error_rate(sample.reference_transcript, hypothesis)
            entity_accuracy = 1.0
            if sample.reference_fields:
                extracted = await extractor.extract(hypothesis)
                entity_accuracy = clinical_entity_accuracy(sample.reference_fields, extracted.fields)
            results.append(
                BenchmarkResult(
                    model_name=provider.name,
                    language_pair=sample.language_pair,
                    wer=wer,
                    entity_accuracy=entity_accuracy,
                )
            )

    output_path.write_text(json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8")
    logger.info("wrote %d benchmark results to %s", len(results), output_path)
    return results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the 3-model ASR benchmark")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("benchmark_report.json"))
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    loaded_settings = get_settings()
    # Add providers here once each STT endpoint is confirmed against real
    # docs — see app/benchmark/providers.py for what's confirmed so far.
    configured_providers: list[STTBenchmarkProvider] = [
        # SaharaFileUploadSTTProvider(loaded_settings),  # uncomment once confirmed
    ]
    if not configured_providers:
        raise SystemExit(
            "No STT providers configured yet — see app/benchmark/providers.py. "
            "The challenge requires benchmarking 3+ models including a Sahara "
            "API; add each provider here once its file-upload endpoint is "
            "confirmed against real documentation."
        )
    asyncio.run(run_benchmark(args.manifest, configured_providers, loaded_settings, args.output))
