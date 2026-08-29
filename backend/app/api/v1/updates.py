"""FR-800: Live Update Endpoints. Accept real-time data mutations and return
recalculated metrics immediately. Idempotent and validation-first design."""
import uuid
from datetime import date
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.tenancy import get_current_user, CurrentUser
from app.services.update_service import (
    update_task_progress,
    update_employee_workload,
    update_project_dates,
    reassign_task,
    batch_update_tasks,
    get_dashboard_snapshot,
)

router = APIRouter(prefix="/api/v1", tags=["updates"])


# ---- Schemas ----
class TaskProgressUpdate(BaseModel):
    task_id: str
    progress_percent: float | None = Field(None, ge=0, le=100)
    actual_hours: float | None = Field(None, ge=0)
    status: str | None = Field(None, pattern="^(todo|in_progress|blocked|done)$")


class BatchTaskUpdate(BaseModel):
    updates: list[TaskProgressUpdate] = Field(..., min_items=1, max_items=100)


class EmployeeCapacityUpdate(BaseModel):
    employee_id: str
    available_hours_per_week: int | None = Field(None, ge=0, le=60)
    is_active: bool | None = None


class ProjectTimelineUpdate(BaseModel):
    project_id: str
    start_date: date | None = None
    target_end_date: date | None = None
    status: str | None = Field(None, pattern="^(planned|active|at_risk|blocked|completed)$")


class TaskReassignRequest(BaseModel):
    task_id: str
    new_assignee_id: str


# ---- Endpoints ----

@router.post("/tasks/{task_id}/progress")
def update_task_progress_endpoint(
    task_id: str,
    progress_percent: float | None = Query(None, ge=0, le=100),
    actual_hours: float | None = Query(None, ge=0),
    status: str | None = Query(None, regex="^(todo|in_progress|blocked|done)$"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Update task progress and get recalculated project metrics immediately.
    
    This triggers:
    - Critical path recalculation
    - Risk re-evaluation
    - Project completion % update
    - Auto-complete project if all tasks done
    
    Example: POST /api/v1/tasks/{task_id}/progress?progress_percent=50&status=in_progress
    """
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task_id format")
    
    result = update_task_progress(
        db, current_user.tenant_id, task_uuid,
        progress_percent=progress_percent,
        actual_hours=actual_hours,
        status=status,
    )
    
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    
    return result


@router.post("/tasks/batch-update")
def batch_update_tasks_endpoint(
    body: BatchTaskUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Batch update multiple tasks and recalculate metrics once.
    
    Efficient for updating many tasks at once (e.g., daily stand-up data import).
    Max 100 updates per request.
    
    Example:
    POST /api/v1/tasks/batch-update
    {
      "updates": [
        {"task_id": "...", "progress_percent": 50, "status": "in_progress"},
        {"task_id": "...", "actual_hours": 16, "status": "done"},
      ]
    }
    """
    result = batch_update_tasks(db, current_user.tenant_id, [u.dict() for u in body.updates])
    return result


@router.post("/tasks/{task_id}/reassign")
def reassign_task_endpoint(
    task_id: str,
    new_assignee_id: str = Query(..., description="UUID of the new assignee"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Reassign a task to a different employee.
    
    Returns:
    - New assignee's workload status
    - Capacity warning if now overloaded
    - Recommendation to reduce other workload if needed
    """
    try:
        task_uuid = uuid.UUID(task_id)
        assignee_uuid = uuid.UUID(new_assignee_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")
    
    result = reassign_task(db, current_user.tenant_id, task_uuid, assignee_uuid)
    
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    
    return result


@router.put("/employees/{employee_id}/capacity")
def update_employee_capacity_endpoint(
    employee_id: str,
    available_hours_per_week: int | None = Query(None, ge=0, le=60),
    is_active: bool | None = Query(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Update employee availability and recalculate workload band.
    
    Use this when:
    - Employee takes leave or reduces hours
    - Employee returns from leave
    - Onboarding new team member with different capacity
    """
    try:
        emp_uuid = uuid.UUID(employee_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid employee_id format")
    
    result = update_employee_workload(
        db, current_user.tenant_id, emp_uuid,
        available_hours_per_week=available_hours_per_week,
        is_active=is_active,
    )
    
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    
    return result


@router.put("/projects/{project_id}/timeline")
def update_project_timeline_endpoint(
    project_id: str,
    start_date: date | None = Query(None),
    target_end_date: date | None = Query(None),
    status: str | None = Query(None, regex="^(planned|active|at_risk|blocked|completed)$"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Update project dates and status, get recalculated critical path and buffer.
    
    Triggers:
    - Critical path recalculation
    - Monte Carlo simulation (500 iterations)
    - Buffer analysis
    - Risk re-evaluation
    """
    try:
        proj_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project_id format")
    
    result = update_project_dates(
        db, current_user.tenant_id, proj_uuid,
        start_date=start_date,
        target_end_date=target_end_date,
        status=status,
    )
    
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    
    return result


@router.get("/dashboard/snapshot")
def get_dashboard_snapshot_endpoint(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get a real-time snapshot of entire org health.
    
    Returns:
    - Critical risks count
    - Project completion status
    - Workload distribution
    - Top 5 active risks
    - Overloaded/underutilized employees
    
    Hit this endpoint to refresh dashboard after batch updates or major changes.
    """
    snapshot = get_dashboard_snapshot(db, current_user.tenant_id)
    return snapshot
