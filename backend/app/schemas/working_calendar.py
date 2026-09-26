from datetime import date, time

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HolidayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    holiday_date: date
    description: str


class WorkingCalendarOut(BaseModel):
    """The organisation's one working calendar. `working_days` and
    `timezone` are fixed business rules, returned for display only."""

    working_days: list[str]
    timezone: str
    same_day_cutoff_time: time
    holidays: list[HolidayOut]


class SameDayCutoffUpdateRequest(BaseModel):
    same_day_cutoff_time: time

    @field_validator("same_day_cutoff_time")
    @classmethod
    def _kuwait_wall_clock(cls, value: time) -> time:
        # The cut-off is always a Kuwait wall-clock time; an offset would
        # imply some other zone.
        if value.tzinfo is not None:
            raise ValueError("must be a plain time without a timezone offset, e.g. 14:00")
        return value.replace(microsecond=0)


class HolidayCreateRequest(BaseModel):
    holiday_date: date
    description: str = Field(min_length=1, max_length=120)

    @field_validator("description")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value
