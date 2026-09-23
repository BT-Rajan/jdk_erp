import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { useNavigate } from 'react-router-dom'
import { z } from 'zod'
import { ActionMenu, type ActionMenuOption } from '@/components/ui/ActionMenu'
import { Alert } from '@/components/ui/Alert'
import { Badge, type BadgeTone } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
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

/** Mirrors backend/app/schemas/rfq.py's RfqOut. */
interface RfqFile {
  id: number
  original_filename: string
  mime_type: string
  size_bytes: number
}

interface RfqResponse {
  id: number
  response_received_at: string
  note: string | null
  created_by_user_id: number | null
  files: RfqFile[]
}

interface RfqLine {
  id: number
  raw_material_id: number
  quantity: string
}

interface Rfq {
  id: number
  organisation_id: number
  rfq_number: string
  supplier_id: number
  status: 'draft' | 'issued' | 'response_received' | 'selected' | 'rejected' | 'cancelled' | 'converted'
  rfq_date: string
  required_delivery_date: string | null
  notes: string | null
  cancel_reason: string | null
  decided_by_user_id: number | null
  decided_at: string | null
  decision_note: string | null
  selected_response_id: number | null
  purchase_order_id: number | null
  lines: RfqLine[]
  responses: RfqResponse[]
}

interface LookupOption {
  id: number
  name: string
  code: string | null
  is_active: boolean
}

interface PaginatedResponse<T> {
  data: T[]
  pagination: { page: number; page_size: number; total: number; total_pages: number }
}

interface RfqsFilters {
  search: string
}

const STATUS_LABELS: Record<Rfq['status'], string> = {
  draft: 'Draft',
  issued: 'Issued',
  response_received: 'Response Received',
  selected: 'Selected',
  rejected: 'Rejected',
  cancelled: 'Cancelled',
  converted: 'Converted',
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

const DECIMAL_RE = /^\d+(\.\d+)?$/

const rfqSchema = z.object({
  supplier_id: z.string().min(1, 'Supplier is required'),
  rfq_date: z.string().min(1, 'RFQ date is required'),
  required_delivery_date: z.string(),
  notes: z.string(),
})

type RfqFormValues = z.infer<typeof rfqSchema>

const emptyRfqDefaults: RfqFormValues = {
  supplier_id: '',
  rfq_date: new Date().toISOString().slice(0, 10),
  required_delivery_date: '',
  notes: '',
}

const lineSchema = z.object({
  raw_material_id: z.string().min(1, 'Raw material is required'),
  quantity: z
    .string()
    .min(1, 'Quantity is required')
    .refine((v) => DECIMAL_RE.test(v) && Number(v) > 0, 'Enter a positive number'),
})

type LineFormValues = z.infer<typeof lineSchema>

const emptyLineDefaults: LineFormValues = { raw_material_id: '', quantity: '' }

const cancelSchema = z.object({
  cancel_reason: z.string().min(1, 'A reason is required to cancel this RFQ.'),
})

type CancelFormValues = z.infer<typeof cancelSchema>

const captureSchema = z.object({ note: z.string() })
type CaptureFormValues = z.infer<typeof captureSchema>

const decisionSchema = z
  .object({
    decision: z.enum(['selected', 'rejected']),
    selected_response_id: z.string(),
    note: z.string(),
  })
  .refine((v) => v.decision !== 'selected' || v.selected_response_id !== '', {
    message: 'Choose which response this decision is based on.',
    path: ['selected_response_id'],
  })

type DecisionFormValues = z.infer<typeof decisionSchema>

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
    params: { page, page_size: pageSize, sort_by: sort?.field, sort_direction: sort?.direction, q: filters.search || undefined },
  })
  return { rows: data.data, total: data.pagination.total }
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(0)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

/** RFQ -> Supplier Response -> Decision -> Purchase Order
 * (backend/app/api/rfqs.py, docs/modules/rfq.md). One flat list plus a
 * single "RFQ" Modal per row carrying the whole lifecycle -- lines
 * (editable while draft), captured responses (attachment evidence, not
 * re-typed data), the explicit decision action, and conversion into a
 * Purchase Order with full carry-forward -- the same reused
 * list-plus-Modal pattern docs/modules/purchase_orders.md #17
 * established. No document/PDF/email is generated by this page --
 * "Issue" is a plain status fact (docs/modules/rfq.md #4/#20). */
export function RfqsPage() {
  const { user: currentUser } = useAuth()
  const canManage = isAdminRole(currentUser?.role)
  const navigate = useNavigate()

  const [suppliers, setSuppliers] = useState<LookupOption[]>([])
  const [warehouses, setWarehouses] = useState<LookupOption[]>([])
  const [materials, setMaterials] = useState<LookupOption[]>([])
  const [pageError, setPageError] = useState<string | undefined>(undefined)

  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 300)

  const [formOpen, setFormOpen] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const [detailTarget, setDetailTarget] = useState<Rfq | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)

  const [lineFormOpen, setLineFormOpen] = useState(false)

  const [issueBusy, setIssueBusy] = useState(false)

  const [cancelTarget, setCancelTarget] = useState<Rfq | null>(null)
  const [cancelError, setCancelError] = useState<string | null>(null)

  const [captureOpen, setCaptureOpen] = useState(false)
  const [captureFiles, setCaptureFiles] = useState<File[]>([])
  const [captureError, setCaptureError] = useState<string | null>(null)

  const [decisionOpen, setDecisionOpen] = useState(false)
  const [decisionError, setDecisionError] = useState<string | null>(null)

  const [convertOpen, setConvertOpen] = useState(false)
  const [convertWarehouseId, setConvertWarehouseId] = useState('')
  const [convertPrices, setConvertPrices] = useState<Record<number, string>>({})
  const [convertBusy, setConvertBusy] = useState(false)
  const [convertError, setConvertError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    reset,
    setError: setFieldError,
    formState: { errors, isSubmitting },
  } = useForm<RfqFormValues>({ resolver: zodResolver(rfqSchema), defaultValues: emptyRfqDefaults })

  const lineForm = useForm<LineFormValues>({ resolver: zodResolver(lineSchema), defaultValues: emptyLineDefaults })
  const cancelForm = useForm<CancelFormValues>({ resolver: zodResolver(cancelSchema), defaultValues: { cancel_reason: '' } })
  const captureForm = useForm<CaptureFormValues>({ resolver: zodResolver(captureSchema), defaultValues: { note: '' } })
  const decisionForm = useForm<DecisionFormValues>({
    resolver: zodResolver(decisionSchema),
    defaultValues: { decision: 'selected', selected_response_id: '', note: '' },
  })

  const table = useServerTable<Rfq, RfqsFilters>({ fetcher: fetchRfqs, pageSize: 20, initialFilters: { search: '' } })

  const isFirstSearchRender = useRef(true)
  useEffect(() => {
    if (isFirstSearchRender.current) {
      isFirstSearchRender.current = false
      return
    }
    table.setFilters({ search: debouncedSearch })
  }, [debouncedSearch])

  const suppliersById = useMemo(() => new Map(suppliers.map((s) => [s.id, s])), [suppliers])
  const materialsById = useMemo(() => new Map(materials.map((m) => [m.id, m])), [materials])

  const loadLookups = useCallback(async () => {
    try {
      const [suppliersResponse, warehousesResponse, materialsResponse] = await Promise.all([
        apiClient.get<PaginatedResponse<LookupOption>>('/api/suppliers', { params: { page_size: 200 } }),
        apiClient.get<PaginatedResponse<LookupOption>>('/api/warehouses', { params: { page_size: 200 } }),
        apiClient.get<PaginatedResponse<LookupOption>>('/api/raw-materials', { params: { page_size: 200 } }),
      ])
      setSuppliers(suppliersResponse.data.data)
      setWarehouses(warehousesResponse.data.data)
      setMaterials(materialsResponse.data.data)
    } catch (err) {
      setPageError(err instanceof ApiError ? err.message : 'Failed to load suppliers, warehouses, and raw materials.')
    }
  }, [])

  useEffect(() => {
    void loadLookups()
  }, [loadLookups])

  function openCreate() {
    reset(emptyRfqDefaults)
    setFormError(null)
    setFormOpen(true)
  }

  const onFormSubmit = useCallback(
    async (values: RfqFormValues) => {
      setFormError(null)
      try {
        const { data } = await apiClient.post<Rfq>('/api/rfqs', {
          supplier_id: Number(values.supplier_id),
          rfq_date: values.rfq_date,
          required_delivery_date: values.required_delivery_date || null,
          notes: values.notes || null,
        })
        setFormOpen(false)
        table.refetch()
        openDetail(data)
      } catch (err) {
        if (err instanceof ApiError) {
          if (err.fields) {
            for (const [field, message] of Object.entries(err.fields)) {
              if (field in emptyRfqDefaults) setFieldError(field as keyof RfqFormValues, { message })
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
      const { data } = await apiClient.get<Rfq>(`/api/rfqs/${id}`)
      setDetailTarget(data)
      table.refetch()
      return data
    },
     
    [table],
  )

  function openDetail(rfq: Rfq) {
    setDetailTarget(rfq)
    setDetailError(null)
    setLineFormOpen(false)
    setCaptureOpen(false)
    setDecisionOpen(false)
    setConvertOpen(false)
  }

  function closeDetail() {
    setDetailTarget(null)
  }

  function openAddLine() {
    lineForm.reset(emptyLineDefaults)
    setLineFormOpen(true)
  }

  const onLineFormSubmit = useCallback(
    async (values: LineFormValues) => {
      if (!detailTarget) return
      setDetailError(null)
      try {
        await apiClient.post(`/api/rfqs/${detailTarget.id}/lines`, {
          raw_material_id: Number(values.raw_material_id),
          quantity: values.quantity,
        })
        setLineFormOpen(false)
        await refreshDetail(detailTarget.id)
      } catch (err) {
        setDetailError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
      }
    },
    [detailTarget, refreshDetail],
  )

  async function removeLine(line: RfqLine) {
    if (!detailTarget) return
    setDetailError(null)
    try {
      await apiClient.delete(`/api/rfqs/${detailTarget.id}/lines/${line.id}`)
      await refreshDetail(detailTarget.id)
    } catch (err) {
      setDetailError(err instanceof ApiError ? err.message : 'Failed to remove line.')
    }
  }

  async function issueRfq() {
    if (!detailTarget) return
    setIssueBusy(true)
    setDetailError(null)
    try {
      await apiClient.patch(`/api/rfqs/${detailTarget.id}/status`, { status: 'issued' })
      await refreshDetail(detailTarget.id)
    } catch (err) {
      setDetailError(err instanceof ApiError ? err.message : 'Failed to issue RFQ.')
    } finally {
      setIssueBusy(false)
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

  function openCapture() {
    captureForm.reset({ note: '' })
    setCaptureFiles([])
    setCaptureError(null)
    setCaptureOpen(true)
  }

  const onCaptureSubmit = useCallback(
    async (values: CaptureFormValues) => {
      if (!detailTarget) return
      if (captureFiles.length === 0) {
        setCaptureError('Attach at least one file (PDF, screenshot, photo).')
        return
      }
      setCaptureError(null)
      try {
        const uploadedIds: number[] = []
        for (const file of captureFiles) {
          const form = new FormData()
          form.append('upload', file)
          const { data } = await apiClient.post<{ id: number }>('/api/files', form)
          uploadedIds.push(data.id)
        }
        await apiClient.post(`/api/rfqs/${detailTarget.id}/responses`, {
          file_ids: uploadedIds,
          note: values.note || null,
          response_received_at: new Date().toISOString(),
        })
        setCaptureOpen(false)
        await refreshDetail(detailTarget.id)
      } catch (err) {
        setCaptureError(err instanceof ApiError ? err.message : 'Failed to capture response.')
      }
    },
    [captureFiles, detailTarget, refreshDetail],
  )

  function openDecision() {
    decisionForm.reset({ decision: 'selected', selected_response_id: '', note: '' })
    setDecisionError(null)
    setDecisionOpen(true)
  }

  const onDecisionSubmit = useCallback(
    async (values: DecisionFormValues) => {
      if (!detailTarget) return
      setDecisionError(null)
      try {
        await apiClient.patch(`/api/rfqs/${detailTarget.id}/decision`, {
          decision: values.decision,
          selected_response_id: values.decision === 'selected' ? Number(values.selected_response_id) : null,
          note: values.note || null,
        })
        setDecisionOpen(false)
        await refreshDetail(detailTarget.id)
      } catch (err) {
        setDecisionError(err instanceof ApiError ? err.message : 'Failed to record decision.')
      }
    },
    [detailTarget, refreshDetail],
  )

  function openConvert() {
    setConvertWarehouseId('')
    setConvertPrices({})
    setConvertError(null)
    setConvertOpen(true)
  }

  async function submitConvert() {
    if (!detailTarget) return
    if (!convertWarehouseId) {
      setConvertError('Select a warehouse to receive into.')
      return
    }
    const lines = detailTarget.lines.map((line) => ({ rfq_line_id: line.id, unit_price: convertPrices[line.id] }))
    if (lines.some((l) => !l.unit_price || Number(l.unit_price) <= 0)) {
      setConvertError('Enter a unit price for every line.')
      return
    }
    setConvertBusy(true)
    setConvertError(null)
    try {
      await apiClient.post(`/api/rfqs/${detailTarget.id}/convert-to-po`, { warehouse_id: Number(convertWarehouseId), lines })
      setConvertOpen(false)
      await refreshDetail(detailTarget.id)
    } catch (err) {
      setConvertError(err instanceof ApiError ? err.message : 'Failed to create purchase order.')
    } finally {
      setConvertBusy(false)
    }
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

  const columns: DataTableColumn<Rfq>[] = [
    { key: 'rfq_number', label: 'RFQ Number', render: (rfq) => rfq.rfq_number },
    { key: 'supplier', label: 'Supplier', render: (rfq) => suppliersById.get(rfq.supplier_id)?.name ?? `#${rfq.supplier_id}` },
    { key: 'rfq_date', label: 'Date', hideBelow: 'sm', render: (rfq) => rfq.rfq_date },
    { key: 'responses', label: 'Responses', hideBelow: 'md', render: (rfq) => rfq.responses.length },
    { key: 'status', label: 'Status', render: (rfq) => <Badge tone={STATUS_TONES[rfq.status]}>{STATUS_LABELS[rfq.status]}</Badge> },
    {
      key: 'actions',
      label: '',
      alwaysVisible: true,
      align: 'right' as const,
      render: (rfq: Rfq) => {
        const options: ActionMenuOption[] = [{ key: 'view', label: 'View', onSelect: () => openDetail(rfq) }]
        if (canManage) {
          if (rfq.status === 'draft') options.push({ key: 'manage', label: 'Manage Lines...', onSelect: () => openDetail(rfq) })
          if (rfq.status === 'issued' || rfq.status === 'response_received')
            options.push({ key: 'capture', label: 'Capture Response...', onSelect: () => openDetail(rfq) })
          if (rfq.status === 'response_received') options.push({ key: 'decide', label: 'Make Decision...', onSelect: () => openDetail(rfq) })
          if (rfq.status === 'selected') options.push({ key: 'convert', label: 'Create Purchase Order...', onSelect: () => openDetail(rfq) })
          if (rfq.status === 'converted' && rfq.purchase_order_id)
            options.push({ key: 'po', label: 'View Purchase Order', onSelect: () => navigate('/purchase-orders') })
          if (['draft', 'issued', 'response_received', 'selected'].includes(rfq.status))
            options.push({ key: 'cancel', label: 'Cancel', danger: true, onSelect: () => openCancel(rfq) })
        }
        return <ActionMenu label={`Actions for ${rfq.rfq_number}`} options={options} />
      },
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="RFQs"
        subtitle="Request for Quotation → Supplier Response → Decision → Purchase Order."
        actions={canManage ? <Button onClick={openCreate}>New RFQ</Button> : undefined}
      />

      <Alert variant="danger">{pageError}</Alert>

      <FilterBar>
        <TextField label="Search" placeholder="Search by RFQ number..." value={searchInput} onChange={(e) => setSearchInput(e.target.value)} />
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
        emptyTitle={debouncedSearch ? 'No matching RFQs' : 'No RFQs yet'}
        emptyMessage={
          debouncedSearch ? 'Try a different search term.' : canManage ? 'Create the first RFQ with the New RFQ button above.' : 'No RFQs have been created yet.'
        }
      />

      {canManage && (
        <FormDialog open={formOpen} title="New RFQ" onClose={() => setFormOpen(false)} onSubmit={handleSubmit(onFormSubmit)} submitting={isSubmitting} submitLabel="Create Draft">
          <Alert variant="danger">{formError}</Alert>
          <SelectField label="Supplier" required {...register('supplier_id')} error={errors.supplier_id?.message}>
            <option value="">Select a supplier...</option>
            {suppliers.filter((s) => s.is_active).map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </SelectField>
          <DateField label="RFQ Date" required {...register('rfq_date')} error={errors.rfq_date?.message} />
          <DateField label="Required Delivery Date" {...register('required_delivery_date')} error={errors.required_delivery_date?.message} />
          <TextareaField label="Notes" {...register('notes')} error={errors.notes?.message} />
        </FormDialog>
      )}

      <Modal
        open={!!detailTarget}
        title={detailTarget ? `RFQ ${detailTarget.rfq_number}` : ''}
        size="wide"
        onClose={closeDetail}
        footer={
          <>
            {canManage && detailTarget?.status === 'draft' && (
              <Button onClick={issueRfq} isLoading={issueBusy} disabled={detailTarget.lines.length === 0}>
                Issue
              </Button>
            )}
            {canManage && (detailTarget?.status === 'issued' || detailTarget?.status === 'response_received') && (
              <Button onClick={openCapture}>Capture Response...</Button>
            )}
            {canManage && detailTarget?.status === 'response_received' && <Button onClick={openDecision}>Make Decision...</Button>}
            {canManage && detailTarget?.status === 'selected' && <Button onClick={openConvert}>Create Purchase Order...</Button>}
            {detailTarget?.status === 'converted' && detailTarget.purchase_order_id && (
              <Button variant="secondary" onClick={() => navigate('/purchase-orders')}>
                View Purchase Order
              </Button>
            )}
            <Button variant="secondary" onClick={closeDetail}>Close</Button>
          </>
        }
      >
        {detailTarget && (
          <div className="flex flex-col gap-4">
            <Alert variant="danger">{detailError}</Alert>

            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
              <div><span className="text-gold-100/50">Supplier: </span>{suppliersById.get(detailTarget.supplier_id)?.name ?? `#${detailTarget.supplier_id}`}</div>
              <div><span className="text-gold-100/50">RFQ Date: </span>{detailTarget.rfq_date}</div>
              <div><span className="text-gold-100/50">Required Delivery: </span>{detailTarget.required_delivery_date ?? '—'}</div>
              <div><span className="text-gold-100/50">Status: </span><Badge tone={STATUS_TONES[detailTarget.status]}>{STATUS_LABELS[detailTarget.status]}</Badge></div>
              {detailTarget.notes && <div className="col-span-2"><span className="text-gold-100/50">Notes: </span>{detailTarget.notes}</div>}
              {detailTarget.cancel_reason && <div className="col-span-2"><span className="text-gold-100/50">Cancel Reason: </span>{detailTarget.cancel_reason}</div>}
              {detailTarget.decided_at && (
                <div className="col-span-2">
                  <span className="text-gold-100/50">Decision: </span>
                  {STATUS_LABELS[detailTarget.status]} on {new Date(detailTarget.decided_at).toLocaleString()}
                  {detailTarget.decision_note ? ` — ${detailTarget.decision_note}` : ''}
                </div>
              )}
            </div>

            <div>
              <h3 className="mb-2 text-xs uppercase tracking-wide text-gold-100/50">Requested Materials</h3>
              {detailTarget.lines.length === 0 ? (
                <p className="text-sm text-gold-100/60">No materials requested yet.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                      <th className="py-2 pr-3">Raw Material</th>
                      <th className="py-2 pr-3">Requested Qty</th>
                      {canManage && detailTarget.status === 'draft' && <th className="py-2"></th>}
                    </tr>
                  </thead>
                  <tbody>
                    {detailTarget.lines.map((line) => (
                      <tr key={line.id} className="border-t border-ink-700">
                        <td className="py-2 pr-3">{materialsById.get(line.raw_material_id)?.name ?? `#${line.raw_material_id}`}</td>
                        <td className="py-2 pr-3">{line.quantity}</td>
                        {canManage && detailTarget.status === 'draft' && (
                          <td className="py-2 text-right">
                            <Button variant="secondary" onClick={() => removeLine(line)}>Remove</Button>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {canManage && detailTarget.status === 'draft' && !lineFormOpen && (
                <Button type="button" variant="secondary" className="mt-2" onClick={openAddLine}>Add Material</Button>
              )}
              {canManage && detailTarget.status === 'draft' && lineFormOpen && (
                <form onSubmit={lineForm.handleSubmit(onLineFormSubmit)} className="mt-2 flex flex-col gap-4 rounded-md border border-ink-700 p-4">
                  <SelectField label="Raw Material" required {...lineForm.register('raw_material_id')} error={lineForm.formState.errors.raw_material_id?.message}>
                    <option value="">Select a raw material...</option>
                    {materials.filter((m) => m.is_active).map((m) => (
                      <option key={m.id} value={m.id}>{m.name} ({m.code})</option>
                    ))}
                  </SelectField>
                  <TextField label="Quantity" required {...lineForm.register('quantity')} error={lineForm.formState.errors.quantity?.message} />
                  <div className="flex gap-2">
                    <Button type="submit" isLoading={lineForm.formState.isSubmitting}>Add material</Button>
                    <Button type="button" variant="secondary" onClick={() => setLineFormOpen(false)}>Cancel</Button>
                  </div>
                </form>
              )}
            </div>

            <div>
              <h3 className="mb-2 text-xs uppercase tracking-wide text-gold-100/50">Supplier Response</h3>
              {detailTarget.responses.length === 0 ? (
                <p className="text-sm text-gold-100/60">No response captured yet.</p>
              ) : (
                <div className="flex flex-col gap-3">
                  {detailTarget.responses.map((response) => (
                    <div key={response.id} className={`rounded-md border p-3 ${detailTarget.selected_response_id === response.id ? 'border-gold-400' : 'border-ink-700'}`}>
                      <div className="flex items-center justify-between text-sm">
                        <span>{new Date(response.response_received_at).toLocaleString()}</span>
                        {detailTarget.selected_response_id === response.id && <Badge tone="gold">Selected</Badge>}
                      </div>
                      {response.note && <p className="mt-1 text-sm text-gold-100/80">{response.note}</p>}
                      <div className="mt-2 flex flex-wrap gap-2">
                        {response.files.map((file) => (
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
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </Modal>

      <Modal open={captureOpen} title="Capture Supplier Response" onClose={() => setCaptureOpen(false)} footer={
        <>
          <Button variant="secondary" onClick={() => setCaptureOpen(false)}>Cancel</Button>
          <Button onClick={captureForm.handleSubmit(onCaptureSubmit)} isLoading={captureForm.formState.isSubmitting}>Save Response</Button>
        </>
      }>
        <form className="flex flex-col gap-4">
          <Alert variant="danger">{captureError}</Alert>
          <FileUploadField label="Attach Supplier Response" multiple accept=".pdf,.png,.jpg,.jpeg" value={captureFiles} onChange={setCaptureFiles} />
          <TextareaField label="Note" hint="Optional -- e.g. price/lead time mentioned in the response." {...captureForm.register('note')} />
        </form>
      </Modal>

      <Modal open={decisionOpen} title="Make Decision" onClose={() => setDecisionOpen(false)} footer={
        <>
          <Button variant="secondary" onClick={() => setDecisionOpen(false)}>Cancel</Button>
          <Button onClick={decisionForm.handleSubmit(onDecisionSubmit)} isLoading={decisionForm.formState.isSubmitting}>Record Decision</Button>
        </>
      }>
        <form className="flex flex-col gap-4">
          <Alert variant="danger">{decisionError}</Alert>
          <SelectField label="Outcome" required {...decisionForm.register('decision')}>
            <option value="selected">Select a response</option>
            <option value="rejected">Reject</option>
          </SelectField>
          {decisionForm.watch('decision') === 'selected' && (
            <SelectField label="Which response" required {...decisionForm.register('selected_response_id')} error={decisionForm.formState.errors.selected_response_id?.message}>
              <option value="">Select a response...</option>
              {detailTarget?.responses.map((response) => (
                <option key={response.id} value={response.id}>
                  {new Date(response.response_received_at).toLocaleString()} {response.note ? `— ${response.note}` : ''}
                </option>
              ))}
            </SelectField>
          )}
          <TextareaField label="Note" hint="Optional." {...decisionForm.register('note')} />
        </form>
      </Modal>

      <Modal open={convertOpen} title="Create Purchase Order" size="wide" onClose={() => setConvertOpen(false)} footer={
        <>
          <Button variant="secondary" onClick={() => setConvertOpen(false)}>Cancel</Button>
          <Button onClick={submitConvert} isLoading={convertBusy}>Create Purchase Order</Button>
        </>
      }>
        {detailTarget && (
          <div className="flex flex-col gap-4">
            <Alert variant="danger">{convertError}</Alert>
            <p className="text-sm text-gold-100/70">Supplier and requested materials/quantities are carried forward automatically. Only the warehouse and each line's price need to be entered.</p>
            <SelectField label="Warehouse" required value={convertWarehouseId} onChange={(e) => setConvertWarehouseId(e.target.value)}>
              <option value="">Select a warehouse...</option>
              {warehouses.filter((w) => w.is_active).map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>
              ))}
            </SelectField>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                  <th className="py-2 pr-3">Raw Material</th>
                  <th className="py-2 pr-3">Quantity</th>
                  <th className="py-2 pr-3">Unit Price</th>
                </tr>
              </thead>
              <tbody>
                {detailTarget.lines.map((line) => (
                  <tr key={line.id} className="border-t border-ink-700">
                    <td className="py-2 pr-3">{materialsById.get(line.raw_material_id)?.name ?? `#${line.raw_material_id}`}</td>
                    <td className="py-2 pr-3">{line.quantity}</td>
                    <td className="py-2 pr-3">
                      <input
                        type="number"
                        min="0"
                        step="0.0001"
                        className="w-28 rounded border border-ink-700 bg-ink-900 px-2 py-1 text-sm"
                        value={convertPrices[line.id] ?? ''}
                        onChange={(e) => setConvertPrices((prev) => ({ ...prev, [line.id]: e.target.value }))}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Modal>

      <Modal open={!!cancelTarget} title={`Cancel RFQ ${cancelTarget?.rfq_number ?? ''}`} onClose={() => setCancelTarget(null)} footer={
        <>
          <Button variant="secondary" onClick={() => setCancelTarget(null)}>Keep RFQ</Button>
          <Button variant="danger" onClick={cancelForm.handleSubmit(onCancelSubmit)} isLoading={cancelForm.formState.isSubmitting}>Cancel RFQ</Button>
        </>
      }>
        <form className="flex flex-col gap-4">
          <Alert variant="danger">{cancelError}</Alert>
          <TextareaField label="Reason" required hint="Required to cancel an RFQ." {...cancelForm.register('cancel_reason')} error={cancelForm.formState.errors.cancel_reason?.message} />
        </form>
      </Modal>
    </div>
  )
}
