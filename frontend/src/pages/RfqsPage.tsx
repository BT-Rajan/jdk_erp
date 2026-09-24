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
import { formatNumber } from '@/lib/format'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { useServerTable, type ServerTableResult } from '@/lib/useServerTable'

/** Mirrors backend/app/schemas/rfq.py's RfqOut. */
interface RfqFile {
  id: number
  original_filename: string
  mime_type: string
  size_bytes: number
}

interface RfqResponseLine {
  id: number
  rfq_line_id: number
  unit_price: string
  delivery_days: number | null
  remarks: string | null
}

interface RfqResponse {
  id: number
  invitation_id: number
  response_received_at: string
  supplier_quotation_number: string | null
  quotation_date: string | null
  valid_until: string | null
  payment_terms: string | null
  delivery_terms: string | null
  freight_terms: string | null
  note: string | null
  created_by_user_id: number | null
  lines: RfqResponseLine[]
  files: RfqFile[]
}

interface RfqInvitation {
  id: number
  supplier_id: number
  status: 'sent' | 'quoted' | 'declined'
  invited_at: string
  responses: RfqResponse[]
}

interface RfqLine {
  id: number
  raw_material_id: number
  quantity: string
  remarks: string | null
}

interface Rfq {
  id: number
  organisation_id: number
  rfq_number: string
  status: 'draft' | 'issued' | 'response_received' | 'selected' | 'rejected' | 'cancelled' | 'converted'
  priority: 'normal' | 'urgent'
  rfq_date: string
  required_delivery_date: string | null
  team_id: number | null
  requested_by_user_id: number | null
  notes: string | null
  cancel_reason: string | null
  decided_by_user_id: number | null
  decided_at: string | null
  decision_note: string | null
  selected_response_id: number | null
  purchase_order_id: number | null
  lines: RfqLine[]
  invitations: RfqInvitation[]
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
  priority: string
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

const INVITATION_LABELS: Record<RfqInvitation['status'], string> = { sent: 'Awaiting Quote', quoted: 'Quoted', declined: 'Declined' }
const INVITATION_TONES: Record<RfqInvitation['status'], BadgeTone> = { sent: 'info', quoted: 'success', declined: 'neutral' }

const DECIMAL_RE = /^\d+(\.\d+)?$/
const INTEGER_RE = /^\d+$/

function isPositiveDecimal(value: string): boolean {
  return DECIMAL_RE.test(value) && Number(value) > 0
}

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

const rfqSchema = z.object({
  rfq_date: z.string().min(1, 'RFQ date is required'),
  required_delivery_date: z.string(),
  team_id: z.string(),
  priority: z.enum(['normal', 'urgent']),
  notes: z.string(),
})

type RfqFormValues = z.infer<typeof rfqSchema>

const emptyRfqDefaults: RfqFormValues = {
  rfq_date: new Date().toISOString().slice(0, 10),
  required_delivery_date: '',
  team_id: '',
  priority: 'normal',
  notes: '',
}

const lineSchema = z.object({
  raw_material_id: z.string().min(1, 'Raw material is required'),
  quantity: z.string().min(1, 'Quantity is required').refine(isPositiveDecimal, 'Enter a positive number'),
  remarks: z.string(),
})

type LineFormValues = z.infer<typeof lineSchema>

const emptyLineDefaults: LineFormValues = { raw_material_id: '', quantity: '', remarks: '' }

const cancelSchema = z.object({
  cancel_reason: z.string().min(1, 'A reason is required to cancel this RFQ.'),
})

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

const decisionSchema = z
  .object({
    decision: z.enum(['selected', 'rejected']),
    selected_response_id: z.string(),
    note: z.string(),
  })
  .refine((v) => v.decision !== 'selected' || v.selected_response_id !== '', {
    message: 'Choose which supplier response this decision is based on.',
    path: ['selected_response_id'],
  })

type DecisionFormValues = z.infer<typeof decisionSchema>

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

/** Side-by-side read-only comparison (docs/modules/rfq.md #6): RFQ lines
 * down the rows, one column per supplier that has quoted, each cell the
 * supplier's latest quoted unit price (and delivery days). Nothing is
 * ranked, totalled, or highlighted as "best" -- the decision stays
 * entirely the user's. */
function ComparisonTable({
  rfq,
  materialName,
  supplierName,
}: {
  rfq: Rfq
  materialName: (id: number) => string
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
            <th className="py-2 pr-3">Raw Material</th>
            <th className="py-2 pr-3">Qty</th>
            {columns.map(({ invitation, response }) => (
              <th key={invitation.id} className="py-2 pr-3">
                {supplierName(invitation.supplier_id)}
                {rfq.selected_response_id === response.id && (
                  <Badge tone="gold" className="ml-2">Selected</Badge>
                )}
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
              <td className="py-2 pr-3">{formatNumber(line.quantity)}</td>
              {columns.map(({ invitation, response }) => {
                const quoted = response.lines.find((l) => l.rfq_line_id === line.id)
                return (
                  <td key={invitation.id} className="py-2 pr-3">
                    {quoted ? (
                      <>
                        {formatPrice(quoted.unit_price)}
                        {quoted.delivery_days !== null && (
                          <span className="block text-xs text-gold-100/50">{quoted.delivery_days} days</span>
                        )}
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

/** RFQ -> Supplier Invitations -> Responses -> Comparison -> Decision ->
 * Purchase Order (backend/app/api/rfqs.py, docs/modules/rfq.md v2). One
 * list plus a single "RFQ" Modal per row carrying the whole lifecycle,
 * the same reused list-plus-Modal pattern docs/modules/purchase_orders.md
 * #17 established. Inside the Modal, the comparison table comes first
 * once two or more suppliers have quoted, followed by one thread per
 * invited supplier. No document/PDF/email is generated -- "Issue" is a
 * plain status fact (docs/modules/rfq.md #11). */
export function RfqsPage() {
  const { user: currentUser } = useAuth()
  const canManage = isAdminRole(currentUser?.role)
  const navigate = useNavigate()

  const [suppliers, setSuppliers] = useState<LookupOption[]>([])
  const [warehouses, setWarehouses] = useState<LookupOption[]>([])
  const [materials, setMaterials] = useState<LookupOption[]>([])
  const [teams, setTeams] = useState<LookupOption[]>([])
  const [pageError, setPageError] = useState<string | undefined>(undefined)

  const [searchInput, setSearchInput] = useState('')
  const [priorityFilter, setPriorityFilter] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 300)

  const [formOpen, setFormOpen] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const [detailTarget, setDetailTarget] = useState<Rfq | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)

  const [lineFormOpen, setLineFormOpen] = useState(false)
  const [inviteSupplierId, setInviteSupplierId] = useState('')
  const [inviteBusy, setInviteBusy] = useState(false)

  const [issueBusy, setIssueBusy] = useState(false)

  const [cancelTarget, setCancelTarget] = useState<Rfq | null>(null)
  const [cancelError, setCancelError] = useState<string | null>(null)

  const [captureInvitation, setCaptureInvitation] = useState<RfqInvitation | null>(null)
  const [captureLines, setCaptureLines] = useState<Record<number, CaptureLineDraft>>({})
  const [captureFiles, setCaptureFiles] = useState<File[]>([])
  const [captureError, setCaptureError] = useState<string | null>(null)

  const [decisionOpen, setDecisionOpen] = useState(false)
  const [decisionError, setDecisionError] = useState<string | null>(null)

  const [convertOpen, setConvertOpen] = useState(false)
  const [convertWarehouseId, setConvertWarehouseId] = useState('')
  const [convertLines, setConvertLines] = useState<Record<number, ConvertLineDraft>>({})
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
  const captureForm = useForm<CaptureFormValues>({ resolver: zodResolver(captureSchema), defaultValues: emptyCaptureDefaults })
  const decisionForm = useForm<DecisionFormValues>({
    resolver: zodResolver(decisionSchema),
    defaultValues: { decision: 'selected', selected_response_id: '', note: '' },
  })

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
  const teamsById = useMemo(() => new Map(teams.map((t) => [t.id, t])), [teams])

  const supplierName = useCallback((id: number) => suppliersById.get(id)?.name ?? `#${id}`, [suppliersById])
  const materialName = useCallback((id: number) => materialsById.get(id)?.name ?? `#${id}`, [materialsById])

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
    // Department is optional on an RFQ -- a caller without access to the
    // teams list still gets a working page, just without team names.
    try {
      const { data } = await apiClient.get<PaginatedResponse<LookupOption>>('/api/teams', {
        params: { include_inactive: true, page_size: 200 },
      })
      setTeams(data.data)
    } catch {
      setTeams([])
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
          rfq_date: values.rfq_date,
          required_delivery_date: values.required_delivery_date || null,
          team_id: values.team_id ? Number(values.team_id) : null,
          priority: values.priority,
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
    setInviteSupplierId('')
    setCaptureInvitation(null)
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

  async function inviteSupplier() {
    if (!detailTarget || !inviteSupplierId) return
    setInviteBusy(true)
    setDetailError(null)
    try {
      await apiClient.post(`/api/rfqs/${detailTarget.id}/invitations`, { supplier_id: Number(inviteSupplierId) })
      setInviteSupplierId('')
      await refreshDetail(detailTarget.id)
    } catch (err) {
      setDetailError(err instanceof ApiError ? err.message : 'Failed to invite supplier.')
    } finally {
      setInviteBusy(false)
    }
  }

  async function removeInvitation(invitation: RfqInvitation) {
    if (!detailTarget) return
    setDetailError(null)
    try {
      await apiClient.delete(`/api/rfqs/${detailTarget.id}/invitations/${invitation.id}`)
      await refreshDetail(detailTarget.id)
    } catch (err) {
      setDetailError(err instanceof ApiError ? err.message : 'Failed to remove supplier.')
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

  function openCapture(invitation: RfqInvitation) {
    captureForm.reset(emptyCaptureDefaults)
    setCaptureLines({})
    setCaptureFiles([])
    setCaptureError(null)
    setCaptureInvitation(invitation)
  }

  function updateCaptureLine(lineId: number, patch: Partial<CaptureLineDraft>) {
    setCaptureLines((prev) => ({
      ...prev,
      [lineId]: { ...(prev[lineId] ?? { unit_price: '', delivery_days: '', remarks: '' }), ...patch },
    }))
  }

  const onCaptureSubmit = useCallback(
    async (values: CaptureFormValues) => {
      if (!detailTarget || !captureInvitation) return
      const quoted = detailTarget.lines
        .map((line) => ({ line, draft: captureLines[line.id] }))
        .filter(({ draft }) => draft && draft.unit_price.trim() !== '')
      if (quoted.length === 0) {
        setCaptureError('Enter a unit price for at least one line. Leave a line blank if the supplier did not quote it.')
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
        const uploadedIds: number[] = []
        for (const file of captureFiles) {
          const form = new FormData()
          form.append('upload', file)
          const { data } = await apiClient.post<{ id: number }>('/api/files', form)
          uploadedIds.push(data.id)
        }
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
          file_ids: uploadedIds,
        })
        setCaptureInvitation(null)
        await refreshDetail(detailTarget.id)
      } catch (err) {
        setCaptureError(err instanceof ApiError ? err.message : 'Failed to capture response.')
      }
    },
    [captureFiles, captureInvitation, captureLines, detailTarget, refreshDetail],
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

  const selectedResponse = useMemo(() => {
    if (!detailTarget?.selected_response_id) return undefined
    for (const invitation of detailTarget.invitations) {
      const found = invitation.responses.find((r) => r.id === detailTarget.selected_response_id)
      if (found) return { invitation, response: found }
    }
    return undefined
  }, [detailTarget])

  /** Pre-fills every line's price from the selected response
   * (docs/modules/rfq.md #8) -- editable, never locked. */
  function openConvert() {
    if (!detailTarget) return
    const quoted = new Map(selectedResponse?.response.lines.map((l) => [l.rfq_line_id, l.unit_price]) ?? [])
    const drafts: Record<number, ConvertLineDraft> = {}
    for (const line of detailTarget.lines) {
      const price = quoted.get(line.id)
      drafts[line.id] = { include: true, unit_price: price ? String(Number(price)) : '' }
    }
    setConvertLines(drafts)
    setConvertWarehouseId('')
    setConvertError(null)
    setConvertOpen(true)
  }

  async function submitConvert() {
    if (!detailTarget) return
    if (!convertWarehouseId) {
      setConvertError('Select a warehouse to receive into.')
      return
    }
    const included = detailTarget.lines.filter((line) => convertLines[line.id]?.include)
    if (included.length === 0) {
      setConvertError('Include at least one line in the purchase order.')
      return
    }
    const lines = included.map((line) => ({ rfq_line_id: line.id, unit_price: convertLines[line.id].unit_price.trim() }))
    if (lines.some((l) => !isPositiveDecimal(l.unit_price))) {
      setConvertError('Enter a positive unit price for every included line.')
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

  function suppliersSummary(rfq: Rfq): string {
    const invited = rfq.invitations.length
    if (invited === 0) return 'None invited'
    const quoted = rfq.invitations.filter((i) => i.responses.length > 0).length
    return quoted > 0 ? `${quoted} of ${invited} quoted` : `${invited} invited`
  }

  const columns: DataTableColumn<Rfq>[] = [
    { key: 'rfq_number', label: 'RFQ Number', render: (rfq) => rfq.rfq_number },
    {
      key: 'department',
      label: 'Department',
      hideBelow: 'md',
      render: (rfq) => (rfq.team_id ? teamsById.get(rfq.team_id)?.name ?? `#${rfq.team_id}` : '—'),
    },
    { key: 'rfq_date', label: 'Date', hideBelow: 'sm', render: (rfq) => rfq.rfq_date },
    {
      key: 'priority',
      label: 'Priority',
      render: (rfq) => (rfq.priority === 'urgent' ? <Badge tone="danger">Urgent</Badge> : <Badge tone="neutral">Normal</Badge>),
    },
    { key: 'suppliers', label: 'Suppliers', hideBelow: 'md', render: suppliersSummary },
    { key: 'status', label: 'Status', render: (rfq) => <Badge tone={STATUS_TONES[rfq.status]}>{STATUS_LABELS[rfq.status]}</Badge> },
    {
      key: 'po',
      label: 'PO',
      hideBelow: 'lg',
      render: (rfq) => (rfq.purchase_order_id ? <Badge tone="success">Created</Badge> : '—'),
    },
    {
      key: 'actions',
      label: '',
      alwaysVisible: true,
      align: 'right' as const,
      render: (rfq: Rfq) => {
        const options: ActionMenuOption[] = [{ key: 'view', label: 'View', onSelect: () => openDetail(rfq) }]
        if (canManage) {
          if (rfq.status === 'draft') options.push({ key: 'manage', label: 'Materials & Suppliers...', onSelect: () => openDetail(rfq) })
          if (rfq.status === 'issued' || rfq.status === 'response_received')
            options.push({ key: 'capture', label: 'Capture Responses...', onSelect: () => openDetail(rfq) })
          if (rfq.status === 'response_received') options.push({ key: 'decide', label: 'Compare & Decide...', onSelect: () => openDetail(rfq) })
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

  const isDraft = detailTarget?.status === 'draft'
  const isCollecting = detailTarget?.status === 'issued' || detailTarget?.status === 'response_received'
  const quotedCount = detailTarget?.invitations.filter((i) => i.responses.length > 0).length ?? 0
  const invitedSupplierIds = new Set(detailTarget?.invitations.map((i) => i.supplier_id) ?? [])

  return (
    <div className="space-y-6">
      <PageHeader
        title="RFQs"
        subtitle="Request for Quotation → Supplier Responses → Compare → Decision → Purchase Order."
        actions={canManage ? <Button onClick={openCreate}>New RFQ</Button> : undefined}
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

      {canManage && (
        <FormDialog open={formOpen} title="New RFQ" onClose={() => setFormOpen(false)} onSubmit={handleSubmit(onFormSubmit)} submitting={isSubmitting} submitLabel="Create Draft">
          <Alert variant="danger">{formError}</Alert>
          <DateField label="RFQ Date" required {...register('rfq_date')} error={errors.rfq_date?.message} />
          <DateField label="Required Delivery Date" {...register('required_delivery_date')} error={errors.required_delivery_date?.message} />
          <SelectField label="Department" {...register('team_id')} error={errors.team_id?.message}>
            <option value="">No department</option>
            {teams.filter((t) => t.is_active).map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </SelectField>
          <SelectField label="Priority" {...register('priority')} error={errors.priority?.message}>
            <option value="normal">Normal</option>
            <option value="urgent">Urgent</option>
          </SelectField>
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
            {canManage && isDraft && (
              <Button onClick={issueRfq} isLoading={issueBusy} disabled={!detailTarget || detailTarget.lines.length === 0 || detailTarget.invitations.length === 0}>
                Issue
              </Button>
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
              <div><span className="text-gold-100/50">RFQ Date: </span>{detailTarget.rfq_date}</div>
              <div><span className="text-gold-100/50">Required Delivery: </span>{detailTarget.required_delivery_date ?? '—'}</div>
              <div>
                <span className="text-gold-100/50">Department: </span>
                {detailTarget.team_id ? teamsById.get(detailTarget.team_id)?.name ?? `#${detailTarget.team_id}` : '—'}
              </div>
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
                  {detailTarget.selected_response_id && selectedResponse
                    ? `${supplierName(selectedResponse.invitation.supplier_id)} selected`
                    : STATUS_LABELS[detailTarget.status]}{' '}
                  on {new Date(detailTarget.decided_at).toLocaleString()}
                  {detailTarget.decision_note ? ` — ${detailTarget.decision_note}` : ''}
                </div>
              )}
            </div>

            {quotedCount >= 2 && (
              <div>
                <h3 className="mb-2 text-xs uppercase tracking-wide text-gold-100/50">Comparison (latest quote per supplier)</h3>
                <ComparisonTable rfq={detailTarget} materialName={materialName} supplierName={supplierName} />
              </div>
            )}

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
                      <th className="py-2 pr-3">Remarks</th>
                      {canManage && isDraft && <th className="py-2"></th>}
                    </tr>
                  </thead>
                  <tbody>
                    {detailTarget.lines.map((line) => (
                      <tr key={line.id} className="border-t border-ink-700">
                        <td className="py-2 pr-3">{materialName(line.raw_material_id)}</td>
                        <td className="py-2 pr-3">{formatNumber(line.quantity)}</td>
                        <td className="py-2 pr-3">{line.remarks ?? '—'}</td>
                        {canManage && isDraft && (
                          <td className="py-2 text-right">
                            <Button variant="secondary" onClick={() => removeLine(line)}>Remove</Button>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {canManage && isDraft && !lineFormOpen && (
                <Button type="button" variant="secondary" className="mt-2" onClick={openAddLine}>Add Material</Button>
              )}
              {canManage && isDraft && lineFormOpen && (
                <form onSubmit={lineForm.handleSubmit(onLineFormSubmit)} className="mt-2 flex flex-col gap-4 rounded-md border border-ink-700 p-4">
                  <SelectField label="Raw Material" required {...lineForm.register('raw_material_id')} error={lineForm.formState.errors.raw_material_id?.message}>
                    <option value="">Select a raw material...</option>
                    {materials.filter((m) => m.is_active).map((m) => (
                      <option key={m.id} value={m.id}>{m.name} ({m.code})</option>
                    ))}
                  </SelectField>
                  <TextField label="Quantity" required {...lineForm.register('quantity')} error={lineForm.formState.errors.quantity?.message} />
                  <TextField label="Remarks" hint="Optional -- grade, size, quality (e.g. fine washed)." {...lineForm.register('remarks')} />
                  <div className="flex gap-2">
                    <Button type="submit" isLoading={lineForm.formState.isSubmitting}>Add material</Button>
                    <Button type="button" variant="secondary" onClick={() => setLineFormOpen(false)}>Cancel</Button>
                  </div>
                </form>
              )}
            </div>

            <div>
              <h3 className="mb-2 text-xs uppercase tracking-wide text-gold-100/50">Invited Suppliers</h3>
              {detailTarget.invitations.length === 0 ? (
                <p className="text-sm text-gold-100/60">No suppliers invited yet.</p>
              ) : (
                <div className="flex flex-col gap-3">
                  {detailTarget.invitations.map((invitation) => (
                    <div key={invitation.id} className="rounded-md border border-ink-700 p-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{supplierName(invitation.supplier_id)}</span>
                          <Badge tone={INVITATION_TONES[invitation.status]}>{INVITATION_LABELS[invitation.status]}</Badge>
                        </div>
                        {canManage && (
                          <div className="flex gap-2">
                            {isDraft && <Button variant="secondary" onClick={() => removeInvitation(invitation)}>Remove</Button>}
                            {isCollecting && (
                              <Button variant="secondary" onClick={() => openCapture(invitation)}>
                                {invitation.responses.length > 0 ? 'Capture Revised Quote...' : 'Capture Response...'}
                              </Button>
                            )}
                            {isCollecting && invitation.status === 'sent' && (
                              <Button variant="secondary" onClick={() => declineInvitation(invitation)}>Mark Declined</Button>
                            )}
                          </div>
                        )}
                      </div>

                      {invitation.responses.map((response) => (
                        <div
                          key={response.id}
                          className={`mt-3 rounded-md border p-3 ${detailTarget.selected_response_id === response.id ? 'border-gold-400' : 'border-ink-700'}`}
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                            <span>
                              Received {new Date(response.response_received_at).toLocaleString()}
                              {response.supplier_quotation_number && ` · Ref ${response.supplier_quotation_number}`}
                              {response.valid_until && ` · Valid until ${response.valid_until}`}
                            </span>
                            {detailTarget.selected_response_id === response.id && <Badge tone="gold">Selected</Badge>}
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
                          {response.lines.length > 0 && (
                            <table className="mt-2 w-full text-sm">
                              <tbody>
                                {response.lines.map((quoted) => {
                                  const rfqLine = detailTarget.lines.find((l) => l.id === quoted.rfq_line_id)
                                  return (
                                    <tr key={quoted.id} className="border-t border-ink-700">
                                      <td className="py-1 pr-3">{rfqLine ? materialName(rfqLine.raw_material_id) : `Line #${quoted.rfq_line_id}`}</td>
                                      <td className="py-1 pr-3">{formatPrice(quoted.unit_price)}</td>
                                      <td className="py-1 pr-3">{quoted.delivery_days !== null ? `${quoted.delivery_days} days` : '—'}</td>
                                      <td className="py-1 pr-3 text-gold-100/60">{quoted.remarks ?? ''}</td>
                                    </tr>
                                  )
                                })}
                              </tbody>
                            </table>
                          )}
                          {response.note && <p className="mt-1 text-sm text-gold-100/80">{response.note}</p>}
                          {response.files.length > 0 && (
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
                          )}
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              )}
              {canManage && isDraft && (
                <div className="mt-2 flex items-end gap-2">
                  <SelectField label="Invite Supplier" value={inviteSupplierId} onChange={(e) => setInviteSupplierId(e.target.value)}>
                    <option value="">Select a supplier...</option>
                    {suppliers
                      .filter((s) => s.is_active && !invitedSupplierIds.has(s.id))
                      .map((s) => (
                        <option key={s.id} value={s.id}>{s.name}</option>
                      ))}
                  </SelectField>
                  <Button type="button" variant="secondary" onClick={inviteSupplier} isLoading={inviteBusy} disabled={!inviteSupplierId}>
                    Invite
                  </Button>
                </div>
              )}
            </div>
          </div>
        )}
      </Modal>

      <Modal
        open={!!captureInvitation}
        title={captureInvitation ? `Capture Response — ${supplierName(captureInvitation.supplier_id)}` : ''}
        size="wide"
        onClose={() => setCaptureInvitation(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setCaptureInvitation(null)}>Cancel</Button>
            <Button onClick={captureForm.handleSubmit(onCaptureSubmit)} isLoading={captureForm.formState.isSubmitting}>Save Response</Button>
          </>
        }
      >
        {detailTarget && (
          <form className="flex flex-col gap-4">
            <Alert variant="danger">{captureError}</Alert>
            <p className="text-sm text-gold-100/70">Enter the quoted unit price per line. Leave a line blank if the supplier did not quote it.</p>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                  <th className="py-2 pr-3">Raw Material</th>
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
                    <td className="py-2 pr-3">{formatNumber(line.quantity)}</td>
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
              <TextField label="Delivery Terms" {...captureForm.register('delivery_terms')} />
              <TextField label="Freight Terms" placeholder="e.g. included" {...captureForm.register('freight_terms')} />
            </div>
            <FileUploadField label="Attach Supplier Quote (optional)" multiple accept=".pdf,.png,.jpg,.jpeg" value={captureFiles} onChange={setCaptureFiles} />
            <TextareaField label="Note" hint="Optional." {...captureForm.register('note')} />
          </form>
        )}
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
            <option value="selected">Select a supplier response</option>
            <option value="rejected">Reject all</option>
          </SelectField>
          {decisionForm.watch('decision') === 'selected' && (
            <SelectField label="Which response" required {...decisionForm.register('selected_response_id')} error={decisionForm.formState.errors.selected_response_id?.message}>
              <option value="">Select a response...</option>
              {detailTarget?.invitations
                .filter((invitation) => invitation.responses.length > 0)
                .map((invitation) => (
                  <optgroup key={invitation.id} label={supplierName(invitation.supplier_id)}>
                    {invitation.responses.map((response, index) => (
                      <option key={response.id} value={response.id}>
                        {index === invitation.responses.length - 1 ? 'Latest' : `Revision ${index + 1}`} —{' '}
                        {new Date(response.response_received_at).toLocaleString()}
                        {response.supplier_quotation_number ? ` (Ref ${response.supplier_quotation_number})` : ''}
                      </option>
                    ))}
                  </optgroup>
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
            <p className="text-sm text-gold-100/70">
              Supplier{selectedResponse ? ` (${supplierName(selectedResponse.invitation.supplier_id)})` : ''} and requested
              materials/quantities are carried forward automatically. Prices are pre-filled from the selected quote and can be
              changed; lines the supplier did not quote need a price or can be left out.
            </p>
            <SelectField label="Warehouse" required value={convertWarehouseId} onChange={(e) => setConvertWarehouseId(e.target.value)}>
              <option value="">Select a warehouse...</option>
              {warehouses.filter((w) => w.is_active).map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>
              ))}
            </SelectField>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                  <th className="py-2 pr-3">Include</th>
                  <th className="py-2 pr-3">Raw Material</th>
                  <th className="py-2 pr-3">Quantity</th>
                  <th className="py-2 pr-3">Unit Price</th>
                </tr>
              </thead>
              <tbody>
                {detailTarget.lines.map((line) => {
                  const draft = convertLines[line.id] ?? { include: true, unit_price: '' }
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
                      <td className="py-2 pr-3">{formatNumber(line.quantity)}</td>
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
                    </tr>
                  )
                })}
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
