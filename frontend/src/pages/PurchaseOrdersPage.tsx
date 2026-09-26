import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { useLocation, useNavigate } from 'react-router-dom'
import { z } from 'zod'
import { ActionMenu, type ActionMenuOption } from '@/components/ui/ActionMenu'
import { Alert } from '@/components/ui/Alert'
import { Badge, type BadgeTone } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { DataTable, type DataTableColumn } from '@/components/ui/DataTable'
import { FilterBar } from '@/components/ui/FilterBar'
import { Modal } from '@/components/ui/Modal'
import { PageHeader } from '@/components/ui/PageHeader'
import type { SortState } from '@/components/ui/sort'
import { Spinner } from '@/components/ui/Spinner'
import { CheckboxField } from '@/components/forms/CheckboxField'
import { FileUploadField } from '@/components/forms/FileUploadField'
import { SelectField } from '@/components/forms/SelectField'
import { TextField } from '@/components/forms/TextField'
import { TextareaField } from '@/components/forms/TextareaField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { useAuth } from '@/lib/auth/AuthContext'
import { isAdminRole } from '@/lib/auth/roles'
import { formatKuwaitTime } from '@/lib/timezone'
import { formatDate } from '@/lib/format'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { useServerTable, type ServerTableResult } from '@/lib/useServerTable'

/** Mirrors backend/app/schemas/purchase_order.py. */
interface PurchaseOrderLine {
  id: number
  raw_material_id: number
  quantity: string
  unit_of_measure_id: number
  conversion_factor: string
  unit_price: string
  line_total: string
  required_by_date: string | null
  remarks: string | null
  received_quantity: string
  cancelled_quantity: string
}

interface PurchaseOrderRevisionLine {
  id: number
  raw_material_id: number
  quantity: string
  unit_of_measure_id: number | null
  unit_price: string
  line_total: string
  required_by_date: string | null
  remarks: string | null
}

interface PurchaseOrderReceiptLine {
  id: number
  purchase_order_line_id: number
  raw_material_id: number
  quantity: string
  remarks: string | null
}

type PurchaseOrderReceiptStatus = 'draft' | 'posted' | 'cancelled' | 'reversed'

interface PurchaseOrderReceipt {
  id: number
  receipt_number: string
  purchase_order_id: number
  warehouse_id: number
  receipt_date: string
  status: PurchaseOrderReceiptStatus
  supplier_delivery_reference: string | null
  notes: string | null
  posted_at: string | null
  reversed_at: string | null
  reversal_reason: string | null
  created_at: string
  received_by_name: string | null
  days_late: number
  lines: PurchaseOrderReceiptLine[]
  documents: PurchaseFile[]
}

interface PurchaseFile {
  id: number
  original_filename: string
  mime_type: string
  size_bytes: number
}

interface PurchaseOrderRevision {
  id: number
  revision_number: number
  order_date: string
  expected_delivery_date: string | null
  supplier_reference: string | null
  payment_terms: string | null
  notes: string | null
  total_amount: string
  issued_at: string
  issued_by_user_id: number | null
  lines: PurchaseOrderRevisionLine[]
  pdf_file: PurchaseFile | null
}

interface PurchaseOrderPayment {
  id: number
  payment_number: string
  payment_date: string
  amount: string
  payment_method: string | null
  reference_number: string | null
  notes: string | null
  is_final: boolean
  status: 'recorded' | 'cancelled'
  cancelled_at: string | null
  cancellation_reason: string | null
  created_by_user_id: number | null
  created_at: string
  files: PurchaseFile[]
}

type PurchaseOrderStatus =
  | 'draft'
  | 'pending_approval'
  | 'approved'
  | 'sent'
  | 'partially_received'
  | 'reconciliation_required'
  | 'received'
  | 'payment_reconciliation'
  | 'closed'
  | 'cancelled'

interface PurchaseOrderReconciliation {
  id: number
  kind: 'receipt' | 'payment'
  status: 'open' | 'resolved'
  discrepancy: string
  resolution: string | null
  resolution_note: string | null
  created_at: string
  resolved_at: string | null
  resolved_by_name: string | null
}

interface PurchaseOrderCommunication {
  id: number
  kind: 'po_sent' | 'follow_up' | 'note'
  recipient: string | null
  subject: string | null
  message: string | null
  status: 'sent' | 'failed' | 'recorded'
  error: string | null
  created_at: string
  sent_by_name: string | null
  files: PurchaseFile[]
}
type PaymentStatus = 'unpaid' | 'partially_paid' | 'paid'

interface PurchaseOrder {
  id: number
  organisation_id: number
  po_number: string
  supplier_id: number
  warehouse_id: number
  rfq_id: number | null
  rfq_number: string | null
  rfq_response_id: number | null
  status: PurchaseOrderStatus
  revision_number: number
  order_date: string
  expected_delivery_date: string | null
  /** expected_delivery_date has passed and the PO isn't fully received/closed/cancelled. */
  is_overdue: boolean
  days_overdue: number
  supplier_reference: string | null
  payment_terms: string | null
  currency: string
  delivery_instructions: string | null
  notes: string | null
  cancel_reason: string | null
  created_at: string
  created_by_name: string | null
  approved_at: string | null
  approved_by_name: string | null
  sent_at: string | null
  sent_by_name: string | null
  cancelled_at: string | null
  cancelled_by_name: string | null
  total_amount: string
  amount_adjustment: string
  final_amount: string
  paid_amount: string
  outstanding_amount: string
  /** What's owed back on a cancelled order with a payment already made -- '0.0000' otherwise. */
  refundable_amount: string
  payment_status: PaymentStatus
  lines: PurchaseOrderLine[]
  revisions: PurchaseOrderRevision[]
  documents: PurchaseFile[]
  payments: PurchaseOrderPayment[]
  receipts: PurchaseOrderReceipt[]
  reconciliations: PurchaseOrderReconciliation[]
  communications: PurchaseOrderCommunication[]
}

interface LookupOption {
  id: number
  name: string
  code: string | null
  is_active: boolean
  reference_cost?: string | null
  unit_of_measure_id?: number
}

interface PaginatedResponse<T> {
  data: T[]
  pagination: { page: number; page_size: number; total: number; total_pages: number }
}

interface PurchaseOrdersFilters {
  search: string
  overdue: boolean
}

const STATUS_LABELS: Record<PurchaseOrderStatus, string> = {
  draft: 'Draft',
  pending_approval: 'Pending Approval',
  approved: 'Approved',
  sent: 'Sent — Awaiting Delivery',
  partially_received: 'Partially Received',
  reconciliation_required: 'Reconciliation Required',
  received: 'Received — Awaiting Payment',
  payment_reconciliation: 'Payment Reconciliation',
  closed: 'Closed',
  cancelled: 'Cancelled',
}

const STATUS_TONES: Record<PurchaseOrderStatus, BadgeTone> = {
  draft: 'info',
  pending_approval: 'warning',
  approved: 'gold',
  sent: 'gold',
  partially_received: 'warning',
  reconciliation_required: 'danger',
  received: 'info',
  payment_reconciliation: 'danger',
  closed: 'success',
  cancelled: 'danger',
}

const RESOLUTIONS: Record<PurchaseOrderReconciliation['kind'], { value: string; label: string }[]> = {
  receipt: [
    { value: 'keep_pending', label: 'Await balance — remaining quantity still expected (incl. replacement requested)' },
    { value: 'accept_received_quantity', label: 'Accept received quantity — amount owed stays as ordered' },
    { value: 'cancel_remaining', label: 'Cancel balance — amount owed reduced to match what was received' },
  ],
  payment: [
    { value: 'accept_paid_amount', label: 'Accept the paid amount as the final amount' },
    { value: 'correct_payment', label: 'Finance to correct the payment' },
  ],
}

const RESOLUTION_LABELS: Record<string, string> = {
  keep_pending: 'Remaining kept pending',
  accept_received_quantity: 'Received quantity accepted (amount owed unchanged)',
  cancel_remaining: 'Balance cancelled (amount owed reduced)',
  accept_paid_amount: 'Paid amount accepted',
  correct_payment: 'Payment to be corrected',
}

const COMMUNICATION_LABELS: Record<PurchaseOrderCommunication['kind'], string> = {
  po_sent: 'PO sent to supplier',
  follow_up: 'Follow-up email',
  note: 'Supplier reply / note',
}

const PAYMENT_STATUS_LABELS: Record<PaymentStatus, string> = { unpaid: 'Pending', partially_paid: 'Partially Paid', paid: 'Paid' }
const PAYMENT_STATUS_TONES: Record<PaymentStatus, BadgeTone> = { unpaid: 'neutral', partially_paid: 'warning', paid: 'success' }

const CANCELLABLE: PurchaseOrderStatus[] = ['draft', 'pending_approval', 'approved', 'sent', 'partially_received']

function stamp(at: string | null, by: string | null): string | null {
  if (!at) return null
  return `${formatKuwaitTime(at)}${by ? ` by ${by}` : ''}`
}

const RECEIPT_STATUS_LABELS: Record<PurchaseOrderReceiptStatus, string> = {
  draft: 'Draft',
  posted: 'Posted',
  cancelled: 'Cancelled',
  reversed: 'Reversed',
}

const RECEIPT_STATUS_TONES: Record<PurchaseOrderReceiptStatus, BadgeTone> = {
  draft: 'info',
  posted: 'success',
  cancelled: 'danger',
  reversed: 'warning',
}


const cancelSchema = z.object({
  cancel_reason: z.string().min(1, 'A reason is required to cancel this purchase order.'),
})

type CancelFormValues = z.infer<typeof cancelSchema>

const cancelPaymentSchema = z.object({
  reason: z.string().min(1, 'A reason is required to cancel this payment.'),
})

type CancelPaymentFormValues = z.infer<typeof cancelPaymentSchema>

const reverseReceiptSchema = z.object({
  reason: z.string().min(1, 'A reason is required to reverse a goods receipt.'),
})

type ReverseReceiptFormValues = z.infer<typeof reverseReceiptSchema>

async function fetchPurchaseOrders({
  page,
  pageSize,
  sort,
  filters,
}: {
  page: number
  pageSize: number
  sort: SortState | null
  filters: PurchaseOrdersFilters
}): Promise<ServerTableResult<PurchaseOrder>> {
  const { data } = await apiClient.get<PaginatedResponse<PurchaseOrder>>('/api/purchase-orders', {
    params: {
      page,
      page_size: pageSize,
      sort_by: sort?.field,
      sort_direction: sort?.direction,
      q: filters.search || undefined,
      overdue: filters.overdue || undefined,
    },
  })
  return { rows: data.data, total: data.pagination.total }
}

function lineRemaining(line: PurchaseOrderLine): number {
  return Number(line.quantity) - Number(line.cancelled_quantity) - Number(line.received_quantity)
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(0)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

/** Purchase Order: Draft -> Pending Approval -> Approved -> Sent ->
 * Received (backend/app/api/purchase_orders.py,
 * docs/modules/purchase_orders.md). One flat list plus a single
 * "Purchase Order" Modal per row that carries the whole lifecycle --
 * header, items (editable while draft), approved revisions (each with its
 * immutable PDF), payments (status, record/cancel), and inline receive
 * controls once sent -- reusing
 * BomsPage.tsx's list-plus-child-relationship-Modal pattern instead of a
 * separate detail route. Every row's ActionMenu exposes exactly the next
 * valid action for that PO's current status -- no dead ends. */
export function PurchaseOrdersPage() {
  const { user: currentUser } = useAuth()
  const canManage = isAdminRole(currentUser?.role)

  const [suppliers, setSuppliers] = useState<LookupOption[]>([])
  const [materials, setMaterials] = useState<LookupOption[]>([])
  const [units, setUnits] = useState<LookupOption[]>([])
  const [pageError, setPageError] = useState<string | undefined>(undefined)
  const [notice, setNotice] = useState<string | null>(null)

  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 300)
  const [overdueFilter, setOverdueFilter] = useState(false)

  const [detailTarget, setDetailTarget] = useState<PurchaseOrder | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [expandedRevision, setExpandedRevision] = useState<number | null>(null)


  const [actionBusy, setActionBusy] = useState<string | null>(null)

  const [cancelTarget, setCancelTarget] = useState<PurchaseOrder | null>(null)
  const [cancelError, setCancelError] = useState<string | null>(null)


  const [cancelPaymentTarget, setCancelPaymentTarget] = useState<PurchaseOrderPayment | null>(null)
  const [cancelPaymentError, setCancelPaymentError] = useState<string | null>(null)

  const [resolveNotes, setResolveNotes] = useState<Record<number, string>>({})
  const [resolveChoice, setResolveChoice] = useState<Record<number, string>>({})
  const [followUpMessage, setFollowUpMessage] = useState('')
  const [followUpSubject, setFollowUpSubject] = useState('')
  const [followUpAttachPdf, setFollowUpAttachPdf] = useState(false)
  const [followUpFiles, setFollowUpFiles] = useState<File[]>([])
  const [followUpError, setFollowUpError] = useState<string | null>(null)

  const [expandedReceipt, setExpandedReceipt] = useState<number | null>(null)
  const [postReceiptBusy, setPostReceiptBusy] = useState(false)
  const [postReceiptError, setPostReceiptError] = useState<string | null>(null)

  const [cancelReceiptTarget, setCancelReceiptTarget] = useState<PurchaseOrderReceipt | null>(null)
  const [cancelReceiptBusy, setCancelReceiptBusy] = useState(false)
  const [cancelReceiptError, setCancelReceiptError] = useState<string | null>(null)

  const [reverseReceiptTarget, setReverseReceiptTarget] = useState<PurchaseOrderReceipt | null>(null)
  const [reverseReceiptError, setReverseReceiptError] = useState<string | null>(null)

  const cancelForm = useForm<CancelFormValues>({ resolver: zodResolver(cancelSchema), defaultValues: { cancel_reason: '' } })
  const cancelPaymentForm = useForm<CancelPaymentFormValues>({
    resolver: zodResolver(cancelPaymentSchema),
    defaultValues: { reason: '' },
  })
  const reverseReceiptForm = useForm<ReverseReceiptFormValues>({
    resolver: zodResolver(reverseReceiptSchema),
    defaultValues: { reason: '' },
  })

  const table = useServerTable<PurchaseOrder, PurchaseOrdersFilters>({
    fetcher: fetchPurchaseOrders,
    pageSize: 20,
    initialFilters: { search: '', overdue: false },
  })

  const isFirstSearchRender = useRef(true)
  useEffect(() => {
    if (isFirstSearchRender.current) {
      isFirstSearchRender.current = false
      return
    }
    table.setFilters({ search: debouncedSearch, overdue: overdueFilter })
  }, [debouncedSearch, overdueFilter])

  const suppliersById = useMemo(() => new Map(suppliers.map((s) => [s.id, s])), [suppliers])
  const materialsById = useMemo(() => new Map(materials.map((m) => [m.id, m])), [materials])
  const unitsById = useMemo(() => new Map(units.map((u) => [u.id, u])), [units])
  const unitCode = (id: number | null) => (id ? unitsById.get(id)?.code ?? '' : '')

  const loadLookups = useCallback(async () => {
    try {
      const [suppliersResponse, materialsResponse, unitsResponse] = await Promise.all([
        apiClient.get<PaginatedResponse<LookupOption>>('/api/suppliers', { params: { page_size: 200 } }),
        apiClient.get<PaginatedResponse<LookupOption>>('/api/raw-materials', { params: { page_size: 200 } }),
        apiClient.get<PaginatedResponse<LookupOption>>('/api/units-of-measure', { params: { page_size: 200 } }),
      ])
      setSuppliers(suppliersResponse.data.data)
      setMaterials(materialsResponse.data.data)
      setUnits(unitsResponse.data.data)
    } catch (err) {
      setPageError(err instanceof ApiError ? err.message : 'Failed to load suppliers and raw materials.')
    }
  }, [])

  useEffect(() => {
    void loadLookups()
  }, [loadLookups])

  // Viewing a PO is its own page: /purchase-orders/:id. Opening it from
  // the list passes the row along; a direct visit, refresh, or arrival
  // from the PO form or an RFQ's PO generation loads it.
  const location = useLocation()
  const navigate = useNavigate()
  const viewMatch = /^\/purchase-orders\/(\d+)$/.exec(location.pathname)
  const viewId = viewMatch ? Number(viewMatch[1]) : null
  const navState = location.state as { record?: PurchaseOrder; notice?: string } | null
  const [viewLoading, setViewLoading] = useState(false)
  useEffect(() => {
    if (viewId === null) {
      setDetailTarget(null)
      return
    }
    resetDetail()
    setNotice(navState?.notice ?? null)
    if (navState?.record && navState.record.id === viewId) {
      setDetailTarget(navState.record)
      return
    }
    let cancelled = false
    setDetailTarget(null)
    setViewLoading(true)
    apiClient
      .get<PurchaseOrder>(`/api/purchase-orders/${viewId}`)
      .then(({ data }) => {
        if (!cancelled) setDetailTarget(data)
      })
      .catch((err) => {
        if (!cancelled) setDetailError(err instanceof ApiError ? err.message : 'Failed to open the purchase order.')
      })
      .finally(() => {
        if (!cancelled) setViewLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [viewId])

  function openCreate() {
    navigate('/purchase-orders/new')
  }

  const refreshDetail = useCallback(
    async (id: number) => {
      const { data } = await apiClient.get<PurchaseOrder>(`/api/purchase-orders/${id}`)
      setDetailTarget(data)
      table.refetch()
      return data
    },
    [table],
  )

  function openDetail(po: PurchaseOrder) {
    navigate(`/purchase-orders/${po.id}`, { state: { record: po } })
  }

  function resetDetail() {
    setDetailError(null)
    setResolveNotes({})
    setResolveChoice({})
    setFollowUpMessage('')
    setFollowUpSubject('')
    setFollowUpAttachPdf(false)
    setFollowUpFiles([])
    setFollowUpError(null)
    setExpandedRevision(null)
    setExpandedReceipt(null)
    setPostReceiptError(null)
  }

  function closeDetail() {
    navigate('/purchase-orders')
  }

  /** One lifecycle step: submit / approve / send back / revise / send. */
  async function runAction(key: string, request: () => Promise<unknown>, failure: string) {
    if (!detailTarget) return
    setActionBusy(key)
    setDetailError(null)
    try {
      await request()
      await refreshDetail(detailTarget.id)
    } catch (err) {
      setDetailError(err instanceof ApiError ? err.message : failure)
    } finally {
      setActionBusy(null)
    }
  }

  const poUrl = (suffix: string) => `/api/purchase-orders/${detailTarget?.id}${suffix}`
  const submitForApproval = () => runAction('submit', () => apiClient.post(poUrl('/submit')), 'Failed to submit for approval.')
  const approvePurchaseOrder = () => runAction('approve', () => apiClient.post(poUrl('/approve')), 'Failed to approve purchase order.')
  const backToDraft = () =>
    runAction('draft', () => apiClient.patch(poUrl('/status'), { status: 'draft' }), 'Failed to return purchase order to draft.')
  const emailPurchaseOrder = () => runAction('email', () => apiClient.post(poUrl('/send'), { email: true }), 'Failed to send purchase order.')
  const markSent = () => runAction('mark-sent', () => apiClient.post(poUrl('/send'), { email: false }), 'Failed to mark as sent.')

  function openCancel(po: PurchaseOrder) {
    setCancelTarget(po)
    cancelForm.reset({ cancel_reason: '' })
    setCancelError(null)
  }

  const onCancelSubmit = useCallback(
    async (values: CancelFormValues) => {
      if (!cancelTarget) return
      setCancelError(null)
      try {
        await apiClient.patch(`/api/purchase-orders/${cancelTarget.id}/status`, {
          status: 'cancelled',
          cancel_reason: values.cancel_reason,
        })
        setCancelTarget(null)
        table.refetch()
        if (detailTarget?.id === cancelTarget.id) await refreshDetail(cancelTarget.id)
      } catch (err) {
        setCancelError(err instanceof ApiError ? err.message : 'Failed to cancel purchase order.')
      }
    },
    [cancelTarget, detailTarget, refreshDetail, table],
  )

  function openCancelPayment(payment: PurchaseOrderPayment) {
    setCancelPaymentTarget(payment)
    cancelPaymentForm.reset({ reason: '' })
    setCancelPaymentError(null)
  }

  const onCancelPaymentSubmit = useCallback(
    async (values: CancelPaymentFormValues) => {
      if (!detailTarget || !cancelPaymentTarget) return
      setCancelPaymentError(null)
      try {
        await apiClient.post(`/api/purchase-orders/${detailTarget.id}/payments/${cancelPaymentTarget.id}/cancel`, {
          reason: values.reason,
        })
        setCancelPaymentTarget(null)
        await refreshDetail(detailTarget.id)
      } catch (err) {
        setCancelPaymentError(err instanceof ApiError ? err.message : 'Failed to cancel payment.')
      }
    },
    [cancelPaymentTarget, detailTarget, refreshDetail],
  )

  /** The PO creator's documented decision on a discrepancy. */
  async function resolveReconciliation(reconciliation: PurchaseOrderReconciliation) {
    const resolution = resolveChoice[reconciliation.id] ?? RESOLUTIONS[reconciliation.kind][0].value
    const note = (resolveNotes[reconciliation.id] ?? '').trim()
    if (!note) {
      setDetailError('Document the resolution in the note.')
      return
    }
    await runAction(
      `resolve-${reconciliation.id}`,
      () => apiClient.post(poUrl(`/reconciliations/${reconciliation.id}/resolve`), { resolution, note }),
      'Failed to resolve the discrepancy.',
    )
  }

  async function submitFollowUp(sendEmail: boolean) {
    if (!detailTarget) return
    if (!followUpMessage.trim()) {
      setFollowUpError('Enter a message.')
      return
    }
    setActionBusy(sendEmail ? 'follow-up' : 'reply')
    setFollowUpError(null)
    try {
      const fileIds: number[] = []
      for (const file of followUpFiles) {
        const form = new FormData()
        form.append('upload', file)
        const { data } = await apiClient.post<{ id: number }>('/api/files', form)
        fileIds.push(data.id)
      }
      await apiClient.post(poUrl('/follow-ups'), {
        send_email: sendEmail,
        subject: followUpSubject.trim() || null,
        message: followUpMessage.trim(),
        attach_po_pdf: sendEmail && followUpAttachPdf,
        file_ids: fileIds,
      })
      setFollowUpMessage('')
      setFollowUpSubject('')
      setFollowUpAttachPdf(false)
      setFollowUpFiles([])
    } catch (err) {
      setFollowUpError(err instanceof ApiError ? err.message : 'Failed to save the follow-up.')
    } finally {
      await refreshDetail(detailTarget.id)
      setActionBusy(null)
    }
  }

  async function postReceipt(receipt: PurchaseOrderReceipt) {
    if (!detailTarget) return
    setPostReceiptBusy(true)
    setPostReceiptError(null)
    try {
      await apiClient.post(`/api/purchase-orders/${detailTarget.id}/receipts/${receipt.id}/post`)
      await refreshDetail(detailTarget.id)
    } catch (err) {
      setPostReceiptError(err instanceof ApiError ? err.message : 'Failed to post goods receipt.')
    } finally {
      setPostReceiptBusy(false)
    }
  }

  async function confirmCancelReceipt() {
    if (!detailTarget || !cancelReceiptTarget) return
    setCancelReceiptBusy(true)
    setCancelReceiptError(null)
    try {
      await apiClient.post(`/api/purchase-orders/${detailTarget.id}/receipts/${cancelReceiptTarget.id}/cancel`)
      setCancelReceiptTarget(null)
      await refreshDetail(detailTarget.id)
    } catch (err) {
      setCancelReceiptError(err instanceof ApiError ? err.message : 'Failed to cancel goods receipt.')
    } finally {
      setCancelReceiptBusy(false)
    }
  }

  function openReverseReceipt(receipt: PurchaseOrderReceipt) {
    setReverseReceiptTarget(receipt)
    reverseReceiptForm.reset({ reason: '' })
    setReverseReceiptError(null)
  }

  const onReverseReceiptSubmit = useCallback(
    async (values: ReverseReceiptFormValues) => {
      if (!detailTarget || !reverseReceiptTarget) return
      setReverseReceiptError(null)
      try {
        await apiClient.post(`/api/purchase-orders/${detailTarget.id}/receipts/${reverseReceiptTarget.id}/reverse`, {
          reason: values.reason,
        })
        setReverseReceiptTarget(null)
        await refreshDetail(detailTarget.id)
      } catch (err) {
        setReverseReceiptError(err instanceof ApiError ? err.message : 'Failed to reverse goods receipt.')
      }
    },
    [detailTarget, refreshDetail, reverseReceiptTarget],
  )

  async function downloadFile(file: PurchaseFile) {
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

  const canReceive = detailTarget?.status === 'sent' || detailTarget?.status === 'partially_received'
  const canCancelStatus = !!detailTarget && CANCELLABLE.includes(detailTarget.status)
  const hasPayments = !!detailTarget && !['draft', 'pending_approval'].includes(detailTarget.status)
  const isOpen = !!detailTarget && !['draft', 'pending_approval', 'closed', 'cancelled'].includes(detailTarget.status)
  const openToReceiving = (id: number) => navigate('/receiving', { state: { openPurchaseOrderId: id } })
  const openToPayments = (id: number) => navigate(`/finance/payments/${id}`)

  const columns: DataTableColumn<PurchaseOrder>[] = [
    { key: 'po_number', label: 'PO Number', render: (po) => po.po_number },
    { key: 'supplier', label: 'Supplier', render: (po) => suppliersById.get(po.supplier_id)?.name ?? `#${po.supplier_id}` },
    { key: 'order_date', label: 'Order Date', hideBelow: 'sm', render: (po) => formatDate(po.order_date) },
    {
      key: 'expected',
      label: 'Expected Delivery',
      hideBelow: 'md',
      render: (po) => (
        <>
          {formatDate(po.expected_delivery_date)}
          {po.is_overdue && (
            <Badge tone="danger" className="mt-1 block w-fit">
              {`Overdue ${po.days_overdue} ${po.days_overdue === 1 ? 'day' : 'days'}`}
            </Badge>
          )}
        </>
      ),
    },
    { key: 'total', label: 'Total', hideBelow: 'md', render: (po) => `${po.total_amount} ${po.currency}` },
    { key: 'status', label: 'Status', render: (po) => <Badge tone={STATUS_TONES[po.status]}>{STATUS_LABELS[po.status]}</Badge> },
    {
      key: 'payment',
      label: 'Payment',
      hideBelow: 'lg',
      render: (po) => {
        if (po.status === 'cancelled') {
          return Number(po.refundable_amount) > 0 ? <Badge tone="warning">Refundable</Badge> : '—'
        }
        if (['draft', 'pending_approval'].includes(po.status)) return '—'
        return <Badge tone={PAYMENT_STATUS_TONES[po.payment_status]}>{PAYMENT_STATUS_LABELS[po.payment_status]}</Badge>
      },
    },
    {
      key: 'actions',
      label: '',
      alwaysVisible: true,
      align: 'right' as const,
      render: (po: PurchaseOrder) => {
        const options: ActionMenuOption[] = [{ key: 'view', label: 'View', onSelect: () => openDetail(po) }]
        if (canManage) {
          if (po.status === 'draft') options.push({ key: 'manage', label: 'Edit Items / Submit...', onSelect: () => openDetail(po) })
          if (po.status === 'pending_approval') options.push({ key: 'approve', label: 'Approve...', onSelect: () => openDetail(po) })
          if (po.status === 'approved') options.push({ key: 'send', label: 'Send...', onSelect: () => openDetail(po) })
          if (po.status === 'sent' || po.status === 'partially_received')
            options.push({ key: 'receive', label: 'Receive Goods...', onSelect: () => openToReceiving(po.id) })
          if (po.status === 'reconciliation_required' || po.status === 'payment_reconciliation')
            options.push({ key: 'reconcile', label: 'Resolve Discrepancy...', onSelect: () => openDetail(po) })
          if (!['draft', 'pending_approval', 'cancelled', 'closed'].includes(po.status))
            options.push({ key: 'payment', label: 'Payments / Follow-up...', onSelect: () => openDetail(po) })
          if (CANCELLABLE.includes(po.status)) options.push({ key: 'cancel', label: 'Cancel', danger: true, onSelect: () => openCancel(po) })
        }
        return <ActionMenu label={`Actions for ${po.po_number}`} options={options} />
      },
    },
  ]

  return (
    <div className="space-y-6">
      <div hidden={viewId !== null} className="space-y-6">
        <PageHeader
          title="Purchase Orders"
          subtitle="Approval → Sent → Follow-up → Goods Receipt → Reconciliation → Payment → Closed."
          actions={canManage ? <Button onClick={openCreate}>New Purchase</Button> : undefined}
        />

        <Alert variant="danger">{pageError}</Alert>

        <FilterBar>
          <TextField
            label="Search"
            placeholder="Search by PO number..."
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
          <SelectField
            label="Delivery"
            value={overdueFilter ? 'overdue' : ''}
            onChange={(event) => setOverdueFilter(event.target.value === 'overdue')}
          >
            <option value="">All</option>
            <option value="overdue">Overdue only</option>
          </SelectField>
        </FilterBar>

        <DataTable
          columns={columns}
          rows={table.rows}
          rowKey={(po) => po.id}
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
          emptyTitle={debouncedSearch ? 'No matching purchase orders' : 'No purchase orders yet'}
          emptyMessage={
            debouncedSearch
              ? 'Try a different search term.'
              : canManage
                ? 'Create the first purchase order with the New Purchase button above.'
                : 'No purchase orders have been created yet.'
          }
        />
      </div>

      {viewId !== null && (
        <section aria-label={detailTarget ? `Purchase Order ${detailTarget.po_number}` : 'Purchase Order'} className="space-y-6">
          <PageHeader title={detailTarget ? `Purchase Order ${detailTarget.po_number}` : 'Purchase Order'} />
          {!detailTarget ? (
            <div className="flex flex-col gap-4">
              {viewLoading ? <Spinner /> : <Alert variant="danger">{detailError}</Alert>}
              <div>
                <Button variant="secondary" onClick={closeDetail}>Back to Purchase Orders</Button>
              </div>
            </div>
          ) : (
            <>
              <div className="flex flex-col gap-6">
                <Alert variant="success">{notice}</Alert>
                <Alert variant="danger">{detailError}</Alert>

                <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                  <div><span className="text-gold-100/50">Supplier: </span>{suppliersById.get(detailTarget.supplier_id)?.name ?? `#${detailTarget.supplier_id}`}</div>
                  <div><span className="text-gold-100/50">PO Date: </span>{formatDate(detailTarget.order_date)}</div>
                  <div>
                    <span className="text-gold-100/50">Expected Delivery: </span>{formatDate(detailTarget.expected_delivery_date)}
                    {detailTarget.is_overdue && (
                      <Badge tone="danger" className="ml-2">
                        {`Overdue ${detailTarget.days_overdue} ${detailTarget.days_overdue === 1 ? 'day' : 'days'}`}
                      </Badge>
                    )}
                  </div>
                  <div><span className="text-gold-100/50">Payment Terms: </span>{detailTarget.payment_terms ?? '—'}</div>
                  <div><span className="text-gold-100/50">Status: </span><Badge tone={STATUS_TONES[detailTarget.status]}>{STATUS_LABELS[detailTarget.status]}</Badge></div>
                  <div><span className="text-gold-100/50">Revision: </span>{detailTarget.revision_number || '—'}</div>
                  {detailTarget.supplier_reference && <div><span className="text-gold-100/50">Supplier Reference: </span>{detailTarget.supplier_reference}</div>}
                  {detailTarget.rfq_number && <div><span className="text-gold-100/50">RFQ: </span>{detailTarget.rfq_number}</div>}
                  {detailTarget.delivery_instructions && <div className="col-span-2"><span className="text-gold-100/50">Delivery Instructions: </span>{detailTarget.delivery_instructions}</div>}
                  {detailTarget.notes && <div className="col-span-2"><span className="text-gold-100/50">Notes: </span>{detailTarget.notes}</div>}
                  {detailTarget.cancel_reason && <div className="col-span-2"><span className="text-gold-100/50">Cancel Reason: </span>{detailTarget.cancel_reason}</div>}
                </div>

                <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gold-100/70">
                  <div>Created: {stamp(detailTarget.created_at, detailTarget.created_by_name)}</div>
                  {detailTarget.approved_at && <div>Approved: {stamp(detailTarget.approved_at, detailTarget.approved_by_name)}</div>}
                  {detailTarget.sent_at && <div>Sent: {stamp(detailTarget.sent_at, detailTarget.sent_by_name)}</div>}
                  {detailTarget.cancelled_at && <div>Cancelled: {stamp(detailTarget.cancelled_at, detailTarget.cancelled_by_name)}</div>}
                </div>

                {/* Lines */}
                <div>
                  <h3 className="mb-2 text-xs uppercase tracking-wide text-gold-100/50">Items</h3>
                  {detailTarget.lines.length === 0 ? (
                    <p className="text-sm text-gold-100/60">No items on this purchase order yet.</p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                            <th className="py-2 pr-3">Product / Material</th>
                            <th className="py-2 pr-3">Ordered</th>
                            <th className="py-2 pr-3">UOM</th>
                            <th className="py-2 pr-3">Unit Price</th>
                            <th className="py-2 pr-3">Line Total</th>
                            <th className="py-2 pr-3">Received</th>
                            <th className="py-2 pr-3">Remaining</th>
                          </tr>
                        </thead>
                        <tbody>
                          {detailTarget.lines.map((line) => {
                            const remaining = lineRemaining(line)
                            return (
                              <tr key={line.id} className="border-t border-ink-700">
                                <td className="py-2 pr-3">
                                  {materialsById.get(line.raw_material_id)?.name ?? `#${line.raw_material_id}`}
                                  {line.remarks && <span className="block text-xs text-gold-100/50">{line.remarks}</span>}
                                </td>
                                <td className="py-2 pr-3">{line.quantity}</td>
                                <td className="py-2 pr-3">{unitCode(line.unit_of_measure_id)}</td>
                                <td className="py-2 pr-3">{line.unit_price}</td>
                                <td className="py-2 pr-3">{line.line_total}</td>
                                <td className="py-2 pr-3">{line.received_quantity}</td>
                                <td className="py-2 pr-3">
                                  {remaining}
                                  {Number(line.cancelled_quantity) > 0 && (
                                    <span className="block text-xs text-gold-100/50">{line.cancelled_quantity} cancelled</span>
                                  )}
                                </td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}


                  {canReceive && (
                    <Button type="button" variant="secondary" className="mt-2" onClick={() => openToReceiving(detailTarget.id)}>
                      Open in Goods Receiving
                    </Button>
                  )}
                </div>

                {/* Goods Receipts */}
                {detailTarget.receipts.length > 0 && (
                  <div>
                    <h3 className="mb-2 text-xs uppercase tracking-wide text-gold-100/50">Goods Receipts</h3>
                    <Alert variant="danger">{postReceiptError}</Alert>
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                          <th className="py-2 pr-3">Receipt No.</th>
                          <th className="py-2 pr-3">Date</th>
                          <th className="py-2 pr-3">Delivery Ref.</th>
                          <th className="py-2 pr-3">Status</th>
                          <th className="py-2 pr-3">Documents</th>
                          <th className="py-2"></th>
                        </tr>
                      </thead>
                      <tbody>
                        {detailTarget.receipts.map((receipt) => (
                          <>
                            <tr key={receipt.id} className="border-t border-ink-700 align-top">
                              <td className="py-2 pr-3">{receipt.receipt_number}</td>
                              <td className="py-2 pr-3">
                                {formatDate(receipt.receipt_date)}
                                {receipt.days_late > 0 && <span className="block text-xs text-warning-500">{receipt.days_late} day(s) late</span>}
                                {receipt.received_by_name && <span className="block text-xs text-gold-100/50">by {receipt.received_by_name}</span>}
                              </td>
                              <td className="py-2 pr-3">{receipt.supplier_delivery_reference ?? '—'}</td>
                              <td className="py-2 pr-3">
                                <Badge tone={RECEIPT_STATUS_TONES[receipt.status]}>{RECEIPT_STATUS_LABELS[receipt.status]}</Badge>
                                {receipt.status === 'reversed' && receipt.reversal_reason && (
                                  <div className="mt-1 text-xs text-gold-100/50">{receipt.reversal_reason}</div>
                                )}
                              </td>
                              <td className="py-2 pr-3">
                                <div className="flex flex-wrap gap-1">
                                  {receipt.documents.map((file) => (
                                    <button
                                      key={file.id}
                                      type="button"
                                      onClick={() => downloadFile(file)}
                                      className="rounded border border-ink-700 px-2 py-0.5 text-xs hover:border-gold-400"
                                    >
                                      {file.original_filename}
                                    </button>
                                  ))}
                                </div>
                              </td>
                              <td className="py-2 text-right">
                                <div className="flex justify-end gap-2">
                                  <Button
                                    variant="secondary"
                                    onClick={() => setExpandedReceipt(expandedReceipt === receipt.id ? null : receipt.id)}
                                  >
                                    {expandedReceipt === receipt.id ? 'Hide Lines' : 'View Lines'}
                                  </Button>
                                  {canManage && receipt.status === 'draft' && (
                                    <>
                                      <Button isLoading={postReceiptBusy} onClick={() => postReceipt(receipt)}>Post</Button>
                                      <Button variant="secondary" onClick={() => setCancelReceiptTarget(receipt)}>Cancel</Button>
                                    </>
                                  )}
                                  {canManage && receipt.status === 'posted' && (
                                    <Button variant="danger" onClick={() => openReverseReceipt(receipt)}>Reverse...</Button>
                                  )}
                                </div>
                              </td>
                            </tr>
                            {expandedReceipt === receipt.id && (
                              <tr key={`${receipt.id}-lines`} className="border-t border-ink-700 bg-ink-900/40">
                                <td colSpan={6} className="py-2 pr-3">
                                  <table className="w-full text-xs">
                                    <thead>
                                      <tr className="text-left uppercase tracking-wide text-gold-100/40">
                                        <th className="py-1 pr-3">Raw Material</th>
                                        <th className="py-1 pr-3">Quantity</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {receipt.lines.map((line) => (
                                        <tr key={line.id}>
                                          <td className="py-1 pr-3">{materialsById.get(line.raw_material_id)?.name ?? `#${line.raw_material_id}`}</td>
                                          <td className="py-1 pr-3">
                                            {line.quantity}{' '}
                                            {unitCode(detailTarget.lines.find((l) => l.id === line.purchase_order_line_id)?.unit_of_measure_id ?? null)}
                                            {line.remarks && <span className="block text-gold-100/50">{line.remarks}</span>}
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </td>
                              </tr>
                            )}
                          </>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Payments */}
                {hasPayments && (
                  <div>
                    <div className="mb-2 flex items-center justify-between">
                      <h3 className="text-xs uppercase tracking-wide text-gold-100/50">
                        Payments{' '}
                        <Badge tone={PAYMENT_STATUS_TONES[detailTarget.payment_status]}>{PAYMENT_STATUS_LABELS[detailTarget.payment_status]}</Badge>
                      </h3>
                      <Button type="button" variant="secondary" onClick={() => openToPayments(detailTarget.id)}>
                        Open in Finance → Payments
                      </Button>
                    </div>
                    <div className="mb-2 flex items-center justify-between">
                      <div className="text-sm">
                        <span className="text-gold-100/50">PO Amount </span>{detailTarget.final_amount} {detailTarget.currency}
                        {detailTarget.final_amount !== detailTarget.total_amount && (
                          <span className="text-gold-100/40"> (ordered {detailTarget.total_amount})</span>
                        )}
                        <span className="mx-2 text-gold-100/30">|</span>
                        <span className="text-gold-100/50">Paid </span>{detailTarget.paid_amount}
                        <span className="mx-2 text-gold-100/30">|</span>
                        {detailTarget.status === 'cancelled' ? (
                          <>
                            <span className="text-gold-100/50">Refundable </span>
                            <span className={Number(detailTarget.refundable_amount) > 0 ? 'font-semibold text-gold-200' : undefined}>
                              {detailTarget.refundable_amount}
                            </span>
                          </>
                        ) : (
                          <>
                            <span className="text-gold-100/50">Outstanding </span>{detailTarget.outstanding_amount}
                          </>
                        )}
                      </div>
                    </div>
                    {detailTarget.status === 'cancelled' && Number(detailTarget.refundable_amount) > 0 && (
                      <p className="mb-2 text-sm text-gold-200">
                        This order was cancelled with {detailTarget.refundable_amount} {detailTarget.currency} already paid --
                        no further payment is due; this amount is owed back from the supplier.
                      </p>
                    )}
                    {detailTarget.payments.length === 0 ? (
                      <p className="text-sm text-gold-100/60">No payments recorded yet.</p>
                    ) : (
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                            <th className="py-2 pr-3">Date</th>
                            <th className="py-2 pr-3">Amount</th>
                            <th className="py-2 pr-3">Method</th>
                            <th className="py-2 pr-3">Reference</th>
                            <th className="py-2 pr-3">Status</th>
                            <th className="py-2 pr-3">Evidence</th>
                            <th className="py-2"></th>
                          </tr>
                        </thead>
                        <tbody>
                          {detailTarget.payments.map((payment) => (
                            <tr key={payment.id} className="border-t border-ink-700 align-top">
                              <td className="py-2 pr-3">{formatDate(payment.payment_date)}</td>
                              <td className="py-2 pr-3">
                                {payment.amount}
                                {payment.is_final && <span className="block text-xs text-gold-100/50">Final payment</span>}
                              </td>
                              <td className="py-2 pr-3">{payment.payment_method ?? '—'}</td>
                              <td className="py-2 pr-3">{payment.reference_number ?? '—'}</td>
                              <td className="py-2 pr-3">
                                <Badge tone={payment.status === 'cancelled' ? 'danger' : 'success'}>
                                  {payment.status === 'cancelled' ? 'Cancelled' : 'Recorded'}
                                </Badge>
                              </td>
                              <td className="py-2 pr-3">
                                <div className="flex flex-wrap gap-1">
                                  {payment.files.map((file) => (
                                    <button
                                      key={file.id}
                                      type="button"
                                      onClick={() => downloadFile(file)}
                                      className="rounded border border-ink-700 px-2 py-0.5 text-xs hover:border-gold-400"
                                    >
                                      {file.original_filename}
                                    </button>
                                  ))}
                                </div>
                              </td>
                              <td className="py-2 text-right">
                                {canManage && payment.status === 'recorded' && (
                                  <Button variant="secondary" onClick={() => openCancelPayment(payment)}>Cancel</Button>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                    {isOpen && <p className="mt-2 text-xs text-gold-100/60">Payments are recorded by Finance (Finance → Payments).</p>}
                  </div>
                )}

                {/* Reconciliation */}
                {detailTarget.reconciliations.length > 0 && (
                  <div>
                    <h3 className="mb-2 text-xs uppercase tracking-wide text-gold-100/50">Reconciliation</h3>
                    <div className="flex flex-col gap-3">
                      {detailTarget.reconciliations.map((rec) => (
                        <div key={rec.id} className={`rounded-md border p-3 text-sm ${rec.status === 'open' ? 'border-danger-500' : 'border-ink-700'}`}>
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span>
                              <Badge tone={rec.status === 'open' ? 'danger' : 'success'}>
                                {`${rec.kind === 'receipt' ? 'Receipt' : 'Payment'} — ${rec.status === 'open' ? 'Open' : 'Resolved'}`}
                              </Badge>{' '}
                              <span className="text-xs text-gold-100/50">{formatKuwaitTime(rec.created_at)}</span>
                            </span>
                          </div>
                          <p className="mt-1">{rec.discrepancy}</p>
                          {rec.status === 'resolved' ? (
                            <p className="mt-1 text-gold-100/70">
                              {RESOLUTION_LABELS[rec.resolution ?? ''] ?? rec.resolution}: {rec.resolution_note}
                              <span className="block text-xs text-gold-100/50">{stamp(rec.resolved_at, rec.resolved_by_name)}</span>
                            </p>
                          ) : (
                            canManage && (
                              <div className="mt-2 flex flex-col gap-2">
                                <SelectField
                                  label="Resolution"
                                  value={resolveChoice[rec.id] ?? RESOLUTIONS[rec.kind][0].value}
                                  onChange={(e) => setResolveChoice((prev) => ({ ...prev, [rec.id]: e.target.value }))}
                                >
                                  {RESOLUTIONS[rec.kind].map((option) => (
                                    <option key={option.value} value={option.value}>{option.label}</option>
                                  ))}
                                </SelectField>
                                <TextareaField
                                  label="Resolution note"
                                  required
                                  hint={rec.kind === 'receipt' ? 'e.g. supplier sends balance Friday; substitution accepted; material rejected (reverse the receipt).' : 'e.g. agreed discount; Finance to refund.'}
                                  value={resolveNotes[rec.id] ?? ''}
                                  onChange={(e) => setResolveNotes((prev) => ({ ...prev, [rec.id]: e.target.value }))}
                                />
                                <div>
                                  <Button onClick={() => resolveReconciliation(rec)} isLoading={actionBusy === `resolve-${rec.id}`}>Resolve</Button>
                                </div>
                              </div>
                            )
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Supplier follow-up */}
                {(detailTarget.communications.length > 0 || isOpen) && (
                  <div>
                    <h3 className="mb-2 text-xs uppercase tracking-wide text-gold-100/50">Supplier Follow-up</h3>
                    {detailTarget.communications.length > 0 && (
                      <ul className="flex flex-col gap-2 text-sm">
                        {detailTarget.communications.map((entry) => (
                          <li key={entry.id} className="rounded-md border border-ink-700 p-2">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-xs text-gold-100/50">{formatKuwaitTime(entry.created_at)}</span>
                              <span>{COMMUNICATION_LABELS[entry.kind]}</span>
                              {entry.status === 'failed' && <Badge tone="danger">Failed</Badge>}
                              {entry.recipient && <span className="text-xs text-gold-100/50">to {entry.recipient}</span>}
                              {entry.sent_by_name && <span className="text-xs text-gold-100/50">by {entry.sent_by_name}</span>}
                            </div>
                            {entry.subject && <div className="mt-1 font-medium">{entry.subject}</div>}
                            {entry.message && <div className="mt-1 whitespace-pre-line text-gold-100/80">{entry.message}</div>}
                            {entry.error && <div className="mt-1 text-xs text-danger-500">{entry.error}</div>}
                            {entry.files.length > 0 && (
                              <div className="mt-1 flex flex-wrap gap-1">
                                {entry.files.map((file) => (
                                  <button key={file.id} type="button" onClick={() => downloadFile(file)} className="rounded border border-ink-700 px-2 py-0.5 text-xs hover:border-gold-400">
                                    {file.original_filename}
                                  </button>
                                ))}
                              </div>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                    {canManage && isOpen && (
                      <div className="mt-2 flex flex-col gap-3 rounded-md border border-ink-700 p-3">
                        <Alert variant="danger">{followUpError}</Alert>
                        <TextField label="Subject" placeholder={`Follow-up: Purchase Order ${detailTarget.po_number}`} value={followUpSubject} onChange={(e) => setFollowUpSubject(e.target.value)} />
                        <TextareaField label="Message" required value={followUpMessage} onChange={(e) => setFollowUpMessage(e.target.value)} />
                        <CheckboxField label="Attach the PO PDF" checked={followUpAttachPdf} onChange={(e) => setFollowUpAttachPdf(e.target.checked)} />
                        <FileUploadField label="Attachment" multiple accept=".pdf,.png,.jpg,.jpeg" value={followUpFiles} onChange={setFollowUpFiles} />
                        <div className="flex flex-wrap gap-2">
                          <Button onClick={() => submitFollowUp(true)} isLoading={actionBusy === 'follow-up'}>Send Follow-up Email</Button>
                          <Button variant="secondary" onClick={() => submitFollowUp(false)} isLoading={actionBusy === 'reply'}>Record Supplier Reply</Button>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Revisions & documents */}
                {detailTarget.revisions.length > 0 && (
                  <div>
                    <h3 className="mb-2 text-xs uppercase tracking-wide text-gold-100/50">Revisions</h3>
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                          <th className="py-2 pr-3">Rev</th>
                          <th className="py-2 pr-3">Approved</th>
                          <th className="py-2 pr-3">Total</th>
                          <th className="py-2 pr-3">Document</th>
                          <th className="py-2"></th>
                        </tr>
                      </thead>
                      <tbody>
                        {detailTarget.revisions.map((revision) => (
                          <>
                            <tr key={revision.id} className="border-t border-ink-700">
                              <td className="py-2 pr-3">{revision.revision_number}</td>
                              <td className="py-2 pr-3">{formatKuwaitTime(revision.issued_at)}</td>
                              <td className="py-2 pr-3">{revision.total_amount}</td>
                              <td className="py-2 pr-3">
                                {revision.pdf_file ? (
                                  <button
                                    type="button"
                                    onClick={() => downloadFile(revision.pdf_file!)}
                                    className="rounded border border-ink-700 px-2 py-0.5 text-xs hover:border-gold-400"
                                  >
                                    {revision.pdf_file.original_filename} ({formatBytes(revision.pdf_file.size_bytes)})
                                  </button>
                                ) : (
                                  '—'
                                )}
                              </td>
                              <td className="py-2 text-right">
                                <Button
                                  variant="secondary"
                                  onClick={() => setExpandedRevision(expandedRevision === revision.id ? null : revision.id)}
                                >
                                  {expandedRevision === revision.id ? 'Hide Lines' : 'View Lines'}
                                </Button>
                              </td>
                            </tr>
                            {expandedRevision === revision.id && (
                              <tr key={`${revision.id}-lines`} className="border-t border-ink-700 bg-ink-900/40">
                                <td colSpan={5} className="py-2 pr-3">
                                  <table className="w-full text-xs">
                                    <thead>
                                      <tr className="text-left uppercase tracking-wide text-gold-100/40">
                                        <th className="py-1 pr-3">Raw Material</th>
                                        <th className="py-1 pr-3">Qty</th>
                                        <th className="py-1 pr-3">UOM</th>
                                        <th className="py-1 pr-3">Unit Price</th>
                                        <th className="py-1 pr-3">Line Total</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {revision.lines.map((line) => (
                                        <tr key={line.id}>
                                          <td className="py-1 pr-3">{materialsById.get(line.raw_material_id)?.name ?? `#${line.raw_material_id}`}</td>
                                          <td className="py-1 pr-3">{line.quantity}</td>
                                          <td className="py-1 pr-3">{unitCode(line.unit_of_measure_id)}</td>
                                          <td className="py-1 pr-3">{line.unit_price}</td>
                                          <td className="py-1 pr-3">{line.line_total}</td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </td>
                              </tr>
                            )}
                          </>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {detailTarget.documents.length > 0 && (
                  <div>
                    <h3 className="mb-2 text-xs uppercase tracking-wide text-gold-100/50">Documents</h3>
                    <div className="flex flex-wrap gap-2">
                      {detailTarget.documents.map((file) => (
                        <button
                          key={file.id}
                          type="button"
                          onClick={() => downloadFile(file)}
                          className="rounded border border-ink-700 px-2 py-1 text-xs hover:border-gold-400"
                        >
                          {file.original_filename} ({formatBytes(file.size_bytes)})
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="flex flex-wrap justify-end gap-2 border-t border-ink-700 pt-4">
              {canManage && detailTarget?.status === 'draft' && (
                <Button variant="secondary" onClick={() => navigate(`/purchase-orders/${detailTarget.id}/edit`)}>Edit</Button>
              )}
              {canManage && detailTarget?.status === 'draft' && (
                <Button onClick={submitForApproval} isLoading={actionBusy === 'submit'} disabled={detailTarget.lines.length === 0}>
                  Submit for Approval
                </Button>
              )}
              {canManage && detailTarget?.status === 'pending_approval' && (
                <>
                  <Button onClick={approvePurchaseOrder} isLoading={actionBusy === 'approve'}>Approve</Button>
                  <Button variant="secondary" onClick={backToDraft} isLoading={actionBusy === 'draft'}>Send Back to Draft</Button>
                </>
              )}
              {canManage && detailTarget?.status === 'approved' && (
                <>
                  <Button onClick={emailPurchaseOrder} isLoading={actionBusy === 'email'}>Email to Supplier</Button>
                  <Button variant="secondary" onClick={markSent} isLoading={actionBusy === 'mark-sent'}>Mark as Sent</Button>
                </>
              )}
              {canManage && detailTarget?.status === 'sent' && (
                <Button variant="secondary" onClick={emailPurchaseOrder} isLoading={actionBusy === 'email'}>Re-send Email</Button>
              )}
              {canManage && (detailTarget?.status === 'approved' || detailTarget?.status === 'sent') && (
                <Button variant="secondary" onClick={backToDraft} isLoading={actionBusy === 'draft'}>Create Revision</Button>
              )}
              {canManage && canCancelStatus && (
                <Button variant="danger" onClick={() => detailTarget && openCancel(detailTarget)}>Cancel...</Button>
              )}
              <Button variant="secondary" onClick={closeDetail}>Back to Purchase Orders</Button>
              </div>
            </>
          )}
        </section>
      )}

      <Modal open={!!cancelPaymentTarget} title="Cancel Payment" onClose={() => setCancelPaymentTarget(null)} footer={
        <>
          <Button variant="secondary" onClick={() => setCancelPaymentTarget(null)}>Keep Payment</Button>
          <Button variant="danger" onClick={cancelPaymentForm.handleSubmit(onCancelPaymentSubmit)} isLoading={cancelPaymentForm.formState.isSubmitting}>
            Cancel Payment
          </Button>
        </>
      }>
        <form className="flex flex-col gap-4">
          <Alert variant="danger">{cancelPaymentError}</Alert>
          <p className="text-sm text-gold-100/70">
            {cancelPaymentTarget && `${cancelPaymentTarget.payment_number} — ${cancelPaymentTarget.amount} stays visible in history; only its status changes.`}
          </p>
          <TextareaField label="Reason" required {...cancelPaymentForm.register('reason')} error={cancelPaymentForm.formState.errors.reason?.message} />
        </form>
      </Modal>

      <ConfirmDialog
        open={!!cancelReceiptTarget}
        title="Cancel Goods Receipt"
        message={
          cancelReceiptError ??
          (cancelReceiptTarget
            ? `${cancelReceiptTarget.receipt_number} will be discarded -- it never had any effect on stock.`
            : '')
        }
        confirmLabel="Cancel Receipt"
        danger
        busy={cancelReceiptBusy}
        onConfirm={confirmCancelReceipt}
        onCancel={() => setCancelReceiptTarget(null)}
      />

      <Modal
        open={!!reverseReceiptTarget}
        title="Reverse Goods Receipt"
        onClose={() => setReverseReceiptTarget(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setReverseReceiptTarget(null)}>Keep Receipt</Button>
            <Button
              variant="danger"
              onClick={reverseReceiptForm.handleSubmit(onReverseReceiptSubmit)}
              isLoading={reverseReceiptForm.formState.isSubmitting}
            >
              Reverse Receipt
            </Button>
          </>
        }
      >
        <form className="flex flex-col gap-4">
          <Alert variant="danger">{reverseReceiptError}</Alert>
          <p className="text-sm text-gold-100/70">
            {reverseReceiptTarget &&
              `${reverseReceiptTarget.receipt_number} stays visible in history with its original quantities; this creates an offsetting stock movement and reduces the purchase order's received quantity. To correct the amount, reverse then create a new receipt.`}
          </p>
          <TextareaField
            label="Reason"
            required
            {...reverseReceiptForm.register('reason')}
            error={reverseReceiptForm.formState.errors.reason?.message}
          />
        </form>
      </Modal>

      <Modal
        open={!!cancelTarget}
        title={`Cancel Purchase Order ${cancelTarget?.po_number ?? ''}`}
        onClose={() => setCancelTarget(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setCancelTarget(null)}>Keep Purchase Order</Button>
            <Button variant="danger" onClick={cancelForm.handleSubmit(onCancelSubmit)} isLoading={cancelForm.formState.isSubmitting}>
              Cancel Purchase Order
            </Button>
          </>
        }
      >
        <form className="flex flex-col gap-4">
          <Alert variant="danger">{cancelError}</Alert>
          <TextareaField label="Reason" required hint="Required to cancel a purchase order." {...cancelForm.register('cancel_reason')} error={cancelForm.formState.errors.cancel_reason?.message} />
        </form>
      </Modal>
    </div>
  )
}
