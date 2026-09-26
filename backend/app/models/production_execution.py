"""Production Execution (P6): what actually happened during production.

One ProductionExecution = one posted production event on an executable
Production Order: the actual quantity produced (in the order's production
unit), when, by whom -- plus one ProductionExecutionMaterial per raw
material consumed, computed from the order's frozen BOM snapshot. The
records explain the event; Inventory stays the authoritative ledger:
each material row is the reference of exactly one PRODUCTION_ISSUE stock
movement and the execution itself the reference of exactly one
PRODUCTION_COMPLETION Finished Goods movement (the ledgers' own
reference/movement-type uniqueness is the duplicate guard).

`client_reference` (unique per organisation) makes a retried request
return the already-posted execution instead of posting it twice.
Executions are never edited or deleted; the order's produced quantity is
always their sum (never stored separately)."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin

EXECUTION_POSTED = "posted"
# The Finished Goods movement reference for an execution's output.
PRODUCTION_EXECUTION_REFERENCE = "production_execution"


class ProductionExecution(Base, TimestampMixin, OrganisationScopedMixin):
    __tablename__ = "production_executions"
    __table_args__ = (
        UniqueConstraint("production_order_id", "sequence", name="uq_production_executions_order_sequence"),
        UniqueConstraint("organisation_id", "client_reference", name="uq_production_executions_org_client_reference"),
        CheckConstraint("produced_quantity > 0", name="produced_quantity_positive"),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    production_order_id: Mapped[int] = mapped_column(
        ForeignKey("production_orders.id", ondelete="RESTRICT", name="fk_production_executions_order_id"), nullable=False, index=True
    )
    # 1, 2, ... per Production Order -- the execution reference shown to users.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    produced_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_of_measure_id: Mapped[int] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT", name="fk_production_executions_unit_of_measure_id"), nullable=False
    )
    executed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=EXECUTION_POSTED)
    client_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recorded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_production_executions_recorded_by_user_id"), nullable=True
    )
    fg_movement_id: Mapped[int | None] = mapped_column(
        ForeignKey("finished_goods_movements.id", ondelete="RESTRICT", name="fk_production_executions_fg_movement_id"), nullable=True
    )

    materials: Mapped[list["ProductionExecutionMaterial"]] = relationship(
        cascade="all, delete-orphan", order_by="ProductionExecutionMaterial.id"
    )


class ProductionExecutionMaterial(Base):
    __tablename__ = "production_execution_materials"
    __table_args__ = (
        UniqueConstraint("production_execution_id", "raw_material_id", name="uq_production_execution_materials_exec_material"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    production_execution_id: Mapped[int] = mapped_column(
        ForeignKey("production_executions.id", ondelete="CASCADE", name="fk_production_execution_materials_execution_id"),
        nullable=False,
        index=True,
    )
    raw_material_id: Mapped[int] = mapped_column(
        ForeignKey("raw_materials.id", ondelete="RESTRICT", name="fk_production_execution_materials_raw_material_id"), nullable=False
    )
    # Consumed, in the raw material's own unit from the order's BOM snapshot.
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_of_measure_id: Mapped[int] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT", name="fk_production_execution_materials_unit_of_measure_id"), nullable=False
    )
    stock_movement_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_movements.id", ondelete="RESTRICT", name="fk_production_execution_materials_stock_movement_id"), nullable=True
    )
