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


def audio_response(pcm: bytes, rate: int = 24000) -> httpx.Response:
    """Build a Gemini-style TTS response with inline PCM data."""
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "inlineData": {
                                    "mimeType": f"audio/L16;codec=pcm;rate={rate}",
                                    "data": base64.b64encode(pcm).decode("ascii"),
                                }
                            }
                        ]
                    }
                }
            ]
        },
    )
