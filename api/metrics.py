from fastapi import APIRouter, Query, Depends, HTTPException, status
from utils.metrics import calculate_metrics, read_metrics_records
from auth.dependencies import get_current_user
from database.models_db import User

router = APIRouter(prefix="/metrics", tags=["Metrics"])


def check_admin_user(current_user: User = Depends(get_current_user)):
    """
    Dependency to verify if the current user has administrator privileges.
    """
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Administrator privileges required."
        )
    return current_user


@router.get("/summary", dependencies=[Depends(check_admin_user)])
def get_metrics_summary():
    """
    Returns aggregated metrics computed over sliding windows
    (1 min, 5 min, 1 hour, 24 hours, and all-time).
    """
    return calculate_metrics()


@router.get("/raw", dependencies=[Depends(check_admin_user)])
def get_raw_metrics(limit: int = Query(default=100, ge=1, le=1000)):
    """
    Returns the latest raw metric records, up to the limit.
    """
    records = read_metrics_records()
    # Return the most recent records first
    return records[-limit:][::-1]
