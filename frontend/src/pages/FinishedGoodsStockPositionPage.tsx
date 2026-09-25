import { useEffect, useState } from 'react'
import { Alert } from '@/components/ui/Alert'
import { Badge, type BadgeTone } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { DataTable, type DataTableColumn } from '@/components/ui/DataTable'
import { Drawer } from '@/components/ui/Drawer'
import { PageHeader } from '@/components/ui/PageHeader'
import { Spinner } from '@/components/ui/Spinner'
import { ApiError, apiClient } from '@/lib/apiClient'
import { formatDateTime, formatNumber } from '@/lib/format'

/** Mirrors backend/app/schemas/finished_goods_inventory.py's
 * FinishedGoodsStockPositionOut. */
interface StockPosition {
  product_id: number
  product_code: string
  product_name: string
  warehouse_id: number
  warehouse_name: string
  unit_of_measure_id: number
  unit_code: string
  quantity_on_hand: string
  status: 'in_stock' | 'out_of_stock'
}

/** Mirrors FinishedGoodsMovementOut. */
interface MovementEntry {
  id: number
  movement_type: string
  quantity: string
  unit_of_measure_id: number
  unit_code: string
  resulting_balance: string
  reference_type: string
  reference_id: number
  created_by_user_id: number | null
  created_by_name: string | null
  created_at: string
}

const MOVEMENT_TYPE_LABELS: Record<string, string> = {
  production_completion: 'Production Completion',
  delivery: 'Delivery',
  adjustment: 'Adjustment',
}

const MOVEMENT_TYPE_TONES: Record<string, BadgeTone> = {
  production_completion: 'success',
  delivery: 'warning',
  adjustment: 'info',
}

/** The current stock position of every manufactured Product, by
 * warehouse (backend/app/api/finished_goods_inventory.py's
 * list_stock_positions) -- a read-only report, the same "plain list,
 * fetch and render, no pagination" shape InventoryReconciliationPage
 * already established for a per-organisation Inventory listing of this
 * size. "View History" opens each row's own movement history in a
 * Drawer (rule 6) rather than navigating away -- this screen is
 * primarily for viewing and control, not direct quantity editing: there
 * is no inline-edit path on any cell here at all. Correcting a balance
 * is a separate, deliberate action on FinishedGoodsAdjustmentsPage. */
export function FinishedGoodsStockPositionPage() {
  const [positions, setPositions] = useState<StockPosition[] | null>(null)
  const [error, setError] = useState<string | undefined>(undefined)

  const [historyTarget, setHistoryTarget] = useState<StockPosition | null>(null)
  const [movements, setMovements] = useState<MovementEntry[] | null>(null)
  const [historyError, setHistoryError] = useState<string | undefined>(undefined)

  useEffect(() => {
    apiClient
      .get<StockPosition[]>('/api/finished-goods-inventory')
      .then(({ data }) => setPositions(data))
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Failed to load Finished Goods stock positions.'))
  }, [])

  function openHistory(position: StockPosition) {
    setHistoryTarget(position)
    setMovements(null)
    setHistoryError(undefined)
    apiClient
      .get<MovementEntry[]>('/api/finished-goods-inventory/movements', {
        params: { product_id: position.product_id, warehouse_id: position.warehouse_id },
      })
      .then(({ data }) => setMovements(data))
      .catch((err) => setHistoryError(err instanceof ApiError ? err.message : 'Failed to load movement history.'))
  }

  const columns: DataTableColumn<StockPosition>[] = [
    { key: 'product_code', label: 'Product Code', render: (p) => p.product_code },
    { key: 'product_name', label: 'Product', render: (p) => p.product_name },
    { key: 'warehouse_name', label: 'Warehouse', render: (p) => p.warehouse_name },
    { key: 'unit_code', label: 'Stock UOM', hideBelow: 'sm', render: (p) => p.unit_code },
    {
      key: 'quantity_on_hand',
      label: 'Quantity on Hand',
      align: 'right',
      render: (p) => formatNumber(p.quantity_on_hand),
    },
    {
      key: 'status',
      label: 'Status',
      render: (p) => (
        <Badge tone={p.status === 'in_stock' ? 'success' : 'neutral'}>
          {p.status === 'in_stock' ? 'In Stock' : 'Out of Stock'}
        </Badge>
      ),
    },
    {
      key: 'actions',
      label: '',
      alwaysVisible: true,
      align: 'right',
      render: (p) => (
        <Button variant="secondary" size="sm" onClick={() => openHistory(p)}>
          View History
        </Button>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Finished Goods Stock Position"
        subtitle="Current stock on hand for every manufactured Product, by warehouse."
      />
      <Alert variant="danger">{error}</Alert>

      <DataTable
        columns={columns}
        rows={positions ?? []}
        rowKey={(p) => `${p.product_id}-${p.warehouse_id}`}
        loading={positions === null}
        emptyTitle="No Finished Goods stock yet"
        emptyMessage="Stock appears here once a production completion, delivery or adjustment is recorded for a Product."
      />

      <Drawer
        open={historyTarget !== null}
        title={historyTarget ? `${historyTarget.product_name} @ ${historyTarget.warehouse_name}` : 'Movement History'}
        onClose={() => setHistoryTarget(null)}
      >
        <Alert variant="danger">{historyError}</Alert>
        {!historyError && movements === null && (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        )}
        {movements && movements.length === 0 && (
          <p className="text-sm text-gold-100/60">No movements recorded yet.</p>
        )}
        {movements && movements.length > 0 && (
          <ul className="space-y-3">
            {movements.map((m) => (
              <li key={m.id} className="rounded-md border border-ink-700 p-3 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <Badge tone={MOVEMENT_TYPE_TONES[m.movement_type] ?? 'neutral'}>
                    {MOVEMENT_TYPE_LABELS[m.movement_type] ?? m.movement_type}
                  </Badge>
                  <span className="text-xs text-gold-100/60">{formatDateTime(m.created_at)}</span>
                </div>
                <div className="mt-2 flex items-center justify-between">
                  <span className={Number(m.quantity) < 0 ? 'text-danger-500' : 'text-success-500'}>
                    {Number(m.quantity) >= 0 ? '+' : ''}
                    {formatNumber(m.quantity)} {m.unit_code}
                  </span>
                  <span className="text-gold-100/70">
                    Balance: {formatNumber(m.resulting_balance)} {m.unit_code}
                  </span>
                </div>
                <div className="mt-1 text-xs text-gold-100/50">
                  Ref: {m.reference_type} #{m.reference_id}
                  {m.created_by_name && ` · ${m.created_by_name}`}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Drawer>
    </div>
  )
}
