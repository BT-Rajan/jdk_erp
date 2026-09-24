import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { useLocation, useNavigate } from 'react-router-dom'
import { z } from 'zod'
import { ActionMenu, type ActionMenuOption } from '@/components/ui/ActionMenu'
import { Alert } from '@/components/ui/Alert'
import { Badge, type BadgeTone } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { DataTable, type DataTableColumn } from '@/components/ui/DataTable'
import { FilterBar } from '@/components/ui/FilterBar'
import { Modal } from '@/components/ui/Modal'
import { PageHeader } from '@/components/ui/PageHeader'
import type { SortState } from '@/components/ui/sort'
import { Spinner } from '@/components/ui/Spinner'
import { DateField } from '@/components/forms/DateField'
import { FileUploadField } from '@/components/forms/FileUploadField'
import { SelectField } from '@/components/forms/SelectField'
import { TextField } from '@/components/forms/TextField'
import { TextareaField } from '@/components/forms/TextareaField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { useAuth } from '@/lib/auth/AuthContext'
import { isAdminRole } from '@/lib/auth/roles'
import { formatDate, formatNumber } from '@/lib/format'
import { formatKuwaitTime } from '@/lib/timezone'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { useServerTable, type ServerTableResult } from '@/lib/useServerTable'
import {
  isPositiveDecimal,
  todayIso,
  type LookupOption,
  type MaterialOption,
  type PaginatedResponse,
  type Rfq,
  type RfqFile,
  type RfqInvitation,
  type RfqResponse,
} from './rfqShared'

interface RfqsFilters {
  search: string
  priority: string
}

const STATUS_LABELS: Record<Rfq['status'], string> = {
  draft: 'Draft',
  issued: 'Issued',
  response_received: 'Quotes Received',
  selected: 'Approved',
  rejected: 'Rejected',
  cancelled: 'Cancelled',
  converted: 'PO Created',
}

const STATUS_TONES: Record<Rfq['status'], BadgeTone> = {
  draft: 'info',
  issued: 'gold',
  response_received: 'warning',
  selected: 'gold',
  rejected: 'danger',
  cancelled: 'danger',
  converted: 'success',
}

const INVITATION_LABELS: Record<RfqInvitation['status'], string> = { sent: 'Awaiting Quote', quoted: 'Quoted', declined: 'Declined' }
const INVITATION_TONES: Record<RfqInvitation['status'], BadgeTone> = { sent: 'info', quoted: 'success', declined: 'neutral' }

const INTEGER_RE = /^\d+$/
const ACCEPTANCE_TYPES = '.pdf,.png,.jpg,.jpeg'

function formatPrice(value: string): string {
  return formatNumber(value, { minimumFractionDigits: 3, maximumFractionDigits: 4 })
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(0)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

/** The most recent response per invitation -- a revision supersedes the
 * earlier quote for comparison, while the full history stays visible in
 * each supplier's own thread. */
function latestResponse(invitation: RfqInvitation): RfqResponse | undefined {
  return invitation.responses[invitation.responses.length - 1]
}

function hasQuotes(rfq: Rfq): boolean {
  return rfq.invitations.some((i) => i.responses.length > 0)
}

async function uploadFiles(files: File[]): Promise<number[]> {
  const ids: number[] = []
  for (const file of files) {
    const form = new FormData()
    form.append('upload', file)
    const { data } = await apiClient.post<{ id: number }>('/api/files', form)
    ids.push(data.id)
  }
  return ids
}

// --- comparison ---------------------------------------------------------------

/** Side-by-side read-only comparison: RFQ lines down the rows, one column
 * per supplier that has quoted (latest quote). Nothing is ranked or
 * totalled -- the decision stays the user's. */
function ComparisonTable({
  rfq,
  materialName,
  unitCode,
  supplierName,
}: {
  rfq: Rfq
  materialName: (id: number) => string
  unitCode: (id: number) => string
  supplierName: (id: number) => string
}) {
  const columns = rfq.invitations
    .map((invitation) => ({ invitation, response: latestResponse(invitation) }))
    .filter((c): c is { invitation: RfqInvitation; response: RfqResponse } => c.response !== undefined)

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
            <th className="py-2 pr-3">Product / Material</th>
            <th className="py-2 pr-3">Qty</th>
            {columns.map(({ invitation, response }) => (
              <th key={invitation.id} className="py-2 pr-3">
                {supplierName(invitation.supplier_id)}
                {rfq.selected_response_id === response.id && <Badge tone="gold" className="ml-2">Approved</Badge>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rfq.lines.map((line) => (
            <tr key={line.id} className="border-t border-ink-700">
              <td className="py-2 pr-3">
                {materialName(line.raw_material_id)}
                {line.remarks && <span className="block text-xs text-gold-100/50">{line.remarks}</span>}
              </td>
              <td className="py-2 pr-3">{formatNumber(line.quantity)} {unitCode(line.unit_of_measure_id)}</td>
              {columns.map(({ invitation, response }) => {
                const quoted = response.lines.find((l) => l.rfq_line_id === line.id)
                return (
                  <td key={invitation.id} className="py-2 pr-3">
                    {quoted ? (
                      <>
                        {formatPrice(quoted.unit_price)}
                        {quoted.delivery_days !== null && <span className="block text-xs text-gold-100/50">{quoted.delivery_days} days</span>}
                      </>
                    ) : (
                      <span className="text-gold-100/40">Not quoted</span>
                    )}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// --- page ---------------------------------------------------------------------

const cancelSchema = z.object({ cancel_reason: z.string().min(1, 'A reason is required to cancel this RFQ.') })
type CancelFormValues = z.infer<typeof cancelSchema>

const captureSchema = z.object({
  supplier_quotation_number: z.string(),
  quotation_date: z.string(),
  valid_until: z.string(),
  payment_terms: z.string(),
  delivery_terms: z.string(),
  freight_terms: z.string(),
  note: z.string(),
})
type CaptureFormValues = z.infer<typeof captureSchema>
const emptyCaptureDefaults: CaptureFormValues = {
  supplier_quotation_number: '',
  quotation_date: '',
  valid_until: '',
  payment_terms: '',
  delivery_terms: '',
  freight_terms: '',
  note: '',
}

interface CaptureLineDraft {
  unit_price: string
  delivery_days: string
  remarks: string
}

interface ConvertLineDraft {
  include: boolean
  unit_price: string
}

async function fetchRfqs({
  page,
  pageSize,
  sort,
  filters,
}: {
  page: number
  pageSize: number
  sort: SortState | null
  filters: RfqsFilters
}): Promise<ServerTableResult<Rfq>> {
  const { data } = await apiClient.get<PaginatedResponse<Rfq>>('/api/rfqs', {
    params: {
      page,
      page_size: pageSize,
      sort_by: sort?.field,
      sort_direction: sort?.direction,
      q: filters.search || undefined,
      priority: filters.priority || undefined,
    },
  })
  return { rows: data.data, total: data.pagination.total }
}

/** RFQ -> Supplier Quotes -> Accept (with the accepted quotation
 * uploaded) or Reject -> Purchase Order (backend/app/api/rfqs.py,
 * docs/modules/rfq.md). One modal to create/edit/revise the RFQ, one
 * detail modal carrying the rest of the lifecycle. */
export function RfqsPage() {
  const { user: currentUser } = useAuth()
  const canManage = isAdminRole(currentUser?.role)
  const navigate = useNavigate()

  const [suppliers, setSuppliers] = useState<LookupOption[]>([])
  const [warehouses, setWarehouses] = useState<LookupOption[]>([])
  const [materials, setMaterials] = useState<MaterialOption[]>([])
  const [units, setUnits] = useState<LookupOption[]>([])
  const [pageError, setPageError] = useState<string | undefined>(undefined)

  const [searchInput, setSearchInput] = useState('')
  const [priorityFilter, setPriorityFilter] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 300)


  const [detailTarget, setDetailTarget] = useState<Rfq | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [detailNotice, setDetailNotice] = useState<string | null>(null)
  const [emailBusy, setEmailBusy] = useState<number | null>(null)

  const [cancelTarget, setCancelTarget] = useState<Rfq | null>(null)
  const [cancelError, setCancelError] = useState<string | null>(null)

  const [captureInvitation, setCaptureInvitation] = useState<RfqInvitation | null>(null)
  const [captureLines, setCaptureLines] = useState<Record<number, CaptureLineDraft>>({})
  const [captureFiles, setCaptureFiles] = useState<File[]>([])
  const [captureError, setCaptureError] = useState<string | null>(null)

  const [decisionOpen, setDecisionOpen] = useState(false)
  const [decision, setDecision] = useState<'selected' | 'rejected'>('selected')
  const [decisionResponseId, setDecisionResponseId] = useState('')
  const [decisionNote, setDecisionNote] = useState('')
  const [decisionFiles, setDecisionFiles] = useState<File[]>([])
  const [agreedQuantities, setAgreedQuantities] = useState<Record<number, string>>({})
  const [decisionBusy, setDecisionBusy] = useState(false)
  const [decisionError, setDecisionError] = useState<string | null>(null)

  const [convertOpen, setConvertOpen] = useState(false)
  const [convertWarehouseId, setConvertWarehouseId] = useState('')
  const [convertLines, setConvertLines] = useState<Record<number, ConvertLineDraft>>({})
  const [convertExpectedDate, setConvertExpectedDate] = useState('')
  const [convertPaymentTerms, setConvertPaymentTerms] = useState('')
  const [convertSupplierRef, setConvertSupplierRef] = useState('')
  const [convertNotes, setConvertNotes] = useState('')
  const [convertBusy, setConvertBusy] = useState(false)
  const [convertError, setConvertError] = useState<string | null>(null)

  const cancelForm = useForm<CancelFormValues>({ resolver: zodResolver(cancelSchema), defaultValues: { cancel_reason: '' } })
  const captureForm = useForm<CaptureFormValues>({ resolver: zodResolver(captureSchema), defaultValues: emptyCaptureDefaults })

  const table = useServerTable<Rfq, RfqsFilters>({ fetcher: fetchRfqs, pageSize: 20, initialFilters: { search: '', priority: '' } })

  const isFirstFilterRender = useRef(true)
  useEffect(() => {
    if (isFirstFilterRender.current) {
      isFirstFilterRender.current = false
      return
    }
    table.setFilters({ search: debouncedSearch, priority: priorityFilter })
  }, [debouncedSearch, priorityFilter])

  const suppliersById = useMemo(() => new Map(suppliers.map((s) => [s.id, s])), [suppliers])
  const materialsById = useMemo(() => new Map(materials.map((m) => [m.id, m])), [materials])
  const unitsById = useMemo(() => new Map(units.map((u) => [u.id, u])), [units])

  const supplierName = useCallback((id: number) => suppliersById.get(id)?.name ?? `#${id}`, [suppliersById])
  const materialName = useCallback((id: number) => materialsById.get(id)?.name ?? `#${id}`, [materialsById])
  const unitCode = useCallback((id: number) => unitsById.get(id)?.code ?? '', [unitsById])

  const loadLookups = useCallback(async () => {
    try {
      const [suppliersResponse, warehousesResponse, materialsResponse, unitsResponse] = await Promise.all([
        apiClient.get<PaginatedResponse<LookupOption>>('/api/suppliers', { params: { page_size: 200 } }),
        apiClient.get<PaginatedResponse<LookupOption>>('/api/warehouses', { params: { page_size: 200 } }),
        apiClient.get<PaginatedResponse<MaterialOption>>('/api/raw-materials', { params: { page_size: 200 } }),
        apiClient.get<PaginatedResponse<LookupOption>>('/api/units-of-measure', { params: { page_size: 200 } }),
      ])
      setSuppliers(suppliersResponse.data.data)
      setWarehouses(warehousesResponse.data.data)
      setMaterials(materialsResponse.data.data)
      setUnits(unitsResponse.data.data)
    } catch (err) {
      setPageError(err instanceof ApiError ? err.message : 'Failed to load suppliers, warehouses, materials and units.')
    }
  }, [])

  useEffect(() => {
    void loadLookups()
  }, [loadLookups])

  /** Lands on Purchase Orders with that PO open. */
  function openPurchaseOrder(purchaseOrderId: number | null) {
    navigate('/purchase-orders', { state: purchaseOrderId ? { openPurchaseOrderId: purchaseOrderId } : undefined })
  }

  // Viewing an RFQ is its own page: /rfqs/:rfqId. Opening it from the
  // list passes the row along; a direct visit, refresh or arrival from
  // the RFQ form page loads it.
  const location = useLocation()
  const viewMatch = /^\/rfqs\/(\d+)$/.exec(location.pathname)
  const viewId = viewMatch ? Number(viewMatch[1]) : null
  const arrival = location.state as { record?: Rfq; notice?: string } | null
  const [viewLoading, setViewLoading] = useState(false)
  useEffect(() => {
    if (viewId === null) {
      setDetailTarget(null)
      return
    }
    resetDetail()
    setDetailNotice(arrival?.notice ?? null)
    if (arrival?.record && arrival.record.id === viewId) {
      setDetailTarget(arrival.record)
      return
    }
    let cancelled = false
    setDetailTarget(null)
    setViewLoading(true)
    apiClient
      .get<Rfq>(`/api/rfqs/${viewId}`)
      .then(({ data }) => {
        if (!cancelled) setDetailTarget(data)
      })
      .catch((err) => {
        if (!cancelled) setDetailError(err instanceof ApiError ? err.message : 'Failed to open the RFQ.')
      })
      .finally(() => {
        if (!cancelled) setViewLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [viewId])

  const refreshDetail = useCallback(
    async (id: number) => {
      const { data } = await apiClient.get<Rfq>(`/api/rfqs/${id}`)
      setDetailTarget(data)
      table.refetch()
      return data
    },
    [table],
  )

  function openDetail(rfq: Rfq) {
    navigate(`/rfqs/${rfq.id}`, { state: { record: rfq } })
  }

  function closeDetail() {
    navigate('/rfqs')
  }

  function resetDetail() {
    setDetailError(null)
    setDetailNotice(null)
    setCaptureInvitation(null)
    setDecisionOpen(false)
    setConvertOpen(false)
  }

  /** New / edit / revise happens on its own page (RfqFormPage.tsx). */
  function openForm(rfq: Rfq | null) {
    navigate(rfq ? `/rfqs/${rfq.id}/edit` : '/rfqs/new')
  }



  async function downloadFile(file: RfqFile) {
    try {
      const response = await apiClient.get(`/api/files/${file.id}`, { responseType: 'blob' })
      const url = window.URL.createObjectURL(response.data as Blob)
      const link = document.createElement('a')
      link.href = url
      link.download = file.original_filename
      link.click()
      window.URL.revokeObjectURL(url)
    } catch {
      setDetailError('Failed to download file.')
    }
  }

  async function emailInvitation(invitation: RfqInvitation) {
    if (!detailTarget) return
    setEmailBusy(invitation.id)
    setDetailError(null)
    setDetailNotice(null)
    try {
      await apiClient.post(`/api/rfqs/${detailTarget.id}/invitations/${invitation.id}/send`)
      await refreshDetail(detailTarget.id)
      setDetailNotice(`RFQ emailed to ${supplierName(invitation.supplier_id)}.`)
    } catch (err) {
      setDetailError(err instanceof ApiError ? err.message : 'Failed to send email.')
    } finally {
      setEmailBusy(null)
    }
  }

  async function declineInvitation(invitation: RfqInvitation) {
    if (!detailTarget) return
    setDetailError(null)
    try {
      await apiClient.post(`/api/rfqs/${detailTarget.id}/invitations/${invitation.id}/decline`)
      await refreshDetail(detailTarget.id)
    } catch (err) {
      setDetailError(err instanceof ApiError ? err.message : 'Failed to mark supplier as declined.')
    }
  }

  function openCancel(rfq: Rfq) {
    setCancelTarget(rfq)
    cancelForm.reset({ cancel_reason: '' })
    setCancelError(null)
  }

  const onCancelSubmit = useCallback(
    async (values: CancelFormValues) => {
      if (!cancelTarget) return
      setCancelError(null)
      try {
        await apiClient.patch(`/api/rfqs/${cancelTarget.id}/status`, { status: 'cancelled', cancel_reason: values.cancel_reason })
        setCancelTarget(null)
        table.refetch()
        if (detailTarget?.id === cancelTarget.id) await refreshDetail(cancelTarget.id)
      } catch (err) {
        setCancelError(err instanceof ApiError ? err.message : 'Failed to cancel RFQ.')
      }
    },
    [cancelTarget, detailTarget, refreshDetail, table],
  )

  function openCapture(invitation: RfqInvitation) {
    captureForm.reset(emptyCaptureDefaults)
    setCaptureLines({})
    setCaptureFiles([])
    setCaptureError(null)
    setCaptureInvitation(invitation)
  }

  function updateCaptureLine(lineId: number, patch: Partial<CaptureLineDraft>) {
    setCaptureLines((prev) => ({ ...prev, [lineId]: { ...(prev[lineId] ?? { unit_price: '', delivery_days: '', remarks: '' }), ...patch } }))
  }

  const onCaptureSubmit = useCallback(
    async (values: CaptureFormValues) => {
      if (!detailTarget || !captureInvitation) return
      const quoted = detailTarget.lines
        .map((line) => ({ line, draft: captureLines[line.id] }))
        .filter(({ draft }) => draft && draft.unit_price.trim() !== '')
      if (quoted.length === 0) {
        setCaptureError('Enter a unit price for at least one item. Leave an item blank if the supplier did not quote it.')
        return
      }
      if (quoted.some(({ draft }) => !isPositiveDecimal(draft.unit_price.trim()))) {
        setCaptureError('Unit prices must be positive numbers.')
        return
      }
      if (quoted.some(({ draft }) => draft.delivery_days.trim() !== '' && !INTEGER_RE.test(draft.delivery_days.trim()))) {
        setCaptureError('Delivery days must be a whole number.')
        return
      }
      setCaptureError(null)
      try {
        const fileIds = await uploadFiles(captureFiles)
        await apiClient.post(`/api/rfqs/${detailTarget.id}/invitations/${captureInvitation.id}/responses`, {
          response_received_at: new Date().toISOString(),
          supplier_quotation_number: values.supplier_quotation_number || null,
          quotation_date: values.quotation_date || null,
          valid_until: values.valid_until || null,
          payment_terms: values.payment_terms || null,
          delivery_terms: values.delivery_terms || null,
          freight_terms: values.freight_terms || null,
          note: values.note || null,
          lines: quoted.map(({ line, draft }) => ({
            rfq_line_id: line.id,
            unit_price: draft.unit_price.trim(),
            delivery_days: draft.delivery_days.trim() === '' ? null : Number(draft.delivery_days),
            remarks: draft.remarks.trim() || null,
          })),
          file_ids: fileIds,
        })
        setCaptureInvitation(null)
        await refreshDetail(detailTarget.id)
      } catch (err) {
        setCaptureError(err instanceof ApiError ? err.message : 'Failed to capture quotation.')
      }
    },
    [captureFiles, captureInvitation, captureLines, detailTarget, refreshDetail],
  )

  function openDecision() {
    setDecision('selected')
    setDecisionResponseId('')
    setDecisionNote('')
    setDecisionFiles([])
    setAgreedQuantities(Object.fromEntries((detailTarget?.lines ?? []).map((line) => [line.id, String(Number(line.quantity))])))
    setDecisionError(null)
    setDecisionOpen(true)
  }

  const changedQuantities = (detailTarget?.lines ?? []).filter(
    (line) => agreedQuantities[line.id] !== undefined && Number(agreedQuantities[line.id]) !== Number(line.quantity),
  )

  /** Agreed quantity differs from the request: this RFQ can't be
   * approved -- it is cancelled and a new draft RFQ is raised with the
   * agreed quantities, opened straight in the RFQ form. */
  async function raiseNewRfq() {
    if (!detailTarget) return
    if (changedQuantities.some((line) => !isPositiveDecimal(agreedQuantities[line.id].trim()))) {
      setDecisionError('Agreed quantities must be greater than zero.')
      return
    }
    setDecisionBusy(true)
    setDecisionError(null)
    try {
      const { data } = await apiClient.post<Rfq>(`/api/rfqs/${detailTarget.id}/raise-new`, {
        lines: changedQuantities.map((line) => ({ rfq_line_id: line.id, quantity: agreedQuantities[line.id].trim() })),
      })
      setDecisionOpen(false)
      setDetailTarget(null)
      table.refetch()
      openForm(data)
    } catch (err) {
      setDecisionError(err instanceof ApiError ? err.message : 'Failed to raise a new RFQ.')
    } finally {
      setDecisionBusy(false)
    }
  }

  async function submitDecision() {
    if (!detailTarget) return
    if (decision === 'selected') {
      if (!decisionResponseId) {
        setDecisionError('Choose the supplier quotation you are approving.')
        return
      }
      if (changedQuantities.length > 0) {
        setDecisionError('The agreed quantity differs from the request -- raise another RFQ instead.')
        return
      }
      if (decisionFiles.length === 0) {
        setDecisionError("Upload the document received from the supplier (PDF or image) to approve.")
        return
      }
    }
    setDecisionBusy(true)
    setDecisionError(null)
    try {
      const fileIds = decision === 'selected' ? await uploadFiles(decisionFiles) : []
      await apiClient.patch(`/api/rfqs/${detailTarget.id}/decision`, {
        decision,
        selected_response_id: decision === 'selected' ? Number(decisionResponseId) : null,
        note: decisionNote.trim() || null,
        file_ids: fileIds,
        quantities_confirmed: decision === 'selected',
      })
      setDecisionOpen(false)
      const updated = await refreshDetail(detailTarget.id)
      // Approved: straight on to PO generation.
      if (decision === 'selected') openConvert(updated)
    } catch (err) {
      setDecisionError(err instanceof ApiError ? err.message : 'Failed to record decision.')
    } finally {
      setDecisionBusy(false)
    }
  }

  const selectedResponse = useMemo(() => {
    if (!detailTarget?.selected_response_id) return undefined
    for (const invitation of detailTarget.invitations) {
      const found = invitation.responses.find((r) => r.id === detailTarget.selected_response_id)
      if (found) return { invitation, response: found }
    }
    return undefined
  }, [detailTarget])

  /** Prices pre-filled from the accepted quotation -- editable, never
   * locked. */
  function openConvert(rfq: Rfq | null = detailTarget) {
    if (!rfq) return
    const approved = rfq.invitations.flatMap((i) => i.responses).find((r) => r.id === rfq.selected_response_id)
    const quoted = new Map(approved?.lines.map((l) => [l.rfq_line_id, l.unit_price]) ?? [])
    const drafts: Record<number, ConvertLineDraft> = {}
    for (const line of rfq.lines) {
      const price = quoted.get(line.id)
      drafts[line.id] = { include: true, unit_price: price ? String(Number(price)) : '' }
    }
    setConvertLines(drafts)
    setConvertWarehouseId('')
    setConvertExpectedDate(rfq.required_delivery_date && rfq.required_delivery_date >= todayIso() ? rfq.required_delivery_date : '')
    setConvertPaymentTerms(approved?.payment_terms ?? '')
    setConvertSupplierRef(approved?.supplier_quotation_number ?? '')
    setConvertNotes('')
    setConvertError(null)
    setConvertOpen(true)
  }

  async function submitConvert() {
    if (!detailTarget) return
    if (!convertWarehouseId) {
      setConvertError('Select the delivery location.')
      return
    }
    if (!convertExpectedDate || convertExpectedDate < todayIso()) {
      setConvertError('Enter an expected delivery date (today or later).')
      return
    }
    if (!convertPaymentTerms.trim()) {
      setConvertError('Enter the payment terms.')
      return
    }
    const included = detailTarget.lines.filter((line) => convertLines[line.id]?.include)
    if (included.length === 0) {
      setConvertError('Include at least one item in the purchase order.')
      return
    }
    const lines = included.map((line) => ({ rfq_line_id: line.id, unit_price: convertLines[line.id].unit_price.trim() }))
    if (lines.some((l) => !isPositiveDecimal(l.unit_price))) {
      setConvertError('Enter a positive unit price for every included item.')
      return
    }
    setConvertBusy(true)
    setConvertError(null)
    try {
      const { data } = await apiClient.post<Rfq>(`/api/rfqs/${detailTarget.id}/convert-to-po`, {
        warehouse_id: Number(convertWarehouseId),
        expected_delivery_date: convertExpectedDate,
        payment_terms: convertPaymentTerms.trim(),
        supplier_reference: convertSupplierRef.trim() || null,
        notes: convertNotes.trim() || null,
        lines,
      })
      setConvertOpen(false)
      setDetailTarget(null)
      table.refetch()
      openPurchaseOrder(data.purchase_order_id)
    } catch (err) {
      setConvertError(err instanceof ApiError ? err.message : 'Failed to create purchase order.')
    } finally {
      setConvertBusy(false)
    }
  }

  function suppliersSummary(rfq: Rfq): string {
    const invited = rfq.invitations.length
    const quoted = rfq.invitations.filter((i) => i.responses.length > 0).length
    return quoted > 0 ? `${quoted} of ${invited} quoted` : `${invited} invited`
  }

  const columns: DataTableColumn<Rfq>[] = [
    { key: 'rfq_number', label: 'RFQ Number', render: (rfq) => (rfq.revision_number > 1 ? `${rfq.rfq_number} Rev ${rfq.revision_number}` : rfq.rfq_number) },
    { key: 'rfq_date', label: 'Date', hideBelow: 'sm', render: (rfq) => formatDate(rfq.rfq_date) },
    { key: 'required', label: 'Required By', hideBelow: 'md', render: (rfq) => formatDate(rfq.required_delivery_date) },
    {
      key: 'priority',
      label: 'Priority',
      render: (rfq) => (rfq.priority === 'urgent' ? <Badge tone="danger">Urgent</Badge> : <Badge tone="neutral">Normal</Badge>),
    },
    { key: 'suppliers', label: 'Suppliers', hideBelow: 'md', render: suppliersSummary },
    { key: 'status', label: 'Status', render: (rfq) => <Badge tone={STATUS_TONES[rfq.status]}>{STATUS_LABELS[rfq.status]}</Badge> },
    {
      key: 'actions',
      label: '',
      alwaysVisible: true,
      align: 'right' as const,
      render: (rfq: Rfq) => {
        const options: ActionMenuOption[] = [{ key: 'view', label: 'View', onSelect: () => openDetail(rfq) }]
        if (canManage) {
          if (rfq.status === 'draft') options.push({ key: 'edit', label: 'Edit / Submit...', onSelect: () => openForm(rfq) })
          if (rfq.status === 'issued' && !hasQuotes(rfq)) options.push({ key: 'revise', label: 'Revise...', onSelect: () => openForm(rfq) })
          if (rfq.status === 'converted' && rfq.purchase_order_id)
            options.push({ key: 'po', label: 'View Purchase Order', onSelect: () => openPurchaseOrder(rfq.purchase_order_id) })
          if (['draft', 'issued', 'response_received', 'selected'].includes(rfq.status))
            options.push({ key: 'cancel', label: 'Cancel', danger: true, onSelect: () => openCancel(rfq) })
        }
        return <ActionMenu label={`Actions for ${rfq.rfq_number}`} options={options} />
      },
    },
  ]

  const isOpenForQuotes = detailTarget?.status === 'issued' || detailTarget?.status === 'response_received'
  const quotedCount = detailTarget?.invitations.filter((i) => i.responses.length > 0).length ?? 0

  return (
    <div className="space-y-6">
      <div hidden={viewId !== null} className="space-y-6">
        <PageHeader
          title="RFQs"
          subtitle="Request for Quotation → Supplier Quotes → Accept / Reject → Purchase Order."
          actions={canManage ? <Button onClick={() => openForm(null)}>New RFQ</Button> : undefined}
        />

        <Alert variant="danger">{pageError}</Alert>

        <FilterBar>
          <TextField label="Search" placeholder="Search by RFQ number..." value={searchInput} onChange={(e) => setSearchInput(e.target.value)} />
          <SelectField label="Priority" value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value)}>
            <option value="">All</option>
            <option value="urgent">Urgent</option>
            <option value="normal">Normal</option>
          </SelectField>
        </FilterBar>

        <DataTable
          columns={columns}
          rows={table.rows}
          rowKey={(rfq) => rfq.id}
          loading={table.loading}
          error={table.error}
          sort={table.sort}
          onSortChange={table.setSort}
          page={table.page}
          totalPages={table.totalPages}
          total={table.total}
          onPageChange={table.setPage}
          pageSize={table.pageSize}
          onPageSizeChange={table.setPageSize}
          emptyTitle={debouncedSearch || priorityFilter ? 'No matching RFQs' : 'No RFQs yet'}
          emptyMessage={
            debouncedSearch || priorityFilter
              ? 'Try a different search or filter.'
              : canManage
                ? 'Create the first RFQ with the New RFQ button above.'
                : 'No RFQs have been created yet.'
          }
        />
      </div>


      {viewId !== null && (
        <section aria-label={detailTarget ? `RFQ ${detailTarget.rfq_number}` : 'RFQ'} className="space-y-6">
          <PageHeader
            title={detailTarget ? `RFQ ${detailTarget.rfq_number}${detailTarget.revision_number > 0 ? ` — Rev ${detailTarget.revision_number}` : ''}` : 'RFQ'}
          />
          {!detailTarget ? (
            <div className="flex flex-col gap-4">
              {viewLoading ? <Spinner /> : <Alert variant="danger">{detailError}</Alert>}
              <div>
                <Button variant="secondary" onClick={closeDetail}>Back to RFQs</Button>
              </div>
            </div>
          ) : (
            <>
              <div className="flex flex-col gap-4">
                <Alert variant="danger">{detailError}</Alert>
                <Alert variant="success">{detailNotice}</Alert>

                <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                  <div><span className="text-gold-100/50">RFQ Date: </span>{formatDate(detailTarget.rfq_date)}</div>
                  <div><span className="text-gold-100/50">Required By: </span>{formatDate(detailTarget.required_delivery_date)}</div>
                  <div><span className="text-gold-100/50">Requested By: </span>{detailTarget.requested_by_name ?? '—'}</div>
                  <div>
                    <span className="text-gold-100/50">Priority: </span>
                    {detailTarget.priority === 'urgent' ? <Badge tone="danger">Urgent</Badge> : 'Normal'}
                  </div>
                  <div><span className="text-gold-100/50">Status: </span><Badge tone={STATUS_TONES[detailTarget.status]}>{STATUS_LABELS[detailTarget.status]}</Badge></div>
                  {detailTarget.notes && <div className="col-span-2"><span className="text-gold-100/50">Notes: </span>{detailTarget.notes}</div>}
                  {detailTarget.cancel_reason && <div className="col-span-2"><span className="text-gold-100/50">Cancel Reason: </span>{detailTarget.cancel_reason}</div>}
                  {detailTarget.decided_at && (
                    <div className="col-span-2">
                      <span className="text-gold-100/50">Decision: </span>
                      {selectedResponse ? `Approved ${supplierName(selectedResponse.invitation.supplier_id)}` : 'Rejected'} on{' '}
                      {formatKuwaitTime(detailTarget.decided_at)}
                      {detailTarget.decision_note ? ` — ${detailTarget.decision_note}` : ''}
                    </div>
                  )}
                </div>

                {detailTarget.acceptance_files.length > 0 && (
                  <div>
                    <h3 className="mb-2 text-xs uppercase tracking-wide text-gold-100/50">Supplier Document (Approval)</h3>
                    <div className="flex flex-wrap gap-2">
                      {detailTarget.acceptance_files.map((file) => (
                        <button key={file.id} type="button" onClick={() => downloadFile(file)} className="rounded border border-ink-700 px-2 py-1 text-xs hover:border-gold-400">
                          {file.original_filename} ({formatBytes(file.size_bytes)})
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {quotedCount >= 2 && (
                  <div>
                    <h3 className="mb-2 text-xs uppercase tracking-wide text-gold-100/50">Comparison (latest quote per supplier)</h3>
                    <ComparisonTable rfq={detailTarget} materialName={materialName} unitCode={unitCode} supplierName={supplierName} />
                  </div>
                )}

                <div>
                  <h3 className="mb-2 text-xs uppercase tracking-wide text-gold-100/50">Items</h3>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                        <th className="py-2 pr-3">Product / Material</th>
                        <th className="py-2 pr-3">Quantity</th>
                        <th className="py-2 pr-3">UOM</th>
                        <th className="py-2 pr-3">Specification / Remarks</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detailTarget.lines.map((line) => (
                        <tr key={line.id} className="border-t border-ink-700">
                          <td className="py-2 pr-3">{materialName(line.raw_material_id)}</td>
                          <td className="py-2 pr-3">{formatNumber(line.quantity)}</td>
                          <td className="py-2 pr-3">{unitCode(line.unit_of_measure_id)}</td>
                          <td className="py-2 pr-3">{line.remarks ?? '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div>
                  <h3 className="mb-2 text-xs uppercase tracking-wide text-gold-100/50">Suppliers</h3>
                  <div className="flex flex-col gap-3">
                    {detailTarget.invitations.map((invitation) => (
                      <div key={invitation.id} className="rounded-md border border-ink-700 p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <span className="font-medium">{supplierName(invitation.supplier_id)}</span>
                            {detailTarget.status !== 'draft' && (
                              <Badge tone={INVITATION_TONES[invitation.status]}>{INVITATION_LABELS[invitation.status]}</Badge>
                            )}
                            {invitation.last_emailed_at && (
                              <span className="text-xs text-gold-100/50">Emailed {formatKuwaitTime(invitation.last_emailed_at)}</span>
                            )}
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {invitation.pdf_file && (
                              <Button variant="secondary" onClick={() => downloadFile(invitation.pdf_file!)}>Download PDF</Button>
                            )}
                            {canManage && invitation.pdf_file && isOpenForQuotes && (
                              <Button variant="secondary" onClick={() => emailInvitation(invitation)} isLoading={emailBusy === invitation.id}>Email</Button>
                            )}
                            {canManage && isOpenForQuotes && (
                              <Button variant="secondary" onClick={() => openCapture(invitation)}>
                                {invitation.responses.length > 0 ? 'Capture Revised Quote...' : 'Capture Quote...'}
                              </Button>
                            )}
                            {canManage && isOpenForQuotes && invitation.status === 'sent' && (
                              <Button variant="secondary" onClick={() => declineInvitation(invitation)}>Mark Declined</Button>
                            )}
                          </div>
                        </div>

                        {invitation.responses.map((response) => (
                          <div
                            key={response.id}
                            className={`mt-3 rounded-md border p-3 ${detailTarget.selected_response_id === response.id ? 'border-gold-400' : 'border-ink-700'}`}
                          >
                            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                              <span>
                                Received {formatKuwaitTime(response.response_received_at)}
                                {response.supplier_quotation_number && ` · Ref ${response.supplier_quotation_number}`}
                                {response.valid_until && ` · Valid until ${formatDate(response.valid_until)}`}
                              </span>
                              {detailTarget.selected_response_id === response.id && <Badge tone="gold">Approved</Badge>}
                            </div>
                            {(response.payment_terms || response.delivery_terms || response.freight_terms) && (
                              <p className="mt-1 text-xs text-gold-100/60">
                                {[
                                  response.payment_terms && `Payment: ${response.payment_terms}`,
                                  response.delivery_terms && `Delivery: ${response.delivery_terms}`,
                                  response.freight_terms && `Freight: ${response.freight_terms}`,
                                ]
                                  .filter(Boolean)
                                  .join(' · ')}
                              </p>
                            )}
                            <table className="mt-2 w-full text-sm">
                              <tbody>
                                {response.lines.map((quoted) => {
                                  const rfqLine = detailTarget.lines.find((l) => l.id === quoted.rfq_line_id)
                                  return (
                                    <tr key={quoted.id} className="border-t border-ink-700">
                                      <td className="py-1 pr-3">{rfqLine ? materialName(rfqLine.raw_material_id) : `Item #${quoted.rfq_line_id}`}</td>
                                      <td className="py-1 pr-3">{rfqLine ? `${formatNumber(rfqLine.quantity)} ${unitCode(rfqLine.unit_of_measure_id)}` : ''}</td>
                                      <td className="py-1 pr-3">{formatPrice(quoted.unit_price)}</td>
                                      <td className="py-1 pr-3">{quoted.delivery_days !== null ? `${quoted.delivery_days} days` : '—'}</td>
                                      <td className="py-1 pr-3 text-gold-100/60">{quoted.remarks ?? ''}</td>
                                    </tr>
                                  )
                                })}
                              </tbody>
                            </table>
                            {response.note && <p className="mt-1 text-sm text-gold-100/80">{response.note}</p>}
                            {response.files.length > 0 && (
                              <div className="mt-2 flex flex-wrap gap-2">
                                {response.files.map((file) => (
                                  <button key={file.id} type="button" onClick={() => downloadFile(file)} className="rounded border border-ink-700 px-2 py-1 text-xs hover:border-gold-400">
                                    {file.original_filename} ({formatBytes(file.size_bytes)})
                                  </button>
                                ))}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap justify-end gap-2 border-t border-ink-700 pt-4">
              {canManage && detailTarget?.status === 'draft' && <Button onClick={() => openForm(detailTarget)}>Edit / Submit...</Button>}
              {canManage && detailTarget?.status === 'issued' && !hasQuotes(detailTarget) && (
                <Button variant="secondary" onClick={() => openForm(detailTarget)}>Revise...</Button>
              )}
              {canManage && detailTarget?.status === 'response_received' && <Button onClick={openDecision}>Approve / Reject...</Button>}
              {canManage && detailTarget?.status === 'selected' && <Button onClick={() => openConvert()}>Generate Purchase Order...</Button>}
              {detailTarget?.status === 'converted' && detailTarget.purchase_order_id && (
                <Button variant="secondary" onClick={() => openPurchaseOrder(detailTarget.purchase_order_id)}>View Purchase Order</Button>
              )}
              <Button variant="secondary" onClick={closeDetail}>Back to RFQs</Button>
              </div>
            </>
          )}
        </section>
      )}

      <Modal
        open={!!captureInvitation}
        title={captureInvitation ? `Capture Quotation — ${supplierName(captureInvitation.supplier_id)}` : ''}
        size="wide"
        onClose={() => setCaptureInvitation(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setCaptureInvitation(null)}>Cancel</Button>
            <Button onClick={captureForm.handleSubmit(onCaptureSubmit)} isLoading={captureForm.formState.isSubmitting}>Save Quotation</Button>
          </>
        }
      >
        {detailTarget && (
          <form className="flex flex-col gap-4">
            <Alert variant="danger">{captureError}</Alert>
            <p className="text-sm text-gold-100/70">Enter the quoted unit price per item. Leave an item blank if the supplier did not quote it.</p>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                  <th className="py-2 pr-3">Product / Material</th>
                  <th className="py-2 pr-3">Qty</th>
                  <th className="py-2 pr-3">Unit Price</th>
                  <th className="py-2 pr-3">Delivery Days</th>
                  <th className="py-2 pr-3">Remarks</th>
                </tr>
              </thead>
              <tbody>
                {detailTarget.lines.map((line) => (
                  <tr key={line.id} className="border-t border-ink-700">
                    <td className="py-2 pr-3">{materialName(line.raw_material_id)}</td>
                    <td className="py-2 pr-3">{formatNumber(line.quantity)} {unitCode(line.unit_of_measure_id)}</td>
                    <td className="py-2 pr-3">
                      <input
                        type="number"
                        min="0"
                        step="0.0001"
                        aria-label={`Unit price for ${materialName(line.raw_material_id)}`}
                        className="w-28 rounded border border-ink-700 bg-ink-900 px-2 py-1 text-sm"
                        value={captureLines[line.id]?.unit_price ?? ''}
                        onChange={(e) => updateCaptureLine(line.id, { unit_price: e.target.value })}
                      />
                    </td>
                    <td className="py-2 pr-3">
                      <input
                        type="number"
                        min="0"
                        step="1"
                        aria-label={`Delivery days for ${materialName(line.raw_material_id)}`}
                        className="w-20 rounded border border-ink-700 bg-ink-900 px-2 py-1 text-sm"
                        value={captureLines[line.id]?.delivery_days ?? ''}
                        onChange={(e) => updateCaptureLine(line.id, { delivery_days: e.target.value })}
                      />
                    </td>
                    <td className="py-2 pr-3">
                      <input
                        type="text"
                        aria-label={`Remarks for ${materialName(line.raw_material_id)}`}
                        className="w-full rounded border border-ink-700 bg-ink-900 px-2 py-1 text-sm"
                        value={captureLines[line.id]?.remarks ?? ''}
                        onChange={(e) => updateCaptureLine(line.id, { remarks: e.target.value })}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="grid gap-4 sm:grid-cols-3">
              <TextField label="Supplier Quotation No." {...captureForm.register('supplier_quotation_number')} />
              <DateField label="Quotation Date" {...captureForm.register('quotation_date')} />
              <DateField label="Valid Until" {...captureForm.register('valid_until')} />
              <TextField label="Payment Terms" placeholder="e.g. 30 days" {...captureForm.register('payment_terms')} />
              <TextField label="Delivery Terms" placeholder="e.g. 5 days" {...captureForm.register('delivery_terms')} />
              <TextField label="Freight Terms" placeholder="e.g. included" {...captureForm.register('freight_terms')} />
            </div>
            <FileUploadField label="Attach Supplier Quotation (optional)" multiple accept={ACCEPTANCE_TYPES} value={captureFiles} onChange={setCaptureFiles} />
            <TextareaField label="Remarks" {...captureForm.register('note')} />
          </form>
        )}
      </Modal>

      <Modal
        open={decisionOpen}
        title="Approve or Reject"
        size="wide"
        onClose={() => setDecisionOpen(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setDecisionOpen(false)}>Cancel</Button>
            {decision === 'selected' && changedQuantities.length > 0 ? (
              <Button onClick={raiseNewRfq} isLoading={decisionBusy}>Raise New RFQ</Button>
            ) : (
              <Button variant={decision === 'rejected' ? 'danger' : undefined} onClick={submitDecision} isLoading={decisionBusy}>
                {decision === 'selected' ? 'Approve' : 'Reject RFQ'}
              </Button>
            )}
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <Alert variant="danger">{decisionError}</Alert>
          <SelectField label="Decision" required value={decision} onChange={(e) => setDecision(e.target.value as 'selected' | 'rejected')}>
            <option value="selected">Approve a supplier quotation</option>
            <option value="rejected">Reject — stop this RFQ</option>
          </SelectField>
          {decision === 'selected' ? (
            <>
              <SelectField label="Quotation" required value={decisionResponseId} onChange={(e) => setDecisionResponseId(e.target.value)}>
                <option value="">Select a quotation...</option>
                {detailTarget?.invitations
                  .filter((invitation) => invitation.responses.length > 0)
                  .map((invitation) => (
                    <optgroup key={invitation.id} label={supplierName(invitation.supplier_id)}>
                      {invitation.responses.map((response, index) => (
                        <option key={response.id} value={response.id}>
                          {index === invitation.responses.length - 1 ? 'Latest' : `Revision ${index + 1}`} —{' '}
                          {formatKuwaitTime(response.response_received_at)}
                          {response.supplier_quotation_number ? ` (Ref ${response.supplier_quotation_number})` : ''}
                        </option>
                      ))}
                    </optgroup>
                  ))}
              </SelectField>
              <div>
                <h3 className="mb-2 text-xs uppercase tracking-wide text-gold-100/50">Agreed Quantities</h3>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                      <th className="py-2 pr-3">Product / Material</th>
                      <th className="py-2 pr-3">Requested</th>
                      <th className="py-2 pr-3">Agreed (per supplier document)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detailTarget?.lines.map((line) => (
                      <tr key={line.id} className="border-t border-ink-700">
                        <td className="py-2 pr-3">{materialName(line.raw_material_id)}</td>
                        <td className="py-2 pr-3">{formatNumber(line.quantity)} {unitCode(line.unit_of_measure_id)}</td>
                        <td className="py-2 pr-3">
                          <input
                            type="number"
                            min="0"
                            step="any"
                            aria-label={`Agreed quantity for ${materialName(line.raw_material_id)}`}
                            className="w-28 rounded border border-ink-700 bg-ink-900 px-2 py-1 text-sm"
                            value={agreedQuantities[line.id] ?? ''}
                            onChange={(e) => setAgreedQuantities((prev) => ({ ...prev, [line.id]: e.target.value }))}
                          />{' '}
                          {unitCode(line.unit_of_measure_id)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {changedQuantities.length > 0 ? (
                <Alert variant="warning">
                  The agreed quantity differs from the request, so this RFQ can't be approved. Raise New RFQ cancels this one and
                  opens a new draft RFQ with the agreed quantities.
                </Alert>
              ) : (
                <FileUploadField
                  label="Document received from the supplier — PDF or image (required)"
                  multiple
                  accept={ACCEPTANCE_TYPES}
                  value={decisionFiles}
                  onChange={setDecisionFiles}
                />
              )}
            </>
          ) : (
            <p className="text-sm text-gold-100/70">Rejecting ends this RFQ. No purchase order can be created from it.</p>
          )}
          <TextareaField label="Note" value={decisionNote} onChange={(e) => setDecisionNote(e.target.value)} />
        </div>
      </Modal>

      <Modal
        open={convertOpen}
        title="Generate Purchase Order"
        size="wide"
        onClose={() => setConvertOpen(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConvertOpen(false)}>Later</Button>
            <Button onClick={submitConvert} isLoading={convertBusy}>Create Purchase Order</Button>
          </>
        }
      >
        {detailTarget && (
          <div className="flex flex-col gap-4">
            <Alert variant="danger">{convertError}</Alert>
            <p className="text-sm text-gold-100/70">
              Supplier{selectedResponse ? ` (${supplierName(selectedResponse.invitation.supplier_id)})` : ''}, items and quantities come from
              the approved RFQ ({detailTarget.rfq_number}). Prices and terms are pre-filled from the approved quotation and can be changed.
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              <SelectField label="Delivery Location" required value={convertWarehouseId} onChange={(e) => setConvertWarehouseId(e.target.value)}>
                <option value="">Select a warehouse...</option>
                {warehouses.filter((w) => w.is_active).map((w) => (
                  <option key={w.id} value={w.id}>{w.name}</option>
                ))}
              </SelectField>
              <DateField label="Expected Delivery Date" required min={todayIso()} value={convertExpectedDate} onChange={(e) => setConvertExpectedDate(e.target.value)} />
              <TextField label="Payment Terms" required placeholder="e.g. Advance, 30 days" value={convertPaymentTerms} onChange={(e) => setConvertPaymentTerms(e.target.value)} />
              <TextField label="Supplier Reference" value={convertSupplierRef} onChange={(e) => setConvertSupplierRef(e.target.value)} />
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                  <th className="py-2 pr-3">Include</th>
                  <th className="py-2 pr-3">Product / Material</th>
                  <th className="py-2 pr-3">Quantity</th>
                  <th className="py-2 pr-3">Unit Price</th>
                  <th className="py-2 pr-3 text-right">Total</th>
                </tr>
              </thead>
              <tbody>
                {detailTarget.lines.map((line) => {
                  const draft = convertLines[line.id] ?? { include: true, unit_price: '' }
                  const lineTotal = draft.include && isPositiveDecimal(draft.unit_price) ? Number(line.quantity) * Number(draft.unit_price) : null
                  return (
                    <tr key={line.id} className="border-t border-ink-700">
                      <td className="py-2 pr-3">
                        <input
                          type="checkbox"
                          aria-label={`Include ${materialName(line.raw_material_id)}`}
                          checked={draft.include}
                          onChange={(e) => setConvertLines((prev) => ({ ...prev, [line.id]: { ...draft, include: e.target.checked } }))}
                        />
                      </td>
                      <td className="py-2 pr-3">{materialName(line.raw_material_id)}</td>
                      <td className="py-2 pr-3">{formatNumber(line.quantity)} {unitCode(line.unit_of_measure_id)}</td>
                      <td className="py-2 pr-3">
                        <input
                          type="number"
                          min="0"
                          step="0.0001"
                          aria-label={`Unit price for ${materialName(line.raw_material_id)}`}
                          disabled={!draft.include}
                          className="w-28 rounded border border-ink-700 bg-ink-900 px-2 py-1 text-sm disabled:opacity-50"
                          value={draft.unit_price}
                          onChange={(e) => setConvertLines((prev) => ({ ...prev, [line.id]: { ...draft, unit_price: e.target.value } }))}
                        />
                      </td>
                      <td className="py-2 pr-3 text-right">{lineTotal === null ? '—' : formatPrice(String(lineTotal))}</td>
                    </tr>
                  )
                })}
                <tr className="border-t border-ink-600 font-semibold">
                  <td colSpan={4} className="py-2 pr-3 text-right">Total</td>
                  <td className="py-2 pr-3 text-right">
                    {formatPrice(
                      String(
                        detailTarget.lines.reduce((sum, line) => {
                          const draft = convertLines[line.id]
                          return draft?.include && isPositiveDecimal(draft.unit_price) ? sum + Number(line.quantity) * Number(draft.unit_price) : sum
                        }, 0),
                      ),
                    )}
                  </td>
                </tr>
              </tbody>
            </table>
            <TextareaField label="Notes" value={convertNotes} onChange={(e) => setConvertNotes(e.target.value)} />
          </div>
        )}
      </Modal>

      <Modal
        open={!!cancelTarget}
        title={`Cancel RFQ ${cancelTarget?.rfq_number ?? ''}`}
        onClose={() => setCancelTarget(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setCancelTarget(null)}>Keep RFQ</Button>
            <Button variant="danger" onClick={cancelForm.handleSubmit(onCancelSubmit)} isLoading={cancelForm.formState.isSubmitting}>Cancel RFQ</Button>
          </>
        }
      >
        <form className="flex flex-col gap-4">
          <Alert variant="danger">{cancelError}</Alert>
          <TextareaField label="Reason" required hint="Required to cancel an RFQ." {...cancelForm.register('cancel_reason')} error={cancelForm.formState.errors.cancel_reason?.message} />
        </form>
      </Modal>
    </div>
  )
}
