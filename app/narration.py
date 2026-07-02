"""Background narration: synthesize story chunks concurrently and finalize."""

import asyncio
import logging

from app.gemini import GeminiClient, GeminiError, pcm_to_wav
from app.storage import StoryStore

logger = logging.getLogger(__name__)


async def narrate_story(
    gemini: GeminiClient,
    store: StoryStore,
    story_id: str,
    chunks: list[str],
    style_instruction: str,
    concurrency: int,
) -> None:
    """Synthesize all chunks of a story and assemble the final audio.

    Chunks are synthesized concurrently (bounded by ``concurrency``); each
    finished chunk is saved as a part file and the record's contiguous-ready
    counter is advanced so the frontend can start playback immediately. When
    every chunk is done, the PCM streams are concatenated into the full WAV
    and the story is marked ready. Any failure marks the story as error.

    Args:
        gemini: Client used for speech synthesis.
        store: Story cache to update as chunks complete.
        story_id: Identifier of the record created for this story.
        chunks: Story text chunks, in narration order.
        style_instruction: Reading-style instruction for each chunk.
        concurrency: Maximum number of simultaneous TTS calls.
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def synthesize(index: int, chunk: str) -> tuple[int, bytes, int]:
        async with semaphore:
            logger.info(
                "Story %s: synthesizing chunk %d/%d (%d chars)",
                story_id,
                index + 1,
                len(chunks),
                len(chunk),
            )
            pcm, sample_rate = await gemini.synthesize_chunk(chunk, style_instruction)
            return index, pcm, sample_rate

    tasks = [asyncio.create_task(synthesize(i, chunk)) for i, chunk in enumerate(chunks)]
    pcm_parts: dict[int, bytes] = {}
    rates: dict[int, int] = {}
    try:
        for future in asyncio.as_completed(tasks):
            index, pcm, sample_rate = await future
            pcm_parts[index] = pcm
            rates[index] = sample_rate
            store.save_part(story_id, index, pcm_to_wav(pcm, sample_rate))
            store.set_progress(story_id, _contiguous_ready(pcm_parts))
        if len(set(rates.values())) > 1:
            logger.error("Story %s: mixed sample rates %s, using the first", story_id, rates)
        full_pcm = b"".join(pcm_parts[i] for i in range(len(chunks)))
        store.finalize(story_id, pcm_to_wav(full_pcm, rates[0]))
        logger.info("Story %s: narration complete (%d chunks)", story_id, len(chunks))
    except (GeminiError, OSError) as exc:
        logger.error("Story %s: narration failed: %s", story_id, exc)
        store.mark_error(story_id)
    except asyncio.CancelledError:
        store.mark_error(story_id)
        raise
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _contiguous_ready(pcm_parts: dict[int, bytes]) -> int:
    """Count how many chunks are ready starting from index 0 with no gaps."""
    count = 0
    while count in pcm_parts:
        count += 1
    return count
