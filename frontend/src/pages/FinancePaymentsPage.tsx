import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { DataTable, type DataTableColumn } from '@/components/ui/DataTable'
import { FilterBar } from '@/components/ui/FilterBar'
import { PageHeader } from '@/components/ui/PageHeader'
import { Spinner } from '@/components/ui/Spinner'
import { DateField } from '@/components/forms/DateField'
import { SelectField } from '@/components/forms/SelectField'
import { TextField } from '@/components/forms/TextField'
import { TextareaField } from '@/components/forms/TextareaField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { formatDate, formatNumber } from '@/lib/format'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { useServerTable, type ServerTableResult } from '@/lib/useServerTable'

/** Mirrors backend/app/schemas/purchase_order.py's FinancePurchaseOrderOut. */
interface FinanceLine {
  material_name: string
  quantity: string
  unit_code: string
  unit_price: string
  line_total: string
}

interface FinancePayment {
  id: number
  payment_number: string
  payment_date: string
  amount: string
  payment_method: string | null
  notes: string | null
  status: string
}

interface FinancePo {
  id: number
  po_number: string
  supplier_name: string
  order_date: string
  expected_delivery_date: string | null
  payment_terms: string | null
  supplier_reference: string | null
  rfq_number: string | null
  notes: string | null
  status: string
  approved_at: string | null
  currency: string
  final_amount: string
  paid_amount: string
  outstanding_amount: string
  /** What's owed back on a cancelled order with a payment already made -- '0.0000' otherwise. */
  refundable_amount: string
  payment_status: 'unpaid' | 'partially_paid' | 'paid'
  lines: FinanceLine[]
  payments: FinancePayment[]
}

interface PaginatedResponse<T> {
  data: T[]
  pagination: { page: number; page_size: number; total: number; total_pages: number }
}

interface Filters {
  search: string
}

const PAYMENT_MODES = ['Bank Transfer', 'Cheque', 'Cash', 'KNET / Card']

const STATUS_LABELS: Record<string, string> = {
  approved: 'Approved',
  sent: 'Sent',
  partially_received: 'Partially Received',
  reconciliation_required: 'Reconciliation Required',
  received: 'Received',
  payment_reconciliation: 'Payment Reconciliation',
  closed: 'Closed',
  cancelled: 'Cancelled',
}

const PAYMENT_STATUS_LABELS: Record<FinancePo['payment_status'], string> = {
  unpaid: 'Pending',
  partially_paid: 'Partially Paid',
  paid: 'Paid',
}

const DECIMAL_RE = /^\d+(\.\d+)?$/

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

function kwd(value: string): string {
  return `${formatNumber(value, { minimumFractionDigits: 3, maximumFractionDigits: 3 })} KWD`
}

async function fetchDue({ page, pageSize, filters }: { page: number; pageSize: number; filters: Filters }): Promise<ServerTableResult<FinancePo>> {
  const { data } = await apiClient.get<PaginatedResponse<FinancePo>>('/api/finance/purchase-orders', {
    params: { page, page_size: pageSize, q: filters.search || undefined },
  })
  return { rows: data.data, total: data.pagination.total }
}

interface PaymentDraft {
  amount: string
  payment_date: string
  payment_method: string
  notes: string
}

function emptyPayment(po: FinancePo | null): PaymentDraft {
  return {
    amount: po ? String(Number(po.outstanding_amount)) : '',
    payment_date: todayIso(),
    payment_method: '',
    notes: '',
  }
}

/** Finance / Accounts (backend/app/api/finance.py): every approved PO
 * comes here, whatever its payment terms; when it is paid is decided case
 * by case. The PO is read-only -- Finance only enters the payment amount,
 * date, mode and notes. `/finance/payments/:id` opens one PO. */
export function FinancePaymentsPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const viewMatch = /^\/finance\/payments\/(\d+)$/.exec(location.pathname)
  const viewId = viewMatch ? Number(viewMatch[1]) : null

  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 300)
  const table = useServerTable<FinancePo, Filters>({ fetcher: fetchDue, pageSize: 20, initialFilters: { search: '' } })

  const [target, setTarget] = useState<FinancePo | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [payment, setPayment] = useState<PaymentDraft>(() => emptyPayment(null))
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const isFirstSearch = useRef(true)
  useEffect(() => {
    if (isFirstSearch.current) {
      isFirstSearch.current = false
      return
    }
    table.setFilters({ search: debouncedSearch })
  }, [debouncedSearch])

  useEffect(() => {
    setError(null)
    setNotice(null)
    setLoadError(null)
    if (viewId === null) {
      setTarget(null)
      return
    }
    const passed = (location.state as { record?: FinancePo } | null)?.record
    if (passed && passed.id === viewId) {
      setTarget(passed)
      setPayment(emptyPayment(passed))
      return
    }
    let cancelled = false
    setTarget(null)
    setLoading(true)
    apiClient
      .get<FinancePo>(`/api/finance/purchase-orders/${viewId}`)
      .then(({ data }) => {
        if (cancelled) return
        setTarget(data)
        setPayment(emptyPayment(data))
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err instanceof ApiError ? err.message : 'Failed to open the purchase order.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [viewId])

  const openPo = (po: FinancePo) => navigate(`/finance/payments/${po.id}`, { state: { record: po } })
  const backToList = () => navigate('/finance/payments')
  const openPurchaseOrder = (id: number) => navigate(`/purchase-orders/${id}`)

  async function savePayment() {
    if (!target) return
    const amount = payment.amount.trim()
    if (!DECIMAL_RE.test(amount) || Number(amount) <= 0) {
      setError('Enter a payment amount greater than zero.')
      return
    }
    if (!payment.payment_date) {
      setError('Enter the payment date.')
      return
    }
    if (!payment.payment_method) {
      setError('Select the payment mode.')
      return
    }
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await apiClient.post(`/api/purchase-orders/${target.id}/payments`, {
        amount,
        payment_date: payment.payment_date,
        payment_method: payment.payment_method,
        notes: payment.notes.trim() || null,
      })
      const { data } = await apiClient.get<FinancePo>(`/api/finance/purchase-orders/${target.id}`)
      setTarget(data)
      setPayment(emptyPayment(data))
      setNotice(`Payment of ${kwd(amount)} recorded.`)
      table.refetch()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to record the payment.')
    } finally {
      setBusy(false)
    }
  }

  const columns: DataTableColumn<FinancePo>[] = [
    { key: 'po_number', label: 'PO Number', render: (po) => po.po_number },
    { key: 'supplier', label: 'Supplier', render: (po) => po.supplier_name },
    { key: 'terms', label: 'Payment Terms', render: (po) => po.payment_terms ?? '—' },
    { key: 'status', label: 'PO Status', hideBelow: 'md', render: (po) => STATUS_LABELS[po.status] ?? po.status },
    { key: 'amount', label: 'PO Amount', hideBelow: 'sm', render: (po) => kwd(po.final_amount) },
    { key: 'outstanding', label: 'Outstanding', render: (po) => kwd(po.outstanding_amount) },
    {
      key: 'actions',
      label: '',
      alwaysVisible: true,
      align: 'right' as const,
      render: (po) => <Button variant="secondary" onClick={() => openPo(po)}>Open</Button>,
    },
  ]

  return (
    <div className="space-y-6">
      <div hidden={viewId !== null} className="space-y-6">
        <PageHeader title="Payments" subtitle="Approved purchase orders with an amount still to pay." />
        <FilterBar>
          <TextField label="Search" placeholder="Search by PO number..." value={searchInput} onChange={(e) => setSearchInput(e.target.value)} />
        </FilterBar>
        <DataTable
          columns={columns}
          rows={table.rows}
          rowKey={(po) => po.id}
          loading={table.loading}
          error={table.error}
          page={table.page}
          totalPages={table.totalPages}
          total={table.total}
          onPageChange={table.setPage}
          pageSize={table.pageSize}
          onPageSizeChange={table.setPageSize}
          emptyTitle={debouncedSearch ? 'No matching purchase orders' : 'Nothing to pay'}
          emptyMessage={debouncedSearch ? 'Try a different PO number.' : 'Approved purchase orders appear here until they are fully paid.'}
        />
      </div>

      {viewId !== null && (
        <section aria-label={target ? `Payment for ${target.po_number}` : 'Payment'} className="space-y-6">
          <PageHeader title={target ? `Purchase Order ${target.po_number}` : 'Purchase Order'} subtitle="Read-only. Record the payment below." />
          {!target ? (
            <div className="flex flex-col gap-4">
              {loading ? <Spinner /> : <Alert variant="danger">{loadError}</Alert>}
              <div>
                <Button variant="secondary" onClick={backToList}>Back to Payments</Button>
              </div>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
                <div><span className="text-gold-100/50">Supplier: </span>{target.supplier_name}</div>
                <div><span className="text-gold-100/50">Payment Terms: </span><strong>{target.payment_terms ?? '—'}</strong></div>
                <div><span className="text-gold-100/50">PO Date: </span>{formatDate(target.order_date)}</div>
                <div><span className="text-gold-100/50">Expected Delivery: </span>{formatDate(target.expected_delivery_date)}</div>
                <div><span className="text-gold-100/50">PO Status: </span>{STATUS_LABELS[target.status] ?? target.status}</div>
                <div><span className="text-gold-100/50">Payment Status: </span><Badge tone={target.payment_status === 'paid' ? 'success' : target.payment_status === 'partially_paid' ? 'warning' : 'danger'}>{PAYMENT_STATUS_LABELS[target.payment_status]}</Badge></div>
                {target.supplier_reference && <div><span className="text-gold-100/50">Supplier Reference: </span>{target.supplier_reference}</div>}
                {target.rfq_number && <div><span className="text-gold-100/50">RFQ: </span>{target.rfq_number}</div>}
                {target.notes && <div className="sm:col-span-2"><span className="text-gold-100/50">Notes: </span>{target.notes}</div>}
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                      <th className="py-2 pr-3">Product / Material</th>
                      <th className="py-2 pr-3">Quantity</th>
                      <th className="py-2 pr-3">UOM</th>
                      <th className="py-2 pr-3">Unit Price</th>
                      <th className="py-2 pr-3">Line Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {target.lines.map((line, index) => (
                      <tr key={index} className="border-t border-ink-700">
                        <td className="py-2 pr-3">{line.material_name}</td>
                        <td className="py-2 pr-3">{formatNumber(line.quantity)}</td>
                        <td className="py-2 pr-3">{line.unit_code}</td>
                        <td className="py-2 pr-3">{formatNumber(line.unit_price, { minimumFractionDigits: 3, maximumFractionDigits: 3 })}</td>
                        <td className="py-2 pr-3">{formatNumber(line.line_total, { minimumFractionDigits: 3, maximumFractionDigits: 3 })}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
                <div><span className="text-gold-100/50">PO Amount: </span>{kwd(target.final_amount)}</div>
                <div><span className="text-gold-100/50">Paid: </span>{kwd(target.paid_amount)}</div>
                {target.status === 'cancelled' ? (
                  <div><span className="text-gold-100/50">Refundable: </span><strong>{kwd(target.refundable_amount)}</strong></div>
                ) : (
                  <div><span className="text-gold-100/50">Outstanding: </span><strong>{kwd(target.outstanding_amount)}</strong></div>
                )}
              </div>
              {target.status === 'cancelled' && Number(target.refundable_amount) > 0 && (
                <Alert variant="info">
                  This order was cancelled with {kwd(target.refundable_amount)} already paid -- no further payment is
                  due; this amount is owed back from the supplier.
                </Alert>
              )}

              {target.payments.length > 0 && (
                <div>
                  <h3 className="mb-2 text-xs uppercase tracking-wide text-gold-100/50">Payments</h3>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                        <th className="py-2 pr-3">Payment No.</th>
                        <th className="py-2 pr-3">Date</th>
                        <th className="py-2 pr-3">Amount</th>
                        <th className="py-2 pr-3">Mode</th>
                        <th className="py-2 pr-3">Notes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {target.payments.map((p) => (
                        <tr key={p.id} className="border-t border-ink-700">
                          <td className="py-2 pr-3">{p.payment_number}{p.status === 'cancelled' && <span className="block text-xs text-gold-100/50">Cancelled</span>}</td>
                          <td className="py-2 pr-3">{formatDate(p.payment_date)}</td>
                          <td className="py-2 pr-3">{kwd(p.amount)}</td>
                          <td className="py-2 pr-3">{p.payment_method ?? '—'}</td>
                          <td className="py-2 pr-3">{p.notes ?? '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <Alert variant="success">{notice}</Alert>
              {Number(target.outstanding_amount) > 0 && (
                <div className="rounded-md border border-ink-700 p-4">
                  <h3 className="mb-3 text-xs uppercase tracking-wide text-gold-100/50">Record Payment</h3>
                  {target.payment_terms === 'Prepaid' && (
                    <Alert variant="info">Prepaid: record the payment already made to the supplier.</Alert>
                  )}
                  <Alert variant="danger">{error}</Alert>
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <TextField
                      label="Payment Amount (KWD)"
                      required
                      type="number"
                      min="0"
                      step="any"
                      value={payment.amount}
                      onChange={(e) => setPayment((prev) => ({ ...prev, amount: e.target.value }))}
                    />
                    <DateField
                      label="Payment Date"
                      required
                      value={payment.payment_date}
                      onChange={(e) => setPayment((prev) => ({ ...prev, payment_date: e.target.value }))}
                    />
                    <SelectField
                      label="Payment Mode"
                      required
                      value={payment.payment_method}
                      onChange={(e) => setPayment((prev) => ({ ...prev, payment_method: e.target.value }))}
                    >
                      <option value="">Select...</option>
                      {PAYMENT_MODES.map((mode) => (
                        <option key={mode} value={mode}>{mode}</option>
                      ))}
                    </SelectField>
                    <TextareaField
                      label="Notes"
                      value={payment.notes}
                      onChange={(e) => setPayment((prev) => ({ ...prev, notes: e.target.value }))}
                    />
                  </div>
                </div>
              )}

              <div className="flex flex-wrap justify-end gap-2 border-t border-ink-700 pt-4">
                <Button variant="secondary" onClick={backToList}>Back to Payments</Button>
                <Button variant="secondary" onClick={() => openPurchaseOrder(target.id)}>Open Purchase Order</Button>
                {Number(target.outstanding_amount) > 0 && (
                  <Button onClick={savePayment} isLoading={busy}>Save Payment</Button>
                )}
              </div>
            </>
          )}
        </section>
      )}
    </div>
  )
}
