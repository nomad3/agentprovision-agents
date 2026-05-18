import logging
import os
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api import deps
from app.models.user import User
from app.services import media_utils
from app.services.transcription_client import (
    TranscriptionUnavailable,
    transcribe_async,
    transcription_status,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# Sync-wait window for the user-facing endpoint. Keep modest so we never
# tie up the request budget on long clips — clients are expected to fall
# back to polling ``GET /media/transcription/{job_id}`` if we return
# ``status=pending``.
_SYNC_WINDOW_SECONDS = 10.0


@router.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Transcribe an uploaded audio file via the code-worker whisper workflow.

    The file is streamed to a disk-backed temp file (so we never hold the
    whole payload in RAM), then handed off to the
    ``TranscribeAudioWorkflow`` running on the ``agentprovision-code``
    Temporal queue (see ``apps/code-worker/transcription.py``).

    We wait up to ``_SYNC_WINDOW_SECONDS`` for the result so short clips
    return inline like the pre-migration endpoint did. Longer clips
    return a 202 with ``{"status": "pending", "job_id": ...}`` — clients
    poll ``GET /media/transcription/{job_id}`` for the final transcript.
    """
    if not file.content_type.startswith("audio/") and file.content_type not in media_utils.AUDIO_MIMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported media type: {file.content_type}. Must be audio.",
        )

    tmp_path: str | None = None
    audio_bytes: bytes
    try:
        # delete=False so we control cleanup; the workflow takes ownership
        # of a copy on the shared volume.
        with tempfile.NamedTemporaryFile(delete=False, suffix=".audio") as tmp:
            tmp_path = tmp.name
            size = 0
            while chunk := await file.read(1024 * 1024):  # 1 MB chunks
                size += len(chunk)
                if size > media_utils.MAX_AUDIO_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Audio file too large. Max size is {media_utils.MAX_AUDIO_SIZE // (1024 * 1024)}MB.",
                    )
                tmp.write(chunk)

        with open(tmp_path, "rb") as fh:
            audio_bytes = fh.read()

        try:
            result = await transcribe_async(
                audio_bytes, sync_timeout=_SYNC_WINDOW_SECONDS
            )
        except TranscriptionUnavailable as exc:
            logger.warning("Transcription service unavailable: %s", exc)
            return {
                "transcript": None,
                "engine": "unavailable",
                "reason": "transcription_service_unavailable",
                "duration_ms": 0,
            }

        if result.status == "pending":
            # 202 + job_id; web client should poll the status endpoint.
            return {
                "status": "pending",
                "job_id": result.job_id,
                "transcript": None,
                "engine": "pending",
                "duration_ms": 0,
                "poll_url": f"/api/v1/media/transcription/{result.job_id}",
            }

        return {
            "transcript": result.transcript,
            "engine": result.engine,
            "duration_ms": result.duration_ms,
            "job_id": result.job_id,
            "status": "completed",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Transcription endpoint failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                logger.debug("Temp file cleanup skipped", exc_info=True)


@router.get("/transcription/{job_id}")
async def get_transcription_status(
    job_id: str,
    current_user: User = Depends(deps.get_current_active_user),
):
    """Poll an in-flight transcription job.

    Returns the same shape as ``POST /transcribe`` once the workflow
    finishes (``status=completed``). While running, returns
    ``status=pending`` and the client should retry after a short delay.
    """
    try:
        result = await transcription_status(job_id)
    except TranscriptionUnavailable as exc:
        logger.warning("Transcription status check failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transcription service unavailable",
        )
    except Exception as e:
        logger.exception("Transcription status check failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

    return {
        "status": result.status,
        "job_id": result.job_id,
        "transcript": result.transcript,
        "engine": result.engine,
        "duration_ms": result.duration_ms,
    }
