"""Shared pytest fixtures."""

import base64

import httpx
import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Run anyio-marked tests on asyncio only."""
    return "asyncio"


def text_response(text: str) -> httpx.Response:
    """Build a Gemini-style text generation response."""
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


def audio_response(pcm: bytes, rate: int = 24000, mime_type: str | None = None) -> httpx.Response:
    """Build a Gemini-style TTS response with inline audio data.

    ``mime_type`` defaults to the bare-PCM type older TTS models return.
    """
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "inlineData": {
                                    "mimeType": mime_type or f"audio/L16;codec=pcm;rate={rate}",
                                    "data": base64.b64encode(pcm).decode("ascii"),
                                }
                            }
                        ]
                    }
                }
            ]
        },
    )
