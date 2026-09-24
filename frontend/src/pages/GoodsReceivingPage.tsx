import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ActionMenu } from '@/components/ui/ActionMenu'
import { Alert } from '@/components/ui/Alert'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { DataTable, type DataTableColumn } from '@/components/ui/DataTable'
import { FilterBar } from '@/components/ui/FilterBar'
import { Modal } from '@/components/ui/Modal'
import { PageHeader } from '@/components/ui/PageHeader'
import { DateField } from '@/components/forms/DateField'
import { FileUploadField } from '@/components/forms/FileUploadField'
import { TextField } from '@/components/forms/TextField'
import { TextareaField } from '@/components/forms/TextareaField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { formatDate, formatNumber } from '@/lib/format'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { useServerTable, type ServerTableResult } from '@/lib/useServerTable'

/** Mirrors backend/app/schemas/purchase_order.py's ReceivingOut -- the
 * warehouse view: quantities only, never prices. */
interface ReceivingFile {
  id: number
  original_filename: string
}

interface ReceivingLine {
  id: number
  raw_material_id: number
  material_name: string
  unit_code: string
  ordered_quantity: string
  received_quantity: string
  remaining_quantity: string
}

interface ReceivingReceipt {
  id: number
  receipt_number: string
  receipt_date: string
  status: string
  posted_at: string | null
  received_by_name: string | null
  supplier_delivery_reference: string | null
  notes: string | null
  days_late: number
  lines: { material_name: string; unit_code: string; quantity: string; remarks: string | null }[]
  documents: ReceivingFile[]
}

interface ReceivingPo {
  id: number
  po_number: string
  supplier_name: string
  warehouse_name: string
  expected_delivery_date: string | null
  delivery_instructions: string | null
  status: string
  can_receive: boolean
  lines: ReceivingLine[]
  receipts: ReceivingReceipt[]
}

interface PaginatedResponse<T> {
  data: T[]
  pagination: { page: number; page_size: number; total: number; total_pages: number }
}

interface Filters {
  search: string
}

const DECIMAL_RE = /^\d+(\.\d+)?$/

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

async function fetchReceivable({ page, pageSize, filters }: { page: number; pageSize: number; filters: Filters }): Promise<ServerTableResult<ReceivingPo>> {
  const { data } = await apiClient.get<PaginatedResponse<ReceivingPo>>('/api/goods-receiving', {
    params: { page, page_size: pageSize, q: filters.search || undefined },
  })
  return { rows: data.data, total: data.pagination.total }
}

/** Goods Receiving (backend/app/api/goods_receiving.py): the warehouse
 * records what physically arrived against a sent PO. Submit Receipt posts
 * stock and reconciles automatically -- a short line goes back to the PO
 * creator. No prices, totals or payment terms are ever loaded here. */
export function GoodsReceivingPage() {
  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 300)
  const table = useServerTable<ReceivingPo, Filters>({ fetcher: fetchReceivable, pageSize: 20, initialFilters: { search: '' } })

  const [target, setTarget] = useState<ReceivingPo | null>(null)
  const [quantities, setQuantities] = useState<Record<number, string>>({})
  const [remarks, setRemarks] = useState<Record<number, string>>({})
  const [receiptDate, setReceiptDate] = useState(todayIso())
  const [deliveryRef, setDeliveryRef] = useState('')
  const [notes, setNotes] = useState('')
  const [files, setFiles] = useState<File[]>([])
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

  const open = useCallback((po: ReceivingPo) => {
    setTarget(po)
    setQuantities(Object.fromEntries(po.lines.map((line) => [line.id, String(Number(line.remaining_quantity))])))
    setRemarks({})
    setReceiptDate(todayIso())
    setDeliveryRef('')
    setNotes('')
    setFiles([])
    setError(null)
    setNotice(null)
  }, [])

  // Arriving from the Purchase Orders page: open that PO straight away.
  const location = useLocation()
  const navigate = useNavigate()
  const openId = (location.state as { openPurchaseOrderId?: number } | null)?.openPurchaseOrderId
  useEffect(() => {
    if (!openId) return
    navigate(location.pathname, { replace: true, state: null })
    apiClient
      .get<ReceivingPo>(`/api/goods-receiving/${openId}`)
      .then(({ data }) => open(data))
      .catch((err) => setNotice(err instanceof ApiError ? err.message : 'Failed to open the purchase order.'))
  }, [openId, open])

  async function downloadFile(file: ReceivingFile) {
    try {
      const response = await apiClient.get(`/api/files/${file.id}`, { responseType: 'blob' })
      const url = window.URL.createObjectURL(response.data as Blob)
      const link = document.createElement('a')
      link.href = url
      link.download = file.original_filename
      link.click()
      window.URL.revokeObjectURL(url)
    } catch {
      setError('Failed to download file.')
    }
  }

  async function submitReceipt() {
    if (!target) return
    const lines = target.lines
      .filter((line) => (quantities[line.id] ?? '').trim() !== '' && Number(quantities[line.id]) > 0)
      .map((line) => ({ purchase_order_line_id: line.id, quantity: quantities[line.id].trim(), remarks: remarks[line.id]?.trim() || null }))
    if (lines.length === 0) {
      setError('Enter the received quantity for at least one item.')
      return
    }
    if (lines.some((line) => !DECIMAL_RE.test(line.quantity))) {
      setError('Quantities must be positive numbers.')
      return
    }
    if (!receiptDate || receiptDate > todayIso()) {
      setError('Receipt date is required and cannot be in the future.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const fileIds: number[] = []
      for (const file of files) {
        const form = new FormData()
        form.append('upload', file)
        const { data } = await apiClient.post<{ id: number }>('/api/files', form)
        fileIds.push(data.id)
      }
      const { data } = await apiClient.post<ReceivingPo>(`/api/goods-receiving/${target.id}/receipts`, {
        receipt_date: receiptDate,
        supplier_delivery_reference: deliveryRef.trim() || null,
        notes: notes.trim() || null,
        lines,
        file_ids: fileIds,
      })
      table.refetch()
      open(data)
      setNotice(
        data.status === 'reconciliation_required'
          ? 'Receipt recorded. Quantities differ from the order -- the PO has been returned to its creator.'
          : 'Receipt recorded.',
      )
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to record the receipt.')
    } finally {
      setBusy(false)
    }
  }

  const columns: DataTableColumn<ReceivingPo>[] = [
    { key: 'po_number', label: 'PO Number', render: (po) => po.po_number },
    { key: 'supplier', label: 'Supplier', render: (po) => po.supplier_name },
    { key: 'expected', label: 'Expected Delivery', render: (po) => formatDate(po.expected_delivery_date) },
    { key: 'items', label: 'Items', hideBelow: 'sm', render: (po) => po.lines.length },
    { key: 'location', label: 'Delivery Location', hideBelow: 'md', render: (po) => po.warehouse_name },
    {
      key: 'actions',
      label: '',
      alwaysVisible: true,
      align: 'right' as const,
      render: (po: ReceivingPo) => (
        <ActionMenu label={`Actions for ${po.po_number}`} options={[{ key: 'receive', label: 'Receive Goods...', onSelect: () => open(po) }]} />
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader title="Goods Receiving" subtitle="Record what arrived against purchase orders sent to suppliers." />
      <Alert variant="info">{!target ? notice : null}</Alert>

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
        emptyTitle="Nothing to receive"
        emptyMessage="Purchase orders appear here once they have been sent to the supplier."
      />

      <Modal
        open={!!target}
        title={target ? `Receive — PO ${target.po_number}` : ''}
        size="wide"
        onClose={() => setTarget(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setTarget(null)}>Close</Button>
            {target?.can_receive && <Button onClick={submitReceipt} isLoading={busy}>Submit Receipt</Button>}
          </>
        }
      >
        {target && (
          <div className="flex flex-col gap-4">
            <Alert variant="danger">{error}</Alert>
            <Alert variant="success">{notice}</Alert>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
              <div><span className="text-gold-100/50">Supplier: </span>{target.supplier_name}</div>
              <div><span className="text-gold-100/50">Expected Delivery: </span>{formatDate(target.expected_delivery_date)}</div>
              <div><span className="text-gold-100/50">Delivery Location: </span>{target.warehouse_name}</div>
              {!target.can_receive && <div><Badge tone="warning">Not open for receiving</Badge></div>}
              {target.delivery_instructions && (
                <div className="col-span-2"><span className="text-gold-100/50">Instructions: </span>{target.delivery_instructions}</div>
              )}
            </div>

            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                  <th className="py-2 pr-3">Material</th>
                  <th className="py-2 pr-3">Ordered</th>
                  <th className="py-2 pr-3">Already Received</th>
                  {target.can_receive && <th className="py-2 pr-3">Received Now</th>}
                  {target.can_receive && <th className="py-2 pr-3">Remarks</th>}
                </tr>
              </thead>
              <tbody>
                {target.lines.map((line) => (
                  <tr key={line.id} className="border-t border-ink-700">
                    <td className="py-2 pr-3">{line.material_name}</td>
                    <td className="py-2 pr-3">{formatNumber(line.ordered_quantity)} {line.unit_code}</td>
                    <td className="py-2 pr-3">{formatNumber(line.received_quantity)} {line.unit_code}</td>
                    {target.can_receive && (
                      <td className="py-2 pr-3">
                        <input
                          type="number"
                          min="0"
                          step="any"
                          aria-label={`Received quantity for ${line.material_name}`}
                          className="w-24 rounded border border-ink-700 bg-ink-900 px-2 py-1 text-sm"
                          value={quantities[line.id] ?? ''}
                          onChange={(e) => setQuantities((prev) => ({ ...prev, [line.id]: e.target.value }))}
                        />{' '}
                        {line.unit_code}
                      </td>
                    )}
                    {target.can_receive && (
                      <td className="py-2 pr-3">
                        <input
                          type="text"
                          aria-label={`Remarks for ${line.material_name}`}
                          className="w-full rounded border border-ink-700 bg-ink-900 px-2 py-1 text-sm"
                          value={remarks[line.id] ?? ''}
                          onChange={(e) => setRemarks((prev) => ({ ...prev, [line.id]: e.target.value }))}
                        />
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>

            {target.can_receive && (
              <div className="grid gap-4 sm:grid-cols-2">
                <DateField label="Receipt Date" required max={todayIso()} value={receiptDate} onChange={(e) => setReceiptDate(e.target.value)} />
                <TextField label="Delivery Note / Supplier Document No." value={deliveryRef} onChange={(e) => setDeliveryRef(e.target.value)} />
                <FileUploadField label="Attachment (delivery note, photo)" multiple accept=".pdf,.png,.jpg,.jpeg" value={files} onChange={setFiles} />
                <TextareaField label="Remarks" value={notes} onChange={(e) => setNotes(e.target.value)} />
              </div>
            )}

            {target.receipts.length > 0 && (
              <div>
                <h3 className="mb-2 text-xs uppercase tracking-wide text-gold-100/50">Receipts</h3>
                <ul className="flex flex-col gap-2 text-sm">
                  {target.receipts.map((receipt) => (
                    <li key={receipt.id} className="rounded-md border border-ink-700 p-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{receipt.receipt_number}</span>
                        <span>{formatDate(receipt.receipt_date)}</span>
                        {receipt.received_by_name && <span className="text-xs text-gold-100/50">by {receipt.received_by_name}</span>}
                        {receipt.days_late > 0 && <Badge tone="warning">{`${receipt.days_late} day(s) late`}</Badge>}
                        {receipt.status !== 'posted' && <Badge tone="neutral">{receipt.status}</Badge>}
                      </div>
                      <div className="mt-1 text-gold-100/80">
                        {receipt.lines.map((line, index) => (
                          <div key={index}>
                            {line.material_name}: {formatNumber(line.quantity)} {line.unit_code}
                            {line.remarks ? ` — ${line.remarks}` : ''}
                          </div>
                        ))}
                      </div>
                      {receipt.documents.length > 0 && (
                        <div className="mt-1 flex flex-wrap gap-1">
                          {receipt.documents.map((file) => (
                            <button key={file.id} type="button" onClick={() => downloadFile(file)} className="rounded border border-ink-700 px-2 py-0.5 text-xs hover:border-gold-400">
                              {file.original_filename}
                            </button>
                          ))}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}
