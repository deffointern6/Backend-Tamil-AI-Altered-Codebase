from fastapi import APIRouter, Query
from utils.metrics import calculate_metrics, read_metrics_records

router = APIRouter(prefix="/metrics", tags=["Metrics"])

@router.get("/summary")
def get_metrics_summary():
    """
    Returns aggregated metrics computed over sliding windows
    (1 min, 5 min, 1 hour, 24 hours, and all-time).
    """
    return calculate_metrics()


@router.get("/raw")
def get_raw_metrics(limit: int = Query(default=100, ge=1, le=1000)):
    """
    Returns the latest raw metric records, up to the limit.
    """
    records = read_metrics_records()
    # Return the most recent records first
    return records[-limit:][::-1]
