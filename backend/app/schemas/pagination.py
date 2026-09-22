from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


class PaginatedResponse(BaseModel, Generic[T]):
    """The one standard shape for every server-backed list endpoint
    (docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md's list-contract
    follow-up) -- `data` plus a `pagination` block, instead of each
    endpoint returning a bare array with the caller having no way to
    know how many records exist in total. Built with app/core/list_query.py's
    `paginate()`, never assembled by hand at a call site."""

    data: list[T]
    pagination: PaginationMeta
