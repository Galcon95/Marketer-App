"""The marketing agent's schedule (agents/automation.py), set in the app under Integrations → Automation.

    GET  /automation        the user's schedule, the next and the last run, whether the agent runs for the user
    PUT  /automation        save the user's schedule (manual, or every N minutes / at times of day)
    POST /automation/run    ask the agent for a run now, like /next in Telegram

Every user has their own schedule. The agent itself (agents/page_inbox_worker.py) runs once per server, for the owner
of the inbox books (FACEBOOK_INBOX_BOOKS); for any other user the schedule is saved but not used (`active` false).
"""

from fastapi import APIRouter, Depends, HTTPException

from app.agents import automation, page_inbox_worker
from app.core.auth import User, current_user
from app.core.schemas import AutomationSchedule, AutomationStatus

router = APIRouter()


@router.get("/automation", response_model=AutomationStatus)
def status(user: User = Depends(current_user)):
    """The user's schedule (the defaults when never saved), when it runs next and ran last, and whether the agent
    runs for this user (`note` says why not).

    Raises:
        HTTPException: 503 if the database cannot be read.
    """
    try:
        return automation.status(user.id)
    except OSError as e:  # DatabaseError
        raise HTTPException(503, "The schedule cannot be read right now, please try again.") from e


@router.put("/automation", response_model=AutomationStatus)
def save(schedule: AutomationSchedule, user: User = Depends(current_user)):
    """Save the user's schedule; the next run counts from now (saving never starts a run). 422 if it is invalid
    (unknown time zone, no time of day, interval under 15 minutes).

    Raises:
        HTTPException: 503 if the database cannot be written.
    """
    try:
        automation.save(user.id, schedule)
        return automation.status(user.id)
    except OSError as e:  # DatabaseError
        raise HTTPException(503, "The schedule could not be saved, please try again.") from e


@router.post("/automation/run", status_code=202)
def run_now(user: User = Depends(current_user)) -> dict[str, str]:
    """Ask the agent for a run now: it looks at the Page and the channel and proposes the next reply in Telegram.
    It starts within half a minute.

    Raises:
        HTTPException: 409 if the agent does not run on this server or works for another user.
    """
    if not page_inbox_worker.is_running():
        raise HTTPException(409, "The agent is not running on the server (Telegram and FACEBOOK_INBOX_BOOKS in "
                                 "server/.env).")
    if automation.inbox_owner() != user.id:
        raise HTTPException(409, "The agent on this server works for the owner of other books.")
    page_inbox_worker.request_run()
    return {"status": "Run requested: watch Telegram."}
