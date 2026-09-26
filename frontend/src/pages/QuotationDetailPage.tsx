import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { FormSectionHeading } from '@/components/ui/FormSectionHeading'
import { KeyValue } from '@/components/ui/KeyValue'
import { PageHeader } from '@/components/ui/PageHeader'
import { Spinner } from '@/components/ui/Spinner'
import { TextareaField } from '@/components/forms/TextareaField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { useAuth } from '@/lib/auth/AuthContext'
import { isAdminRole } from '@/lib/auth/roles'
import { formatDate, formatDateTime, formatNumber } from '@/lib/format'
import type { LookupOption, PaginatedResponse } from './rfqShared'
import {
  READINESS_LABELS,
  READINESS_TONES,
  WINDOW_LABELS,
  reasonLabel,
  type FeasibilityCheck,
  type Quotation,
  type Readiness,
} from './quotationShared'

// Windows where an S8 feasibility record carries the operational decision
// (a non-working date is decided by Admin on that record too).
const FEASIBILITY_WINDOWS = new Set(['same_day', 'within_2_working_days', 'not_servable'])
const DECIDABLE_STATES = new Set(['admin_override_required', 'approved', 'rejected'])
const CHECK_STATE_LABELS: Record<string, string> = {
  calculated: 'Calculated',
  admin_override_required: 'Awaiting Admin decision',
  approved: 'Approved by Admin',
  rejected: 'Rejected by Admin',
  not_servable: 'Not servable',
}

function money(value: string, currency: string): string {
  return `${formatNumber(value, { minimumFractionDigits: 3, maximumFractionDigits: 3 })} ${currency}`
}

/** One quotation (`/sales/quotations/:quotationId`): what was quoted, when
 * it is wanted, and the server's current readiness. Every state shown is
 * read from the server; the actions call the server, which enforces who
 * may do what. There is no accept/reject/convert here -- those rules are
 * not decided yet. */
export function QuotationDetailPage() {
  const { quotationId } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const isAdmin = isAdminRole(user?.role)

  const [quotation, setQuotation] = useState<Quotation | null>(null)
  const [readiness, setReadiness] = useState<Readiness | null>(null)
  const [checks, setChecks] = useState<FeasibilityCheck[]>([])
  const [products, setProducts] = useState<LookupOption[]>([])
  const [units, setUnits] = useState<LookupOption[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [decisionReason, setDecisionReason] = useState('')
  const [priceReason, setPriceReason] = useState('')

  const load = useCallback(async () => {
    const base = `/api/quotations/${quotationId}`
    const [q, r, c] = await Promise.all([
      apiClient.get<Quotation>(base),
      // The audited readiness assessment (S9) -- never an unrecorded read.
      apiClient.post<Readiness>(`${base}/readiness`),
      apiClient.get<FeasibilityCheck[]>(`${base}/feasibility-checks`),
    ])
    setQuotation(q.data)
    setReadiness(r.data)
    setChecks(c.data)
  }, [quotationId])

  useEffect(() => {
    load().catch((err) => setLoadError(err instanceof ApiError ? err.message : 'Failed to load the quotation.'))
    Promise.all([
      apiClient.get<PaginatedResponse<LookupOption>>('/api/products', { params: { page_size: 200 } }),
      apiClient.get<PaginatedResponse<LookupOption>>('/api/units-of-measure', { params: { page_size: 200 } }),
    ])
      .then(([p, u]) => {
        setProducts(p.data.data)
        setUnits(u.data.data)
      })
      .catch(() => undefined)
  }, [load])

  const productsById = useMemo(() => new Map(products.map((p) => [p.id, p])), [products])
  const unitsById = useMemo(() => new Map(units.map((u) => [u.id, u])), [units])
  const latestCheck = checks[0] ?? null

  async function act(name: string, action: () => Promise<unknown>) {
    setBusy(name)
    setActionError(null)
    try {
      await action()
      setDecisionReason('')
      setPriceReason('')
      await load()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setBusy(null)
    }
  }

  const runCheck = () => act('check', () => apiClient.post(`/api/quotations/${quotationId}/feasibility-checks`))
  const decide = (decision: 'approved' | 'rejected') =>
    act(decision, () =>
      apiClient.put(`/api/quotations/${quotationId}/feasibility-checks/${latestCheck?.id}/decision`, {
        decision,
        reason: decisionReason,
      }),
    )

  const decidePrice = (decision: 'approved' | 'rejected') =>
    act(`price-${decision}`, () =>
      apiClient.put(`/api/quotations/${quotationId}/price-decision`, { decision, reason: priceReason }),
    )

  if (loadError) {
    return (
      <div className="space-y-6">
        <PageHeader title="Quotation" />
        <Alert variant="danger">{loadError}</Alert>
        <Button variant="secondary" onClick={() => navigate('/sales/quotations')}>Back to Quotations</Button>
      </div>
    )
  }
  if (!quotation || !readiness) return <Spinner />

  const window = readiness.delivery_window
  const canRunCheck = window !== null && FEASIBILITY_WINDOWS.has(window)
  const canDecide = isAdmin && latestCheck !== null && latestCheck.is_current && DECIDABLE_STATES.has(latestCheck.state)

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Quotation ${quotation.quotation_number}`}
        subtitle={quotation.customer_name ?? undefined}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => navigate('/sales/quotations')}>All Quotations</Button>
            {quotation.can_edit && (
              <Button onClick={() => navigate(`/sales/quotations/${quotation.id}/edit`)}>Edit</Button>
            )}
          </div>
        }
      />

      <Alert variant="danger">{actionError}</Alert>

      <Card className="grid grid-cols-1 gap-4 p-6 sm:grid-cols-2 lg:grid-cols-3">
        <KeyValue label="Customer" value={quotation.customer_name ?? '—'} />
        <KeyValue label="Quotation Date" value={formatDate(quotation.quotation_date)} />
        <KeyValue label="Requested Delivery" value={formatDate(quotation.requested_delivery_date)} />
        <KeyValue label="Delivery Window" value={window ? WINDOW_LABELS[window] ?? window : '—'} />
        <KeyValue label="Created By" value={quotation.created_by_name ?? '—'} />
        <KeyValue label="Last Updated" value={formatDateTime(quotation.updated_at)} />
      </Card>

      <Card className="space-y-3 p-6">
        <FormSectionHeading>Readiness</FormSectionHeading>
        <div>
          <Badge tone={READINESS_TONES[readiness.status] ?? 'neutral'}>{READINESS_LABELS[readiness.status] ?? readiness.status}</Badge>
        </div>
        {readiness.reason_codes.length > 0 && (
          <ul className="list-disc space-y-1 pl-5 text-sm text-gold-100/80">
            {readiness.reason_codes.map((code) => (
              <li key={code}>{reasonLabel(code)}</li>
            ))}
          </ul>
        )}
        {readiness.status === 'ready' && (
          <p className="text-sm text-gold-100/60">This quotation is ready for the next Sales decision.</p>
        )}
      </Card>

      {canRunCheck && (
        <Card className="space-y-3 p-6">
          <FormSectionHeading>Feasibility</FormSectionHeading>
          {latestCheck ? (
            <div className="space-y-1 text-sm">
              <div>
                <span className="text-gold-100/50">Last check: </span>
                {formatDateTime(latestCheck.calculated_at)} — {CHECK_STATE_LABELS[latestCheck.state] ?? latestCheck.state}
                {!latestCheck.is_current && <span className="text-warning-500"> (out of date)</span>}
              </div>
              {latestCheck.reason_codes.length > 0 && (
                <div className="text-gold-100/70">{latestCheck.reason_codes.map(reasonLabel).join(' ')}</div>
              )}
              {latestCheck.decision_reason && (
                <div><span className="text-gold-100/50">Admin reason: </span>{latestCheck.decision_reason}</div>
              )}
            </div>
          ) : (
            <p className="text-sm text-gold-100/60">Feasibility has not been checked yet.</p>
          )}
          <div>
            <Button variant="secondary" onClick={runCheck} isLoading={busy === 'check'} disabled={busy !== null}>
              {latestCheck ? 'Re-check Feasibility' : 'Check Feasibility'}
            </Button>
          </div>

          {latestCheck?.is_current && latestCheck.state === 'admin_override_required' && !isAdmin && (
            <Alert variant="warning">An Admin must approve or reject this exception.</Alert>
          )}
          {canDecide && (
            <div className="space-y-2 border-t border-ink-700 pt-3">
              <TextareaField
                label="Admin decision reason"
                required
                value={decisionReason}
                onChange={(e) => setDecisionReason(e.target.value)}
              />
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => decide('approved')} isLoading={busy === 'approved'} disabled={busy !== null || !decisionReason.trim()}>
                  Approve Exception
                </Button>
                <Button variant="danger" onClick={() => decide('rejected')} isLoading={busy === 'rejected'} disabled={busy !== null || !decisionReason.trim()}>
                  Reject Exception
                </Button>
              </div>
            </div>
          )}
        </Card>
      )}

      {quotation.price_approval_required && (
        <Card className="space-y-3 p-6">
          <FormSectionHeading>Price Approval</FormSectionHeading>
          <p className="text-sm">
            <span className="text-gold-100/50">Decision: </span>
            {quotation.price_decision === 'approved'
              ? 'Approved by Admin'
              : quotation.price_decision === 'rejected'
                ? 'Rejected by Admin'
                : 'Awaiting Admin decision'}
            {quotation.price_decision_reason && <span className="text-gold-100/70"> — {quotation.price_decision_reason}</span>}
          </p>
          {!isAdmin && !quotation.price_decision && (
            <Alert variant="warning">An Admin must approve or reject the quoted prices.</Alert>
          )}
          {isAdmin && (
            <div className="space-y-2 border-t border-ink-700 pt-3">
              <TextareaField label="Price decision reason" required value={priceReason} onChange={(e) => setPriceReason(e.target.value)} />
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => decidePrice('approved')} isLoading={busy === 'price-approved'} disabled={busy !== null || !priceReason.trim()}>
                  Approve Prices
                </Button>
                <Button variant="danger" onClick={() => decidePrice('rejected')} isLoading={busy === 'price-rejected'} disabled={busy !== null || !priceReason.trim()}>
                  Reject Prices
                </Button>
              </div>
            </div>
          )}
        </Card>
      )}

      <Card className="space-y-3 p-6">
        <FormSectionHeading>Products</FormSectionHeading>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                <th className="py-2 pr-3">#</th>
                <th className="py-2 pr-3">Product</th>
                <th className="py-2 pr-3 text-right">Quantity</th>
                <th className="py-2 pr-3">Unit</th>
                <th className="py-2 pr-3 text-right">Unit Price</th>
                <th className="py-2 text-right">Amount</th>
              </tr>
            </thead>
            <tbody>
              {quotation.lines.map((line) => (
                <tr key={line.id} className="border-t border-ink-700">
                  <td className="py-2 pr-3">{line.line_number}</td>
                  <td className="py-2 pr-3">
                    {productsById.get(line.product_id)?.name ?? `Product ${line.product_id}`}
                    {line.price_approval_required && <Badge tone="warning" className="ml-2">Price approval</Badge>}
                  </td>
                  <td className="py-2 pr-3 text-right">{formatNumber(line.quantity, { maximumFractionDigits: 4 })}</td>
                  <td className="py-2 pr-3">{unitsById.get(line.unit_of_measure_id)?.code ?? '—'}</td>
                  <td className="py-2 pr-3 text-right">{formatNumber(line.unit_price, { maximumFractionDigits: 4 })}</td>
                  <td className="py-2 text-right">{money(line.line_amount, quotation.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-col items-end gap-1 border-t border-ink-700 pt-3 text-sm">
          <div><span className="text-gold-100/50">Subtotal: </span>{money(quotation.subtotal_amount, quotation.currency)}</div>
          <div className="font-medium"><span className="text-gold-100/50">Total: </span>{money(quotation.total_amount, quotation.currency)}</div>
        </div>
      </Card>
    </div>
  )
}
