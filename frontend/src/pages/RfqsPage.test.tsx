import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RfqFormPage } from './RfqFormPage'
import { RfqsPage } from './RfqsPage'

const { useAuthMock, getMock, postMock, putMock, patchMock } = vi.hoisted(() => ({
  useAuthMock: vi.fn(),
  getMock: vi.fn(),
  postMock: vi.fn(),
  putMock: vi.fn(),
  patchMock: vi.fn(),
}))

vi.mock('@/lib/auth/AuthContext', () => ({ useAuth: useAuthMock }))
vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock, post: postMock, put: putMock, patch: patchMock } }
})

function page<T>(data: T[]) {
  return { data, pagination: { page: 1, page_size: 200, total: data.length, total_pages: 1 } }
}

const SUPPLIERS = [
  { id: 1, name: 'Acme Traders', code: 'SUP0001', is_active: true },
  { id: 2, name: 'Beta Supplies', code: 'SUP0002', is_active: true },
  { id: 3, name: 'Gamma Co', code: 'SUP0003', is_active: true },
]
const MATERIALS = [
  { id: 10, name: 'Cement', code: 'RM001', is_active: true, unit_of_measure_id: 20 },
  { id: 11, name: 'Sand', code: 'RM002', is_active: true, unit_of_measure_id: 20 },
]
const UNITS = [
  { id: 20, name: 'Kilogram', code: 'KG', is_active: true },
  { id: 21, name: 'Metric Tonne', code: 'MT', is_active: true },
]
const WAREHOUSES = [{ id: 5, name: 'Factory Warehouse', code: 'WH-001', is_active: true }]

function response(id: number, invitationId: number, lines: { rfq_line_id: number; unit_price: string; delivery_days?: number }[]) {
  return {
    id,
    invitation_id: invitationId,
    response_received_at: '2026-01-12T10:00:00',
    supplier_quotation_number: null as string | null,
    quotation_date: null,
    valid_until: null,
    payment_terms: null as string | null,
    delivery_terms: null,
    freight_terms: null,
    note: null,
    created_by_user_id: 1,
    lines: lines.map((l, i) => ({ id: id * 10 + i, delivery_days: null, remarks: null, ...l })),
    files: [],
  }
}

const PDF = { id: 90, original_filename: 'RFQ.pdf', mime_type: 'application/pdf', size_bytes: 2048 }

function makeRfq(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    organisation_id: 1,
    rfq_number: '2630001',
    status: 'response_received',
    revision_number: 1,
    priority: 'urgent',
    rfq_date: '2026-01-10',
    required_delivery_date: '2026-09-30',
    requested_by_user_id: 1,
    requested_by_name: 'Admin',
    notes: null,
    cancel_reason: null,
    decided_by_user_id: null,
    decided_at: null,
    decision_note: null,
    selected_response_id: null,
    purchase_order_id: null,
    lines: [
      { id: 100, raw_material_id: 10, quantity: '100.0000', unit_of_measure_id: 20, required_by_date: null, remarks: 'Type 1' },
      { id: 101, raw_material_id: 11, quantity: '2.0000', unit_of_measure_id: 21, required_by_date: null, remarks: null },
    ],
    invitations: [
      {
        id: 1, supplier_id: 1, status: 'quoted', invited_at: '2026-01-10T09:00:00', last_emailed_at: null, pdf_file: PDF,
        responses: [response(1, 1, [{ rfq_line_id: 100, unit_price: '42.0000' }, { rfq_line_id: 101, unit_price: '5.0000', delivery_days: 3 }])],
      },
      {
        id: 2, supplier_id: 2, status: 'quoted', invited_at: '2026-01-10T09:00:00', last_emailed_at: null, pdf_file: PDF,
        responses: [response(2, 2, [{ rfq_line_id: 100, unit_price: '39.5000' }])],
      },
      { id: 3, supplier_id: 3, status: 'sent', invited_at: '2026-01-10T09:00:00', last_emailed_at: null, pdf_file: PDF, responses: [] },
    ],
    acceptance_files: [],
    ...overrides,
  }
}

function mockGets(rfqs: ReturnType<typeof makeRfq>[]) {
  getMock.mockImplementation((url: string) => {
    if (url === '/api/suppliers') return Promise.resolve({ data: page(SUPPLIERS) })
    if (url === '/api/raw-materials') return Promise.resolve({ data: page(MATERIALS) })
    if (url === '/api/units-of-measure') return Promise.resolve({ data: page(UNITS) })
    if (url === '/api/warehouses') return Promise.resolve({ data: page(WAREHOUSES) })
    if (url === '/api/rfqs/next-number') return Promise.resolve({ data: { rfq_number: '2630009' } })
    if (url === '/api/rfqs') return Promise.resolve({ data: page(rfqs) })
    const match = rfqs.find((r) => url === `/api/rfqs/${r.id}`)
    if (match) return Promise.resolve({ data: match })
    return Promise.reject(new Error(`Unexpected GET ${url}`))
  })
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/rfqs" element={<RfqsPage />} />
        <Route path="/rfqs/new" element={<RfqFormPage />} />
        <Route path="/rfqs/:rfqId" element={<RfqsPage />} />
        <Route path="/rfqs/:rfqId/edit" element={<div>Editing RFQ form</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

function renderPage() {
  return renderAt('/rfqs')
}

async function openRfq(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: 'Actions for 2630001' }))
  await user.click(await screen.findByRole('menuitem', { name: 'View' }))
  return screen.findByRole('region', { name: /RFQ 2630001/ })
}

beforeEach(() => {
  useAuthMock.mockReset().mockReturnValue({ user: { id: 1, full_name: 'Admin', role: 'admin' } })
  getMock.mockReset()
  postMock.mockReset()
  putMock.mockReset()
  patchMock.mockReset()
})

describe('RfqsPage', () => {
  it('lists how many invited suppliers have quoted, with dates as DD-MM-YYYY', async () => {
    mockGets([makeRfq()])
    renderPage()
    expect(await screen.findByText('2 of 3 quoted')).toBeInTheDocument()
    expect(screen.getByText('10-01-2026')).toBeInTheDocument()
  })

  it('creates an RFQ: unit defaults from the item, suppliers need 2 letters, submit sends the whole form', async () => {
    mockGets([])
    postMock.mockResolvedValue({ data: makeRfq({ status: 'issued', invitations: [] }) })
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: 'New RFQ' }))
    // The form is its own page, not a dialog.
    expect(await screen.findByRole('heading', { name: 'New RFQ' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'New RFQ' })).not.toBeInTheDocument()
    const modal = document.body
    expect(await within(modal).findByText('2630009')).toBeInTheDocument()
    expect(within(modal).queryByLabelText('Item 1 required by')).not.toBeInTheDocument()
    expect(within(modal).getAllByLabelText(/Required By/)).toHaveLength(1)
    expect(within(modal).queryByLabelText(/Department/)).not.toBeInTheDocument()
    expect(within(modal).queryByLabelText(/Notes/)).not.toBeInTheDocument()

    await user.type(within(modal).getByLabelText(/Required By/), '2099-09-30')
    await user.selectOptions(within(modal).getByLabelText('Item 1 product / material'), '10')
    expect((within(modal).getByLabelText('Item 1 unit') as HTMLSelectElement).value).toBe('20')
    await user.selectOptions(within(modal).getByLabelText('Item 1 unit'), '21')
    await user.type(within(modal).getByLabelText('Item 1 quantity'), '2')

    const supplierInput = within(modal).getByLabelText('Add Supplier')
    await user.type(supplierInput, 'b')
    expect(within(modal).getByText('Type at least 2 letters')).toBeInTheDocument()
    await user.type(supplierInput, 'e')
    await user.click(within(modal).getByRole('option', { name: 'Beta Supplies (SUP0002)' }))
    expect(within(modal).getByText('Beta Supplies')).toBeInTheDocument()

    await user.click(within(modal).getByRole('button', { name: 'Submit & Generate PDF' }))
    expect(postMock).toHaveBeenCalledWith('/api/rfqs', {
      submit: true,
      required_delivery_date: '2099-09-30',
      priority: 'normal',
      supplier_ids: [2],
      lines: [{ raw_material_id: 10, quantity: '2', unit_of_measure_id: 21, remarks: null }],
    })
  })

  it('blocks submit when quantity is zero', async () => {
    mockGets([])
    const user = userEvent.setup()
    renderAt('/rfqs/new')
    await screen.findByRole('heading', { name: 'New RFQ' })
    const modal = document.body
    await user.type(within(modal).getByLabelText(/Required By/), '2099-09-30')
    await user.selectOptions(within(modal).getByLabelText('Item 1 product / material'), '10')
    await user.type(within(modal).getByLabelText('Item 1 quantity'), '0')
    await user.click(within(modal).getByRole('button', { name: 'Save Draft' }))
    expect(within(modal).getByText('Item 1: quantity must be greater than zero.')).toBeInTheDocument()
    expect(postMock).not.toHaveBeenCalled()
  })

  it('shows per-supplier PDF actions and the comparison', async () => {
    mockGets([makeRfq()])
    const user = userEvent.setup()
    renderPage()
    const dialog = await openRfq(user)
    expect(within(dialog).getAllByRole('button', { name: 'Download PDF' })).toHaveLength(3)
    expect(within(dialog).getAllByRole('button', { name: 'Email' })).toHaveLength(3)
    const heading = within(dialog).getByText(/Comparison/)
    const table = heading.parentElement!.querySelector('table')!
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
      'Product / Material', 'Qty', 'Acme Traders', 'Beta Supplies',
    ])
  })

  it('approval requires the supplier document; a different agreed quantity raises a new RFQ instead', async () => {
    mockGets([makeRfq()])
    const newDraft = makeRfq({ id: 2, rfq_number: '2630002', status: 'draft', revision_number: 0, invitations: [] })
    postMock.mockResolvedValue({ data: newDraft })
    const user = userEvent.setup()
    renderPage()
    const dialog = await openRfq(user)
    await user.click(within(dialog).getByRole('button', { name: 'Approve / Reject...' }))
    const decision = await screen.findByRole('dialog', { name: 'Approve or Reject' })
    await user.selectOptions(within(decision).getByLabelText(/^Quotation/), '2')
    await user.click(within(decision).getByRole('button', { name: 'Approve' }))
    expect(within(decision).getByText('Upload the document received from the supplier (PDF or image) to approve.')).toBeInTheDocument()
    expect(patchMock).not.toHaveBeenCalled()

    const agreed = within(decision).getByLabelText('Agreed quantity for Cement')
    await user.clear(agreed)
    await user.type(agreed, '80')
    expect(within(decision).queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
    await user.click(within(decision).getByRole('button', { name: 'Raise New RFQ' }))
    expect(postMock).toHaveBeenCalledWith('/api/rfqs/1/raise-new', { lines: [{ rfq_line_id: 100, quantity: '80' }] })
    expect(await screen.findByText('Editing RFQ form')).toBeInTheDocument()
  })

  it('generates the purchase order pre-filled from the approved quotation', async () => {
    const approved = response(2, 2, [{ rfq_line_id: 100, unit_price: '39.5000' }])
    const rfq = makeRfq({
      status: 'selected', selected_response_id: 2, decided_at: '2026-01-13T10:00:00', required_delivery_date: '2099-09-30',
      acceptance_files: [{ id: 91, original_filename: 'supplier-doc.pdf', mime_type: 'application/pdf', size_bytes: 1000 }],
    })
    rfq.invitations[1].responses = [{ ...approved, payment_terms: '30 days', supplier_quotation_number: 'BQ-9' }]
    mockGets([rfq])
    postMock.mockResolvedValue({ data: { ...rfq, status: 'converted', purchase_order_id: 9 } })
    const user = userEvent.setup()
    renderPage()
    const dialog = await openRfq(user)
    expect(within(dialog).getByText(/supplier-doc.pdf/)).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: 'Generate Purchase Order...' }))
    const convert = await screen.findByRole('dialog', { name: 'Generate Purchase Order' })
    expect((within(convert).getByLabelText('Unit price for Cement') as HTMLInputElement).value).toBe('39.5')
    expect(within(convert).queryByLabelText(/Delivery Location/)).not.toBeInTheDocument()
    await user.click(within(convert).getByLabelText('Include Sand'))
    await user.click(within(convert).getByRole('button', { name: 'Create Purchase Order' }))
    expect(postMock).toHaveBeenCalledWith('/api/rfqs/1/convert-to-po', {
      expected_delivery_date: '2099-09-30',
      payment_terms: '30 days',
      supplier_reference: 'BQ-9',
      notes: null,
      lines: [{ rfq_line_id: 100, unit_price: '39.5' }],
    })
  })
})
