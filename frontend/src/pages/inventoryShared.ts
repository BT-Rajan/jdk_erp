/** Types and small helpers shared by the Inventory module's pages --
 * Raw Material Inventory (InventoryAdjustmentsPage.tsx, Opening Stock,
 * Reconciliation) and Finished Goods Inventory (FinishedGoodsStockPositionPage.tsx,
 * FinishedGoodsAdjustmentsPage.tsx) alike, since both are the same
 * Inventory nav group/domain -- same role for Inventory that
 * rfqShared.ts plays for RFQ/Purchase Order. */

/** Mirrors backend/app/schemas/raw_material.py's RawMaterialOut, the
 * fields this module's forms need. */
export interface RawMaterialOption {
  id: number
  code: string
  name: string
  unit_of_measure_id: number
  is_active: boolean
}

/** Mirrors backend/app/schemas/product.py's ProductOut, the fields
 * Finished Goods Inventory's forms need. */
export interface ProductOption {
  id: number
  code: string
  name: string
  unit_of_measure_id: number
  is_active: boolean
}

/** Mirrors backend/app/schemas/warehouse.py's WarehouseOut, the fields
 * this module's forms need. */
export interface WarehouseOption {
  id: number
  code: string
  name: string
  is_active: boolean
}

export interface PaginatedResponse<T> {
  data: T[]
  pagination: { page: number; page_size: number; total: number; total_pages: number }
}

const DECIMAL_RE = /^\d+(\.\d+)?$/

export function isPositiveDecimal(value: string): boolean {
  return DECIMAL_RE.test(value) && Number(value) > 0
}

export function materialLabel(material: RawMaterialOption): string {
  return `${material.name} (${material.code})`
}

export function productLabel(product: ProductOption): string {
  return `${product.name} (${product.code})`
}

export function warehouseLabel(warehouse: WarehouseOption): string {
  return `${warehouse.name} (${warehouse.code})`
}
