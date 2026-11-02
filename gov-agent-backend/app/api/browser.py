import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.database import get_db
from app.auth_utils import get_current_user
from app.models.user import User
from app.services.browser_session_manager import (
    browser_session_manager,
    BrowserSessionError,
)

logger = logging.getLogger("browser.api")

router = APIRouter(
    prefix="/api/browser",
    tags=["Browser Agent"],
)


class BrowserSessionRequest(BaseModel):
    manifest: dict = Field(
        description="Validated execution manifest"
    )


class ActionExecuteRequest(BaseModel):
    action: Optional[str] = Field(
        default=None,
        description="Action type, e.g. click, fill, navigate, or stop",
    )
    target: Optional[str] = Field(
        default=None,
        description="Target element text, field_ref, or selector",
    )
    parameters: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Optional parameters such as value references",
    )


def handle_browser_error(error):
    message = str(error)

    if "not found" in message.lower():
        raise HTTPException(status_code=404, detail=message)

    if "access denied" in message.lower():
        raise HTTPException(status_code=403, detail=message)

    raise HTTPException(status_code=400, detail=message)


@router.post("/sessions")
async def create_browser_session(
    request: BrowserSessionRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        # Call directly or via run_in_threadpool without passing an active loop
        result = await run_in_threadpool(
            browser_session_manager.create_session,
            current_user.id,
            request.manifest,
        )
        return result
    except BrowserSessionError as error:
        logger.error("BROWSER SESSION REJECTED: %s", error)
        handle_browser_error(error)


@router.get("/sessions/{session_id}/observe")
async def observe_browser_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    try:
        return await run_in_threadpool(
            browser_session_manager.observe,
            session_id,
            current_user.id,
        )

    except BrowserSessionError as error:
        handle_browser_error(error)


@router.get("/sessions/{session_id}/task")
async def get_browser_task(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    try:
        task = await run_in_threadpool(
            browser_session_manager.get_session_task,
            session_id,
            current_user.id,
        )

        return {
            "status": "success",
            "task": task,
        }

    except BrowserSessionError as error:
        handle_browser_error(error)


@router.post("/sessions/{session_id}/analyze")
async def analyze_browser_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    try:
        return await run_in_threadpool(
            browser_session_manager.analyze_session,
            session_id,
            current_user.id,
        )

    except BrowserSessionError as error:
        handle_browser_error(error)

    except Exception:
        logger.exception("Browser session Gemini analysis failed")
        raise HTTPException(
            status_code=502,
            detail="Gemini analysis failed"
        )


@router.post("/sessions/{session_id}/execute")
async def execute_browser_action(
    session_id: str,
    request: Optional[ActionExecuteRequest] = None,
    current_user: User = Depends(get_current_user),
):
    """
    Approve and execute a proposed browser action (e.g. clicking 'Fill Form 6').
    Can accept the proposal body directly or an empty body to approve staged actions.
    """
    try:
        action_dict = (
            request.model_dump(exclude_unset=True)
            if request and request.action
            else None
        )

        result = await run_in_threadpool(
            browser_session_manager.execute_session_action,
            session_id,
            current_user.id,
            action_dict,
        )
        return result

    except BrowserSessionError as error:
        logger.error("BROWSER ACTION EXECUTION REJECTED: %s", error)
        handle_browser_error(error)


@router.delete("/sessions/{session_id}")
async def close_browser_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    try:
        return await run_in_threadpool(
            browser_session_manager.close_session,
            session_id,
            current_user.id,
        )

    except BrowserSessionError as error:
        handle_browser_error(error)