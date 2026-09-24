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
import { FormDialog } from '@/components/ui/FormDialog'
import { Modal } from '@/components/ui/Modal'
import { PageHeader } from '@/components/ui/PageHeader'
import type { SortState } from '@/components/ui/sort'
import { DateField } from '@/components/forms/DateField'
import { FileUploadField } from '@/components/forms/FileUploadField'
import { SelectField } from '@/components/forms/SelectField'
import { TextField } from '@/components/forms/TextField'
import { TextareaField } from '@/components/forms/TextareaField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { useAuth } from '@/lib/auth/AuthContext'
import { isAdminRole } from '@/lib/auth/roles'
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
  status: 'recorded' | 'cancelled'
  cancelled_at: string | null
  cancellation_reason: string | null
  created_by_user_id: number | null
  created_at: string
  files: PurchaseFile[]
}

type PurchaseOrderStatus = 'draft' | 'pending_approval' | 'approved' | 'sent' | 'partially_received' | 'received' | 'cancelled'
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
  paid_amount: string
  outstanding_amount: string
  payment_status: PaymentStatus
  lines: PurchaseOrderLine[]
  revisions: PurchaseOrderRevision[]
  documents: PurchaseFile[]
  payments: PurchaseOrderPayment[]
  receipts: PurchaseOrderReceipt[]
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
}

const STATUS_LABELS: Record<PurchaseOrderStatus, string> = {
  draft: 'Draft',
  pending_approval: 'Pending Approval',
  approved: 'Approved',
  sent: 'Sent',
  partially_received: 'Partially Received',
  received: 'Received',
  cancelled: 'Cancelled',
}

const STATUS_TONES: Record<PurchaseOrderStatus, BadgeTone> = {
  draft: 'info',
  pending_approval: 'warning',
  approved: 'gold',
  sent: 'gold',
  partially_received: 'warning',
  received: 'success',
  cancelled: 'danger',
}

const PAYMENT_STATUS_LABELS: Record<PaymentStatus, string> = { unpaid: 'Unpaid', partially_paid: 'Partially Paid', paid: 'Paid' }
const PAYMENT_STATUS_TONES: Record<PaymentStatus, BadgeTone> = { unpaid: 'neutral', partially_paid: 'warning', paid: 'success' }

const CANCELLABLE: PurchaseOrderStatus[] = ['draft', 'pending_approval', 'approved', 'sent', 'partially_received']

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

function stamp(at: string | null, by: string | null): string | null {
  if (!at) return null
  return `${new Date(at).toLocaleString()}${by ? ` by ${by}` : ''}`
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

const DECIMAL_RE = /^\d+(\.\d+)?$/

const poSchema = z.object({
  supplier_id: z.string().min(1, 'Supplier is required'),
  warehouse_id: z.string().min(1, 'Delivery location is required'),
  expected_delivery_date: z
    .string()
    .min(1, 'Expected delivery date is required')
    .refine((v) => v >= todayIso(), 'Cannot be in the past'),
  payment_terms: z.string().trim().min(1, 'Payment terms are required'),
  currency: z.string().trim().regex(/^[A-Za-z]{3}$/, 'Enter a 3-letter currency code'),
  supplier_reference: z.string(),
  delivery_instructions: z.string(),
  notes: z.string(),
})

type PoFormValues = z.infer<typeof poSchema>

const emptyPoDefaults: PoFormValues = {
  supplier_id: '',
  warehouse_id: '',
  expected_delivery_date: '',
  payment_terms: '',
  currency: 'KWD',
  supplier_reference: '',
  delivery_instructions: '',
  notes: '',
}

const lineSchema = z.object({
  raw_material_id: z.string().min(1, 'Raw material is required'),
  quantity: z
    .string()
    .min(1, 'Quantity is required')
    .refine((v) => DECIMAL_RE.test(v) && Number(v) > 0, 'Enter a positive number'),
  unit_of_measure_id: z.string().min(1, 'Unit is required'),
  unit_price: z
    .string()
    .min(1, 'Unit price is required')
    .refine((v) => DECIMAL_RE.test(v) && Number(v) > 0, 'Enter a positive number'),
  required_by_date: z.string(),
  remarks: z.string(),
})

type LineFormValues = z.infer<typeof lineSchema>

const emptyLineDefaults: LineFormValues = {
  raw_material_id: '',
  quantity: '',
  unit_of_measure_id: '',
  unit_price: '',
  required_by_date: '',
  remarks: '',
}

const cancelSchema = z.object({
  cancel_reason: z.string().min(1, 'A reason is required to cancel this purchase order.'),
})

type CancelFormValues = z.infer<typeof cancelSchema>

const paymentSchema = z.object({
  payment_date: z.string().min(1, 'Payment date is required'),
  amount: z
    .string()
    .min(1, 'Amount is required')
    .refine((v) => DECIMAL_RE.test(v) && Number(v) > 0, 'Enter a positive number'),
  payment_method: z.string(),
  reference_number: z.string(),
  notes: z.string(),
})

type PaymentFormValues = z.infer<typeof paymentSchema>

const emptyPaymentDefaults: PaymentFormValues = {
  payment_date: new Date().toISOString().slice(0, 10),
  amount: '',
  payment_method: '',
  reference_number: '',
  notes: '',
}

const cancelPaymentSchema = z.object({
  reason: z.string().min(1, 'A reason is required to cancel this payment.'),
})

type CancelPaymentFormValues = z.infer<typeof cancelPaymentSchema>

const createReceiptSchema = z.object({
  receipt_date: z.string().min(1, 'Receipt date is required'),
  supplier_delivery_reference: z.string(),
  notes: z.string(),
})

type CreateReceiptFormValues = z.infer<typeof createReceiptSchema>

const emptyCreateReceiptDefaults: CreateReceiptFormValues = {
  receipt_date: new Date().toISOString().slice(0, 10),
  supplier_delivery_reference: '',
  notes: '',
}

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
    },
  })
  return { rows: data.data, total: data.pagination.total }
}

function lineRemaining(line: PurchaseOrderLine): number {
  return Number(line.quantity) - Number(line.received_quantity)
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
  const [warehouses, setWarehouses] = useState<LookupOption[]>([])
  const [materials, setMaterials] = useState<LookupOption[]>([])
  const [units, setUnits] = useState<LookupOption[]>([])
  const [pageError, setPageError] = useState<string | undefined>(undefined)

  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 300)

  const [formOpen, setFormOpen] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const [detailTarget, setDetailTarget] = useState<PurchaseOrder | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [expandedRevision, setExpandedRevision] = useState<number | null>(null)

  const [lineFormOpen, setLineFormOpen] = useState(false)

  const [actionBusy, setActionBusy] = useState<string | null>(null)

  const [cancelTarget, setCancelTarget] = useState<PurchaseOrder | null>(null)
  const [cancelError, setCancelError] = useState<string | null>(null)

  const [paymentFormOpen, setPaymentFormOpen] = useState(false)
  const [paymentFiles, setPaymentFiles] = useState<File[]>([])
  const [paymentError, setPaymentError] = useState<string | null>(null)

  const [cancelPaymentTarget, setCancelPaymentTarget] = useState<PurchaseOrderPayment | null>(null)
  const [cancelPaymentError, setCancelPaymentError] = useState<string | null>(null)

  const [receiveQuantities, setReceiveQuantities] = useState<Record<number, string>>({})
  const [createReceiptFiles, setCreateReceiptFiles] = useState<File[]>([])
  const [createReceiptBusy, setCreateReceiptBusy] = useState(false)
  const [createReceiptError, setCreateReceiptError] = useState<string | null>(null)

  const [expandedReceipt, setExpandedReceipt] = useState<number | null>(null)
  const [postReceiptBusy, setPostReceiptBusy] = useState(false)
  const [postReceiptError, setPostReceiptError] = useState<string | null>(null)

  const [cancelReceiptTarget, setCancelReceiptTarget] = useState<PurchaseOrderReceipt | null>(null)
  const [cancelReceiptBusy, setCancelReceiptBusy] = useState(false)
  const [cancelReceiptError, setCancelReceiptError] = useState<string | null>(null)

  const [reverseReceiptTarget, setReverseReceiptTarget] = useState<PurchaseOrderReceipt | null>(null)
  const [reverseReceiptError, setReverseReceiptError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    reset,
    setError: setFieldError,
    formState: { errors, isSubmitting },
  } = useForm<PoFormValues>({ resolver: zodResolver(poSchema), defaultValues: emptyPoDefaults })

  const lineForm = useForm<LineFormValues>({ resolver: zodResolver(lineSchema), defaultValues: emptyLineDefaults })
  const cancelForm = useForm<CancelFormValues>({ resolver: zodResolver(cancelSchema), defaultValues: { cancel_reason: '' } })
  const paymentForm = useForm<PaymentFormValues>({ resolver: zodResolver(paymentSchema), defaultValues: emptyPaymentDefaults })
  const cancelPaymentForm = useForm<CancelPaymentFormValues>({
    resolver: zodResolver(cancelPaymentSchema),
    defaultValues: { reason: '' },
  })
  const createReceiptForm = useForm<CreateReceiptFormValues>({
    resolver: zodResolver(createReceiptSchema),
    defaultValues: emptyCreateReceiptDefaults,
  })
  const reverseReceiptForm = useForm<ReverseReceiptFormValues>({
    resolver: zodResolver(reverseReceiptSchema),
    defaultValues: { reason: '' },
  })

  const table = useServerTable<PurchaseOrder, PurchaseOrdersFilters>({
    fetcher: fetchPurchaseOrders,
    pageSize: 20,
    initialFilters: { search: '' },
  })

  const isFirstSearchRender = useRef(true)
  useEffect(() => {
    if (isFirstSearchRender.current) {
      isFirstSearchRender.current = false
      return
    }
    table.setFilters({ search: debouncedSearch })
  }, [debouncedSearch])

  const suppliersById = useMemo(() => new Map(suppliers.map((s) => [s.id, s])), [suppliers])
  const warehousesById = useMemo(() => new Map(warehouses.map((w) => [w.id, w])), [warehouses])
  const materialsById = useMemo(() => new Map(materials.map((m) => [m.id, m])), [materials])
  const unitsById = useMemo(() => new Map(units.map((u) => [u.id, u])), [units])
  const unitCode = (id: number | null) => (id ? unitsById.get(id)?.code ?? '' : '')

  const loadLookups = useCallback(async () => {
    try {
      const [suppliersResponse, warehousesResponse, materialsResponse, unitsResponse] = await Promise.all([
        apiClient.get<PaginatedResponse<LookupOption>>('/api/suppliers', { params: { page_size: 200 } }),
        apiClient.get<PaginatedResponse<LookupOption>>('/api/warehouses', { params: { page_size: 200 } }),
        apiClient.get<PaginatedResponse<LookupOption>>('/api/raw-materials', { params: { page_size: 200 } }),
        apiClient.get<PaginatedResponse<LookupOption>>('/api/units', { params: { page_size: 200 } }),
      ])
      setSuppliers(suppliersResponse.data.data)
      setWarehouses(warehousesResponse.data.data)
      setMaterials(materialsResponse.data.data)
      setUnits(unitsResponse.data.data)
    } catch (err) {
      setPageError(err instanceof ApiError ? err.message : 'Failed to load suppliers, warehouses, and raw materials.')
    }
  }, [])

  useEffect(() => {
    void loadLookups()
  }, [loadLookups])

  // Arriving from an RFQ's PO generation (or "View Purchase Order"):
  // open that PO straight away, then clear the state so a refresh or
  // back-navigation doesn't reopen it.
  const location = useLocation()
  const navigate = useNavigate()
  const openPurchaseOrderId = (location.state as { openPurchaseOrderId?: number } | null)?.openPurchaseOrderId
  useEffect(() => {
    if (!openPurchaseOrderId) return
    navigate(location.pathname, { replace: true, state: null })
    apiClient
      .get<PurchaseOrder>(`/api/purchase-orders/${openPurchaseOrderId}`)
      .then(({ data }) => openDetail(data))
      .catch((err) => setPageError(err instanceof ApiError ? err.message : 'Failed to open the purchase order.'))
  }, [openPurchaseOrderId])

  function openCreate() {
    reset(emptyPoDefaults)
    setFormError(null)
    setFormOpen(true)
  }

  const onFormSubmit = useCallback(
    async (values: PoFormValues) => {
      setFormError(null)
      try {
        const { data } = await apiClient.post<PurchaseOrder>('/api/purchase-orders', {
          supplier_id: Number(values.supplier_id),
          warehouse_id: Number(values.warehouse_id),
          expected_delivery_date: values.expected_delivery_date,
          payment_terms: values.payment_terms.trim(),
          currency: values.currency.trim().toUpperCase(),
          supplier_reference: values.supplier_reference || null,
          delivery_instructions: values.delivery_instructions || null,
          notes: values.notes || null,
        })
        setFormOpen(false)
        table.refetch()
        openDetail(data)
      } catch (err) {
        if (err instanceof ApiError) {
          if (err.fields) {
            for (const [field, message] of Object.entries(err.fields)) {
              if (field in emptyPoDefaults) setFieldError(field as keyof PoFormValues, { message })
            }
          }
          setFormError(err.message)
        } else {
          setFormError('Something went wrong. Please try again.')
        }
      }
    },
    [setFieldError, table],
  )

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
    setDetailTarget(po)
    setDetailError(null)
    setLineFormOpen(false)
    setPaymentFormOpen(false)
    setReceiveQuantities({})
    setCreateReceiptFiles([])
    setCreateReceiptError(null)
    createReceiptForm.reset(emptyCreateReceiptDefaults)
    setExpandedRevision(null)
    setExpandedReceipt(null)
    setPostReceiptError(null)
  }

  function closeDetail() {
    setDetailTarget(null)
  }

  function openAddLine() {
    lineForm.reset(emptyLineDefaults)
    setLineFormOpen(true)
  }

  function onMaterialChosen(materialId: string) {
    // Purchase UOM defaults from the item master; price from its reference cost.
    const material = materialsById.get(Number(materialId))
    lineForm.setValue('unit_of_measure_id', material?.unit_of_measure_id ? String(material.unit_of_measure_id) : '')
    if (material?.reference_cost) lineForm.setValue('unit_price', String(Number(material.reference_cost)))
  }

  const onLineFormSubmit = useCallback(
    async (values: LineFormValues) => {
      if (!detailTarget) return
      setDetailError(null)
      try {
        await apiClient.post(`/api/purchase-orders/${detailTarget.id}/lines`, {
          raw_material_id: Number(values.raw_material_id),
          quantity: values.quantity,
          unit_of_measure_id: Number(values.unit_of_measure_id),
          unit_price: values.unit_price,
          required_by_date: values.required_by_date || null,
          remarks: values.remarks || null,
        })
        setLineFormOpen(false)
        await refreshDetail(detailTarget.id)
      } catch (err) {
        setDetailError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
      }
    },
    [detailTarget, refreshDetail],
  )

  async function removeLine(line: PurchaseOrderLine) {
    if (!detailTarget) return
    setDetailError(null)
    try {
      await apiClient.delete(`/api/purchase-orders/${detailTarget.id}/lines/${line.id}`)
      await refreshDetail(detailTarget.id)
    } catch (err) {
      setDetailError(err instanceof ApiError ? err.message : 'Failed to remove line.')
    }
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

  function openRecordPayment() {
    paymentForm.reset(emptyPaymentDefaults)
    setPaymentFiles([])
    setPaymentError(null)
    setPaymentFormOpen(true)
  }

  const onPaymentSubmit = useCallback(
    async (values: PaymentFormValues) => {
      if (!detailTarget) return
      setPaymentError(null)
      try {
        const fileIds: number[] = []
        for (const file of paymentFiles) {
          const form = new FormData()
          form.append('upload', file)
          const { data } = await apiClient.post<{ id: number }>('/api/files', form)
          fileIds.push(data.id)
        }
        await apiClient.post(`/api/purchase-orders/${detailTarget.id}/payments`, {
          payment_date: values.payment_date,
          amount: values.amount,
          payment_method: values.payment_method || null,
          reference_number: values.reference_number || null,
          notes: values.notes || null,
          file_ids: fileIds,
        })
        setPaymentFormOpen(false)
        await refreshDetail(detailTarget.id)
      } catch (err) {
        setPaymentError(err instanceof ApiError ? err.message : 'Failed to record payment.')
      }
    },
    [detailTarget, paymentFiles, refreshDetail],
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

  const onCreateReceiptSubmit = useCallback(
    async (values: CreateReceiptFormValues) => {
      if (!detailTarget) return
      const lines = Object.entries(receiveQuantities)
        .filter(([, qty]) => qty && Number(qty) > 0)
        .map(([lineId, qty]) => ({ purchase_order_line_id: Number(lineId), quantity: qty }))
      if (lines.length === 0) {
        setCreateReceiptError('Enter a quantity for at least one line.')
        return
      }
      setCreateReceiptBusy(true)
      setCreateReceiptError(null)
      try {
        const fileIds: number[] = []
        for (const file of createReceiptFiles) {
          const form = new FormData()
          form.append('upload', file)
          const { data } = await apiClient.post<{ id: number }>('/api/files', form)
          fileIds.push(data.id)
        }
        await apiClient.post(`/api/purchase-orders/${detailTarget.id}/receipts`, {
          receipt_date: values.receipt_date,
          supplier_delivery_reference: values.supplier_delivery_reference || null,
          notes: values.notes || null,
          lines,
          file_ids: fileIds,
        })
        setReceiveQuantities({})
        setCreateReceiptFiles([])
        createReceiptForm.reset(emptyCreateReceiptDefaults)
        await refreshDetail(detailTarget.id)
      } catch (err) {
        setCreateReceiptError(err instanceof ApiError ? err.message : 'Failed to create goods receipt.')
      } finally {
        setCreateReceiptBusy(false)
      }
    },
    [createReceiptFiles, createReceiptForm, detailTarget, receiveQuantities, refreshDetail],
  )

  function defaultReceiveQuantity(line: PurchaseOrderLine): string {
    if (receiveQuantities[line.id] !== undefined) return receiveQuantities[line.id]
    const remaining = lineRemaining(line)
    return remaining > 0 ? String(remaining) : ''
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

  const columns: DataTableColumn<PurchaseOrder>[] = [
    { key: 'po_number', label: 'PO Number', render: (po) => po.po_number },
    { key: 'supplier', label: 'Supplier', render: (po) => suppliersById.get(po.supplier_id)?.name ?? `#${po.supplier_id}` },
    { key: 'order_date', label: 'Order Date', hideBelow: 'sm', render: (po) => po.order_date },
    { key: 'expected', label: 'Expected Delivery', hideBelow: 'md', render: (po) => po.expected_delivery_date ?? '—' },
    { key: 'total', label: 'Total', hideBelow: 'md', render: (po) => `${po.total_amount} ${po.currency}` },
    { key: 'status', label: 'Status', render: (po) => <Badge tone={STATUS_TONES[po.status]}>{STATUS_LABELS[po.status]}</Badge> },
    {
      key: 'payment',
      label: 'Payment',
      hideBelow: 'lg',
      render: (po) =>
        ['draft', 'pending_approval', 'cancelled'].includes(po.status) ? '—' : (
          <Badge tone={PAYMENT_STATUS_TONES[po.payment_status]}>{PAYMENT_STATUS_LABELS[po.payment_status]}</Badge>
        ),
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
            options.push({ key: 'receive', label: 'Receive...', onSelect: () => openDetail(po) })
          if (!['draft', 'pending_approval', 'cancelled'].includes(po.status))
            options.push({ key: 'payment', label: 'Payments...', onSelect: () => openDetail(po) })
          if (CANCELLABLE.includes(po.status)) options.push({ key: 'cancel', label: 'Cancel', danger: true, onSelect: () => openCancel(po) })
        }
        return <ActionMenu label={`Actions for ${po.po_number}`} options={options} />
      },
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Purchase Orders"
        subtitle="Draft → Approval → Sent → Payment → Goods Receipt → Inventory."
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

      {canManage && (
        <FormDialog
          open={formOpen}
          title="New Purchase"
          onClose={() => setFormOpen(false)}
          onSubmit={handleSubmit(onFormSubmit)}
          submitting={isSubmitting}
          submitLabel="Create Draft"
        >
          <Alert variant="danger">{formError}</Alert>
          <p className="text-sm text-gold-100/60">PO number and PO date ({todayIso()}) are assigned automatically. Add items after creating the draft.</p>
          <SelectField label="Supplier" required {...register('supplier_id')} error={errors.supplier_id?.message}>
            <option value="">Select a supplier...</option>
            {suppliers.filter((s) => s.is_active).map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </SelectField>
          <SelectField label="Delivery Location" required {...register('warehouse_id')} error={errors.warehouse_id?.message}>
            <option value="">Select a warehouse...</option>
            {warehouses.filter((w) => w.is_active).map((w) => (
              <option key={w.id} value={w.id}>{w.name}</option>
            ))}
          </SelectField>
          <DateField label="Expected Delivery Date" required min={todayIso()} {...register('expected_delivery_date')} error={errors.expected_delivery_date?.message} />
          <TextField label="Payment Terms" required hint="e.g. Advance, 30 days, Payment on delivery." {...register('payment_terms')} error={errors.payment_terms?.message} />
          <TextField label="Currency" required {...register('currency')} error={errors.currency?.message} />
          <TextField label="Supplier Reference" hint="Supplier's quotation / reference number." {...register('supplier_reference')} />
          <TextareaField label="Delivery Instructions" {...register('delivery_instructions')} />
          <TextareaField label="Notes" {...register('notes')} error={errors.notes?.message} />
        </FormDialog>
      )}

      <Modal
        open={!!detailTarget}
        title={detailTarget ? `Purchase Order ${detailTarget.po_number}` : ''}
        size="wide"
        onClose={closeDetail}
        footer={
          <>
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
            <Button variant="secondary" onClick={closeDetail}>Close</Button>
          </>
        }
      >
        {detailTarget && (
          <div className="flex flex-col gap-6">
            <Alert variant="danger">{detailError}</Alert>

            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
              <div><span className="text-gold-100/50">Supplier: </span>{suppliersById.get(detailTarget.supplier_id)?.name ?? `#${detailTarget.supplier_id}`}</div>
              <div><span className="text-gold-100/50">Delivery Location: </span>{warehousesById.get(detailTarget.warehouse_id)?.name ?? `#${detailTarget.warehouse_id}`}</div>
              <div><span className="text-gold-100/50">PO Date: </span>{detailTarget.order_date}</div>
              <div><span className="text-gold-100/50">Expected Delivery: </span>{detailTarget.expected_delivery_date ?? '—'}</div>
              <div><span className="text-gold-100/50">Payment Terms: </span>{detailTarget.payment_terms ?? '—'}</div>
              <div><span className="text-gold-100/50">Currency: </span>{detailTarget.currency}</div>
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
                        {canReceive && <th className="py-2 pr-3">Receive Now</th>}
                        {canManage && detailTarget.status === 'draft' && <th className="py-2"></th>}
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
                              {line.required_by_date && <span className="block text-xs text-gold-100/50">Required by {line.required_by_date}</span>}
                            </td>
                            <td className="py-2 pr-3">{line.quantity}</td>
                            <td className="py-2 pr-3">{unitCode(line.unit_of_measure_id)}</td>
                            <td className="py-2 pr-3">{line.unit_price}</td>
                            <td className="py-2 pr-3">{line.line_total}</td>
                            <td className="py-2 pr-3">{line.received_quantity}</td>
                            <td className="py-2 pr-3">{remaining}</td>
                            {canReceive && (
                              <td className="py-2 pr-3">
                                {remaining > 0 ? (
                                  <input
                                    type="number"
                                    min="0"
                                    max={remaining}
                                    className="w-24 rounded border border-ink-700 bg-ink-900 px-2 py-1 text-sm"
                                    value={defaultReceiveQuantity(line)}
                                    onChange={(e) => setReceiveQuantities((prev) => ({ ...prev, [line.id]: e.target.value }))}
                                  />
                                ) : (
                                  <span className="text-gold-100/40">—</span>
                                )}
                              </td>
                            )}
                            {canManage && detailTarget.status === 'draft' && (
                              <td className="py-2 text-right">
                                <ActionMenu
                                  label={`Actions for ${materialsById.get(line.raw_material_id)?.name ?? 'line'}`}
                                  options={[{ key: 'remove', label: 'Remove', danger: true, onSelect: () => removeLine(line) }]}
                                />
                              </td>
                            )}
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {canManage && detailTarget.status === 'draft' && !lineFormOpen && (
                <Button type="button" variant="secondary" className="mt-2" onClick={openAddLine}>Add Item</Button>
              )}
              {canManage && detailTarget.status === 'draft' && lineFormOpen && (
                <form onSubmit={lineForm.handleSubmit(onLineFormSubmit)} className="mt-2 flex flex-col gap-4 rounded-md border border-ink-700 p-4">
                  <SelectField
                    label="Product / Material"
                    required
                    {...lineForm.register('raw_material_id', { onChange: (e) => onMaterialChosen(e.target.value) })}
                    error={lineForm.formState.errors.raw_material_id?.message}
                  >
                    <option value="">Select a raw material...</option>
                    {materials.filter((m) => m.is_active).map((m) => (
                      <option key={m.id} value={m.id}>{m.name} ({m.code})</option>
                    ))}
                  </SelectField>
                  <TextField label="Quantity" required {...lineForm.register('quantity')} error={lineForm.formState.errors.quantity?.message} />
                  <SelectField label="Purchase UOM" required {...lineForm.register('unit_of_measure_id')} error={lineForm.formState.errors.unit_of_measure_id?.message}>
                    <option value="">Select a unit...</option>
                    {units.filter((u) => u.is_active).map((u) => (
                      <option key={u.id} value={u.id}>{u.code}</option>
                    ))}
                  </SelectField>
                  <TextField label="Unit Price" required hint="Agreed supplier price per unit." {...lineForm.register('unit_price')} error={lineForm.formState.errors.unit_price?.message} />
                  <DateField label="Required By" hint="Only if different from the expected delivery date." {...lineForm.register('required_by_date')} />
                  <TextField label="Specification / Remarks" {...lineForm.register('remarks')} />
                  <div className="flex gap-2">
                    <Button type="submit" isLoading={lineForm.formState.isSubmitting}>Add item</Button>
                    <Button type="button" variant="secondary" onClick={() => setLineFormOpen(false)}>Cancel</Button>
                  </div>
                </form>
              )}

              {canManage && canReceive && (
                <form onSubmit={createReceiptForm.handleSubmit(onCreateReceiptSubmit)} className="mt-4 flex flex-col gap-4 rounded-md border border-ink-700 p-4">
                  <h4 className="text-xs uppercase tracking-wide text-gold-100/50">New Goods Receipt</h4>
                  <Alert variant="danger">{createReceiptError}</Alert>
                  <p className="text-sm text-gold-100/70">
                    Enter what actually arrived in the "Receive Now" column above, then create the receipt as a
                    draft here -- it has no effect on stock until it's posted below.
                  </p>
                  <DateField
                    label="Receipt Date"
                    required
                    {...createReceiptForm.register('receipt_date')}
                    error={createReceiptForm.formState.errors.receipt_date?.message}
                  />
                  <TextField
                    label="Supplier Delivery Reference"
                    hint="Optional -- the supplier's own delivery note / DN number, if available."
                    {...createReceiptForm.register('supplier_delivery_reference')}
                  />
                  <FileUploadField
                    label="Evidence (delivery note, packing slip, photo, etc.)"
                    multiple
                    accept=".pdf,.png,.jpg,.jpeg"
                    value={createReceiptFiles}
                    onChange={setCreateReceiptFiles}
                  />
                  <TextareaField label="Notes" {...createReceiptForm.register('notes')} />
                  <div>
                    <Button type="submit" isLoading={createReceiptBusy}>Create Receipt</Button>
                  </div>
                </form>
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
                          <td className="py-2 pr-3">{receipt.receipt_date}</td>
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
                  <div className="text-sm">
                    <span className="text-gold-100/50">Total </span>{detailTarget.total_amount} {detailTarget.currency}
                    <span className="mx-2 text-gold-100/30">|</span>
                    <span className="text-gold-100/50">Paid </span>{detailTarget.paid_amount}
                    <span className="mx-2 text-gold-100/30">|</span>
                    <span className="text-gold-100/50">Outstanding </span>{detailTarget.outstanding_amount}
                  </div>
                </div>
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
                          <td className="py-2 pr-3">{payment.payment_date}</td>
                          <td className="py-2 pr-3">{payment.amount}</td>
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
                {canManage && !paymentFormOpen && detailTarget.status !== 'cancelled' && (
                  <Button type="button" variant="secondary" className="mt-2" onClick={openRecordPayment}>Record Payment</Button>
                )}
                {canManage && paymentFormOpen && (
                  <form onSubmit={paymentForm.handleSubmit(onPaymentSubmit)} className="mt-2 flex flex-col gap-4 rounded-md border border-ink-700 p-4">
                    <Alert variant="danger">{paymentError}</Alert>
                    <DateField label="Payment Date" required {...paymentForm.register('payment_date')} error={paymentForm.formState.errors.payment_date?.message} />
                    <TextField label="Amount" required {...paymentForm.register('amount')} error={paymentForm.formState.errors.amount?.message} />
                    <TextField label="Payment Method" hint="e.g. Bank Transfer, Cheque, Cash." {...paymentForm.register('payment_method')} />
                    <TextField label="Reference No." {...paymentForm.register('reference_number')} />
                    <FileUploadField label="Attachment" multiple accept=".pdf,.png,.jpg,.jpeg" value={paymentFiles} onChange={setPaymentFiles} />
                    <TextareaField label="Notes" {...paymentForm.register('notes')} />
                    <div className="flex gap-2">
                      <Button type="submit" isLoading={paymentForm.formState.isSubmitting}>Save Payment</Button>
                      <Button type="button" variant="secondary" onClick={() => setPaymentFormOpen(false)}>Cancel</Button>
                    </div>
                  </form>
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
                          <td className="py-2 pr-3">{new Date(revision.issued_at).toLocaleString()}</td>
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
        )}
      </Modal>

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
