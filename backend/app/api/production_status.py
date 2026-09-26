"""Production Status (P7): the daily production view.

GET /api/production-status/day?date= -- the issued Production Orders
scheduled that day (default: today, Kuwait) in schedule sequence, with
planned / produced / remaining, status, required-by, source, production
line and exceptions; totals per production unit; the previous and next
working days for navigation. Read-only; `production:view` or `execute`.
Recording production is P6's Record Production endpoint."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.timezone import now_jdk
from app.models.user import User
from app.services import production_scope, production_status_service

router = APIRouter(prefix="/api/production-status", tags=["production-status"])


class OrderStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    production_order_id: int
    order_number: str
    sequence: int | None
    product_id: int
    product_name: str | None
    unit_of_measure_id: int
    planned_quantity: Decimal
    produced_quantity: Decimal
    remaining_quantity: Decimal
    status: str
    scheduled_date: date
    required_by_date: date | None
    production_line_name: str | None
    machine_name: str | None
    source_type: str
    sales_order_number: str | None
    sales_order_line_number: int | None
    production_plan_id: int
    exceptions: list[str]


class UnitTotalsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    unit_of_measure_id: int
    scheduled_quantity: Decimal
    produced_quantity: Decimal
    remaining_quantity: Decimal


class DayStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    is_working_day: bool
    previous_working_day: date
    next_working_day: date
    order_count: int
    completed_count: int
    in_progress_count: int
    not_started_count: int
    cancelled_count: int
    totals: list[UnitTotalsOut]
    orders: list[OrderStatusOut]


@router.get("/day", response_model=DayStatusOut)
def get_day_status(
    day: date | None = Query(None, alias="date"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DayStatusOut:
    production_scope.require_view_or_execute(db, current_user)
    status = production_status_service.day_status(db, current_user.organisation_id, day or now_jdk().date())
    return DayStatusOut.model_validate(status)
