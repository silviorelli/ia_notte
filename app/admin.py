"""Admin API: password-protected story list and deletion.

The password is read from ``ADMIN_PASSWORD`` (``.env``) and must be sent by
the client in the ``X-Admin-Password`` header on every request.
"""

import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app import config
from app.storage import STATUS_GENERATING, StoryStore

logger = logging.getLogger(__name__)


def require_admin(x_admin_password: Annotated[str | None, Header()] = None) -> None:
    """Reject the request unless it carries the correct admin password.

    Args:
        x_admin_password: Value of the ``X-Admin-Password`` request header.

    Raises:
        HTTPException: 503 if no admin password is configured on the server,
            401 if the header is missing or the password is wrong.
    """
    if not config.ADMIN_PASSWORD:
        logger.error("ADMIN_PASSWORD is not configured; admin API is disabled")
        raise HTTPException(status_code=503, detail="Area admin non configurata")
    if x_admin_password is None or not secrets.compare_digest(
        x_admin_password.encode(), config.ADMIN_PASSWORD.encode()
    ):
        raise HTTPException(status_code=401, detail="Password errata")


router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


@router.post("/login", status_code=204)
def login() -> None:
    """Verify the admin password; 204 means the password is correct."""


@router.get("/stories")
def list_all_stories(request: Request) -> list[dict]:
    """List every story, newest first, with creation date and requester IP."""
    store: StoryStore = request.app.state.store
    return store.list_all()


@router.delete("/stories/{story_id}", status_code=204)
def delete_story(story_id: str, request: Request) -> None:
    """Delete a story and its audio files.

    Raises:
        HTTPException: 404 if the story does not exist, 409 while its
            narration is still being generated (the background task would
            otherwise write orphan audio files).
    """
    store: StoryStore = request.app.state.store
    record = store.get(story_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Storia non trovata")
    if record["status"] == STATUS_GENERATING:
        raise HTTPException(
            status_code=409, detail="La voce è ancora in preparazione: riprova tra poco"
        )
    store.delete(story_id)
