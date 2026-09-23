import re
from dataclasses import dataclass


@dataclass(frozen=True)
class IdFormat:
    """One prefix+digit-count shape, shared by every entity that needs a
    human-readable reference id -- Quotation (QXXXXXX), Order (OXXXXXX),
    User (XXXXX), Product (PRXXXX), Material (MXXXX)
    (docs/modules/common_validation.md). Owns only the *shape*: which
    number comes next is the owning module's business (its own row
    count, a dedicated sequence, whatever fits that table) -- this never
    touches a database."""

    prefix: str
    digits: int

    @property
    def pattern(self) -> re.Pattern[str]:
        return re.compile(rf"^{re.escape(self.prefix)}\d{{{self.digits}}}$")

    @property
    def example(self) -> str:
        return f"{self.prefix}{'X' * self.digits}"

    def validate(self, value: str) -> str:
        if not self.pattern.match(value):
            raise ValueError(f"must match the format {self.example}")
        return value

    def format(self, sequence: int) -> str:
        maximum = 10**self.digits - 1
        if not (1 <= sequence <= maximum):
            raise ValueError(f"sequence must be between 1 and {maximum}")
        return f"{self.prefix}{sequence:0{self.digits}d}"


QUOTATION_ID = IdFormat(prefix="Q", digits=6)
ORDER_ID = IdFormat(prefix="O", digits=6)
USER_ID = IdFormat(prefix="", digits=5)
PRODUCT_ID = IdFormat(prefix="PR", digits=4)
MATERIAL_ID = IdFormat(prefix="M", digits=4)
CUSTOMER_ID = IdFormat(prefix="CUS", digits=5)
SUPPLIER_ID = IdFormat(prefix="SUP", digits=4)
