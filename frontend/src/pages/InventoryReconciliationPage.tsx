import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { DataTable, type DataTableColumn } from '@/components/ui/DataTable'
import { EmptyState } from '@/components/ui/EmptyState'
import { PageHeader } from '@/components/ui/PageHeader'
import { ApiError, apiClient } from '@/lib/apiClient'
import { formatNumber } from '@/lib/format'

/** Mirrors backend/app/schemas/inventory.py's BalanceReconciliationOut. */
interface ReconciliationPair {
  raw_material_id: number
  material_name: string
  warehouse_id: number
  warehouse_name: string
  ledger_sum: string
  quantity_on_hand: string
  difference: string
  matches: boolean
}

/** Mirrors ReconciliationReportOut. */
interface ReconciliationReport {
  pairs_checked: number
  mismatches_found: number
  pairs: ReconciliationPair[]
}

/** Ledger/balance reconciliation report (backend/app/api/inventory.py's
 * get_reconciliation_report) -- every (raw material, warehouse) pair
 * this organisation has a stock snapshot for, compared against what its
 * own StockMovement ledger sums to. Read-only, one GET on mount, no
 * filters or pagination (the backend itself returns the whole org's
 * report in one response) -- same "plain list, fetch and render" shape
 * as DashboardPage's own action-items list. A mismatch here is
 * something for a human to investigate and correct with a Controlled
 * Stock Adjustment; this page never fixes one itself. */
export function InventoryReconciliationPage() {
  const navigate = useNavigate()
  const [report, setReport] = useState<ReconciliationReport | null>(null)
  const [error, setError] = useState<string | undefined>(undefined)

  const openAdjustment = (pair: ReconciliationPair) =>
    navigate('/inventory/adjustments', { state: { rawMaterialId: pair.raw_material_id, warehouseId: pair.warehouse_id } })

  useEffect(() => {
    apiClient
      .get<ReconciliationReport>('/api/inventory/reconciliation')
      .then(({ data }) => setReport(data))
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Failed to load the reconciliation report.'))
  }, [])

  const columns: DataTableColumn<ReconciliationPair>[] = [
    { key: 'material', label: 'Raw Material', render: (pair) => pair.material_name },
    { key: 'warehouse', label: 'Warehouse', render: (pair) => pair.warehouse_name },
    { key: 'ledger_sum', label: 'Ledger Sum', align: 'right', render: (pair) => formatNumber(pair.ledger_sum) },
    { key: 'quantity_on_hand', label: 'Quantity on Hand', align: 'right', render: (pair) => formatNumber(pair.quantity_on_hand) },
    { key: 'difference', label: 'Difference', align: 'right', hideBelow: 'sm', render: (pair) => formatNumber(pair.difference) },
    {
      key: 'matches',
      label: 'Status',
      alwaysVisible: true,
      render: (pair) => (
        <Badge tone={pair.matches ? 'success' : 'danger'}>{pair.matches ? 'Matches' : 'Mismatch'}</Badge>
      ),
    },
    {
      key: 'actions',
      label: '',
      alwaysVisible: true,
      align: 'right' as const,
      render: (pair) =>
        pair.matches ? null : (
          <Button variant="secondary" size="sm" onClick={() => openAdjustment(pair)}>
            Record Adjustment
          </Button>
        ),
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Stock Reconciliation"
        subtitle="Every raw material/warehouse pair's ledger total compared against its stored balance. A mismatch here is never corrected automatically -- investigate and record a Stock Adjustment."
      />
      <Alert variant="danger">{error}</Alert>

      {report && (
        <Alert variant={report.mismatches_found > 0 ? 'warning' : 'success'}>
          {report.pairs_checked} pair{report.pairs_checked === 1 ? '' : 's'} checked, {report.mismatches_found} mismatch
          {report.mismatches_found === 1 ? '' : 'es'} found.
        </Alert>
      )}

      {report && report.pairs.length === 0 ? (
        <EmptyState title="Nothing to reconcile" message="No raw material has a recorded stock snapshot yet." />
      ) : (
        <DataTable
          columns={columns}
          rows={report?.pairs ?? []}
          rowKey={(pair) => `${pair.raw_material_id}-${pair.warehouse_id}`}
          loading={report === null}
        />
      )}
    </div>
  )
}
