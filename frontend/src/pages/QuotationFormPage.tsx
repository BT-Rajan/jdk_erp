import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { PageHeader } from '@/components/ui/PageHeader'
import { Spinner } from '@/components/ui/Spinner'
import { DateField } from '@/components/forms/DateField'
import { SearchSelectField } from '@/components/forms/SearchSelectField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { isPositiveDecimal, todayIso, type LookupOption, type PaginatedResponse } from './rfqShared'
import type { Quotation } from './quotationShared'

interface ProductOption extends LookupOption {
  unit_of_measure_id: number
  selling_price: string
}

interface LineDraft {
  key: number
  product_id: string
  quantity: string
  unit_price: string
}

let lineKey = 0
function emptyLine(): LineDraft {
  lineKey += 1
  return { key: lineKey, product_id: '', quantity: '', unit_price: '' }
}

/** Client-side hints only -- the server re-validates everything and its
 * message is what the user sees if it disagrees. */
function validate(customerId: string, requestedDate: string, lines: LineDraft[]): string | null {
  if (!customerId) return 'Select a customer.'
  if (!requestedDate) return 'Enter the requested delivery date.'
  if (lines.length === 0) return 'Add at least one product line.'
  for (const [index, line] of lines.entries()) {
    const n = index + 1
    if (!line.product_id) return `Line ${n}: select a product.`
    if (!isPositiveDecimal(line.quantity.trim())) return `Line ${n}: quantity must be greater than zero.`
    if (!isPositiveDecimal(line.unit_price.trim())) return `Line ${n}: unit price must be greater than zero.`
  }
  return null
}

/** New quotation (`/sales/quotations/new`) and edit of a draft
 * (`/sales/quotations/:quotationId/edit`). Sends only customer, requested
 * date and lines; number, date, totals, readiness and approvals are the
 * server's. The unit is always the product's own unit (no conversion). */
export function QuotationFormPage() {
  const { quotationId } = useParams()
  const navigate = useNavigate()

  const [quotation, setQuotation] = useState<Quotation | null>(null)
  const [customers, setCustomers] = useState<LookupOption[]>([])
  const [products, setProducts] = useState<ProductOption[]>([])
  const [units, setUnits] = useState<LookupOption[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [customerId, setCustomerId] = useState('')
  const [requestedDate, setRequestedDate] = useState('')
  const [lines, setLines] = useState<LineDraft[]>([emptyLine()])
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setLoadError(null)
      try {
        const [customersResponse, productsResponse, unitsResponse, quotationResponse] = await Promise.all([
          apiClient.get<PaginatedResponse<LookupOption>>('/api/customers', { params: { page_size: 200 } }),
          apiClient.get<PaginatedResponse<ProductOption>>('/api/products', { params: { page_size: 200 } }),
          apiClient.get<PaginatedResponse<LookupOption>>('/api/units-of-measure', { params: { page_size: 200 } }),
          quotationId ? apiClient.get<Quotation>(`/api/quotations/${quotationId}`) : Promise.resolve(null),
        ])
        if (cancelled) return
        setCustomers(customersResponse.data.data)
        setProducts(productsResponse.data.data)
        setUnits(unitsResponse.data.data)
        const loaded = quotationResponse ? quotationResponse.data : null
        if (loaded && loaded.status !== 'draft') {
          setLoadError(`Quotation ${loaded.quotation_number} can no longer be edited.`)
        }
        setQuotation(loaded)
        if (loaded) {
          setCustomerId(String(loaded.customer_id))
          setRequestedDate(loaded.requested_delivery_date ?? '')
          setLines(
            loaded.lines.map((line) => ({
              ...emptyLine(),
              product_id: String(line.product_id),
              quantity: String(Number(line.quantity)),
              unit_price: String(Number(line.unit_price)),
            })),
          )
        }
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof ApiError ? err.message : 'Failed to load the quotation form.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [quotationId])

  const productsById = useMemo(() => new Map(products.map((p) => [p.id, p])), [products])
  const unitsById = useMemo(() => new Map(units.map((u) => [u.id, u])), [units])
  const customerOptions = useMemo(
    () =>
      customers
        .filter((c) => c.is_active || String(c.id) === customerId)
        .map((c) => ({ value: String(c.id), label: c.code ? `${c.name} (${c.code})` : c.name })),
    [customers, customerId],
  )

  function updateLine(key: number, patch: Partial<LineDraft>) {
    setLines((prev) => prev.map((line) => (line.key === key ? { ...line, ...patch } : line)))
  }

  function selectProduct(key: number, productId: string) {
    // Price defaults from the product's selling price; the unit is always its own.
    const product = productsById.get(Number(productId))
    updateLine(key, { product_id: productId, ...(product ? { unit_price: String(Number(product.selling_price)) } : {}) })
  }

  function unitCode(productId: string): string {
    const product = productsById.get(Number(productId))
    if (!product) return '—'
    return unitsById.get(product.unit_of_measure_id)?.code ?? '—'
  }

  async function save() {
    const problem = validate(customerId, requestedDate, lines)
    if (problem) {
      setError(problem)
      return
    }
    setError(null)
    setSaving(true)
    const body = {
      customer_id: Number(customerId),
      requested_delivery_date: requestedDate,
      lines: lines.map((line) => ({
        product_id: Number(line.product_id),
        quantity: line.quantity.trim(),
        unit_of_measure_id: productsById.get(Number(line.product_id))?.unit_of_measure_id,
        unit_price: line.unit_price.trim(),
      })),
    }
    try {
      const saved = quotation
        ? (await apiClient.patch<Quotation>(`/api/quotations/${quotation.id}`, body)).data
        : (await apiClient.post<Quotation>('/api/quotations', body)).data
      navigate(`/sales/quotations/${saved.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  const title = quotation ? `Edit Quotation ${quotation.quotation_number}` : 'New Quotation'
  const back = () => navigate(quotation ? `/sales/quotations/${quotation.id}` : '/sales/quotations')

  return (
    <div className="space-y-6">
      <PageHeader title={title} subtitle="Customer, requested delivery date and the products quoted. Totals are calculated when you save." />

      {loading ? (
        <Spinner />
      ) : loadError ? (
        <div className="flex flex-col gap-4">
          <Alert variant="danger">{loadError}</Alert>
          <div>
            <Button variant="secondary" onClick={() => navigate('/sales/quotations')}>Back to Quotations</Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-6">
          <Alert variant="danger">{error}</Alert>
          {quotation && (
            <Alert variant="info">
              Changing the customer, requested date or lines means feasibility must be checked again.
            </Alert>
          )}

          <div className="grid gap-4 sm:grid-cols-2">
            <SearchSelectField
              label="Customer"
              required
              placeholder="Type 2 letters of the customer name..."
              minQueryLength={2}
              options={customerOptions}
              value={customerId || null}
              onChange={(value) => setCustomerId(value ?? '')}
            />
            <DateField
              label="Requested Delivery Date"
              required
              min={todayIso()}
              value={requestedDate}
              onChange={(e) => setRequestedDate(e.target.value)}
            />
          </div>

          <div>
            <h3 className="mb-2 text-xs uppercase tracking-wide text-gold-100/50">Products</h3>
            <div className="flex flex-col gap-3">
              {lines.map((line, index) => (
                <div key={line.key} className="grid grid-cols-2 gap-2 rounded border border-ink-700 p-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto_minmax(0,1fr)_auto] sm:items-end">
                  <label className="col-span-2 flex flex-col gap-1 text-xs text-gold-100/60 sm:col-span-1">
                    Product *
                    <select
                      aria-label={`Line ${index + 1} product`}
                      className="rounded border border-ink-700 bg-ink-900 px-2 py-2 text-sm text-gold-100"
                      value={line.product_id}
                      onChange={(e) => selectProduct(line.key, e.target.value)}
                    >
                      <option value="">Select...</option>
                      {products.filter((p) => p.is_active || String(p.id) === line.product_id).map((p) => (
                        <option key={p.id} value={p.id}>{p.name}{p.code ? ` (${p.code})` : ''}</option>
                      ))}
                    </select>
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-gold-100/60">
                    Quantity *
                    <input
                      type="number"
                      inputMode="decimal"
                      min="0"
                      step="any"
                      aria-label={`Line ${index + 1} quantity`}
                      className="rounded border border-ink-700 bg-ink-900 px-2 py-2 text-sm text-gold-100"
                      value={line.quantity}
                      onChange={(e) => updateLine(line.key, { quantity: e.target.value })}
                    />
                  </label>
                  <div className="flex flex-col gap-1 text-xs text-gold-100/60">
                    Unit
                    <span className="py-2 text-sm text-gold-100">{unitCode(line.product_id)}</span>
                  </div>
                  <label className="flex flex-col gap-1 text-xs text-gold-100/60">
                    Unit Price *
                    <input
                      type="number"
                      inputMode="decimal"
                      min="0"
                      step="any"
                      aria-label={`Line ${index + 1} unit price`}
                      className="rounded border border-ink-700 bg-ink-900 px-2 py-2 text-sm text-gold-100"
                      value={line.unit_price}
                      onChange={(e) => updateLine(line.key, { unit_price: e.target.value })}
                    />
                  </label>
                  <div className="col-span-2 flex justify-end sm:col-span-1">
                    <Button
                      variant="secondary"
                      disabled={lines.length === 1}
                      onClick={() => setLines((prev) => prev.filter((l) => l.key !== line.key))}
                    >
                      Remove
                    </Button>
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-3">
              <Button variant="secondary" onClick={() => setLines((prev) => [...prev, emptyLine()])}>Add Product</Button>
            </div>
          </div>

          <div className="flex flex-wrap justify-end gap-2 border-t border-ink-700 pt-4">
            <Button variant="secondary" onClick={back}>Cancel</Button>
            <Button onClick={save} isLoading={saving} disabled={saving}>Save Quotation</Button>
          </div>
        </div>
      )}
    </div>
  )
}
