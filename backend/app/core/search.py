"""The one mechanism every resource's list endpoint uses to add keyword
search (docs/modules/search.md) -- a predicate appended onto the SAME
already-authorized query a plain list already builds, never a separate
lookup path with its own scope. This is what makes "search must never
become a data-discovery backdoor" true by construction: there is no
code path that searches without whatever organisation/role/team/
ownership filters the caller already applied to `query` before this
runs, because this only ever narrows it further.
"""

from sqlalchemy import ColumnElement
from sqlalchemy.orm import Query
from sqlalchemy.sql import or_


def apply_keyword_filter(query: Query, keyword: str | None, *columns: ColumnElement) -> Query:
    """Case-insensitive substring match, OR'd across `columns`, appended
    to `query`. A blank/missing keyword is a no-op -- the plain,
    already-authorized list -- never "match everything." `%`/`_` (SQL
    LIKE's own wildcard characters) are escaped so a search for a
    literal `50%` matches only that text instead of acting as a
    pattern."""
    if not keyword or not keyword.strip():
        return query
    escaped = keyword.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    return query.filter(or_(*(column.ilike(pattern, escape="\\") for column in columns)))
