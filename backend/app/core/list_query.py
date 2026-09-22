"""The one shared mechanism every server-backed list endpoint uses for
pagination and sorting (docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md's
list-contract follow-up) -- a narrow primitive appended onto a query the
caller has already filtered/scoped/searched, the same "harden the
existing query, never build a second path" shape as
app/core/search.py's apply_keyword_filter. Not a generic query/filter
builder: it takes a page number and an already-validated sort key, not
an arbitrary expression.
"""

from math import ceil

from sqlalchemy import ColumnElement
from sqlalchemy.orm import Query

from app.core.errors import ValidationError
from app.schemas.pagination import PaginationMeta


def paginate(query: Query, page: int, page_size: int) -> tuple[list, PaginationMeta]:
    """Counts the filtered (and, if apply_sort was already called,
    sorted) query before paging it -- one COUNT query plus one SELECT,
    never "fetch every row just to measure how many there are." Sort
    order doesn't affect the count, so it's dropped for that query via
    `order_by(None)` (a new, unmutated copy of `query` -- SQLAlchemy's
    Query is immutable, so the caller's own `query` still carries its
    sort when used for the actual page below)."""
    total = query.order_by(None).count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    total_pages = ceil(total / page_size) if total else 0
    return rows, PaginationMeta(page=page, page_size=page_size, total=total, total_pages=total_pages)


def apply_sort(
    query: Query,
    sort_by: str | None,
    sort_direction: str,
    allowed: dict[str, ColumnElement],
    default: ColumnElement,
) -> Query:
    """`allowed` is a fixed, per-endpoint map of API-facing sort keys to
    real columns -- the one place a sort key ever becomes a column
    reference, so a client's `sort_by` string can never reach
    `order_by()` directly (never `order_by(text(sort_by))` or
    `getattr(Model, sort_by)`). An unrecognized key is a 422 naming the
    allowed set, not a silent fallback to `default` -- consistent with
    how every other invalid-input case in this codebase (an unknown
    role, an unsupported protocol, ...) is rejected explicitly rather
    than guessed around."""
    if sort_by is None:
        return query.order_by(default)
    column = allowed.get(sort_by)
    if column is None:
        message = f"Cannot sort by '{sort_by}'. Allowed fields: {', '.join(sorted(allowed))}."
        raise ValidationError(message, fields={"sort_by": message})
    return query.order_by(column.desc() if sort_direction == "desc" else column.asc())
