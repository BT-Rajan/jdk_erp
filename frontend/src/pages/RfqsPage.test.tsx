import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RfqsPage } from './RfqsPage'

const { useAuthMock, getMock, postMock, patchMock, deleteMock } = vi.hoisted(() => ({
  useAuthMock: vi.fn(),
  getMock: vi.fn(),
  postMock: vi.fn(),
  patchMock: vi.fn(),
  deleteMock: vi.fn(),
}))

vi.mock('@/lib/auth/AuthContext', () => ({ useAuth: useAuthMock }))
vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock, post: postMock, patch: patchMock, delete: deleteMock } }
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
  { id: 10, name: 'Cement', code: 'RM001', is_active: true },
  { id: 11, name: 'Sand', code: 'RM002', is_active: true },
]
const WAREHOUSES = [{ id: 5, name: 'Factory Warehouse', code: 'WH-001', is_active: true }]
const TEAMS = [{ id: 7, name: 'Civil Works', code: 'CIV', is_active: true }]

function response(id: number, invitationId: number, lines: { rfq_line_id: number; unit_price: string; delivery_days?: number }[]) {
  return {
    id,
    invitation_id: invitationId,
    response_received_at: '2026-01-12T10:00:00',
    supplier_quotation_number: null,
    quotation_date: null,
    valid_until: null,
    payment_terms: null,
    delivery_terms: null,
    freight_terms: null,
    note: null,
    created_by_user_id: 1,
    lines: lines.map((l, i) => ({ id: id * 10 + i, delivery_days: null, remarks: null, ...l })),
    files: [],
  }
}

function makeRfq(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    organisation_id: 1,
    rfq_number: '2630001',
    status: 'response_received',
    priority: 'urgent',
    rfq_date: '2026-01-10',
    required_delivery_date: null,
    team_id: 7,
    requested_by_user_id: 1,
    notes: null,
    cancel_reason: null,
    decided_by_user_id: null,
    decided_at: null,
    decision_note: null,
    selected_response_id: null,
    purchase_order_id: null,
    lines: [
      { id: 100, raw_material_id: 10, quantity: '100.0000', remarks: 'Type 1' },
      { id: 101, raw_material_id: 11, quantity: '20.0000', remarks: null },
    ],
    invitations: [
      {
        id: 1,
        supplier_id: 1,
        status: 'quoted',
        invited_at: '2026-01-10T09:00:00',
        responses: [response(1, 1, [{ rfq_line_id: 100, unit_price: '42.0000' }, { rfq_line_id: 101, unit_price: '5.0000', delivery_days: 3 }])],
      },
      {
        id: 2,
        supplier_id: 2,
        status: 'quoted',
        invited_at: '2026-01-10T09:00:00',
        responses: [response(2, 2, [{ rfq_line_id: 100, unit_price: '39.5000' }])],
      },
      { id: 3, supplier_id: 3, status: 'sent', invited_at: '2026-01-10T09:00:00', responses: [] },
    ],
    ...overrides,
  }
}

function mockGets(rfq: ReturnType<typeof makeRfq>) {
  getMock.mockImplementation((url: string) => {
    if (url === '/api/suppliers') return Promise.resolve({ data: page(SUPPLIERS) })
    if (url === '/api/raw-materials') return Promise.resolve({ data: page(MATERIALS) })
    if (url === '/api/warehouses') return Promise.resolve({ data: page(WAREHOUSES) })
    if (url === '/api/teams') return Promise.resolve({ data: page(TEAMS) })
    if (url === '/api/rfqs') return Promise.resolve({ data: page([rfq]) })
    if (url === `/api/rfqs/${rfq.id}`) return Promise.resolve({ data: rfq })
    return Promise.reject(new Error(`Unexpected GET ${url}`))
  })
}

function renderPage() {
  return render(
    <MemoryRouter>
      <RfqsPage />
    </MemoryRouter>,
  )
}

async function openRfq(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: 'Actions for 2630001' }))
  await user.click(await screen.findByRole('menuitem', { name: 'View' }))
  return screen.findByRole('dialog', { name: 'RFQ 2630001' })
}

beforeEach(() => {
  useAuthMock.mockReset().mockReturnValue({ user: { id: 1, full_name: 'Admin', role: 'admin' } })
  getMock.mockReset()
  postMock.mockReset()
  patchMock.mockReset()
  deleteMock.mockReset()
})

describe('RfqsPage', () => {
  it('lists department, priority and how many invited suppliers have quoted', async () => {
    mockGets(makeRfq())
    renderPage()

    expect(await screen.findByText('2 of 3 quoted')).toBeInTheDocument()
    expect(await screen.findByText('Civil Works')).toBeInTheDocument()
    expect(screen.getAllByText('Urgent').length).toBeGreaterThan(0)
  })

  it('shows a side-by-side comparison of each supplier quote per line', async () => {
    mockGets(makeRfq())
    const user = userEvent.setup()
    renderPage()
    const dialog = await openRfq(user)

    const heading = within(dialog).getByText(/Comparison/)
    const table = heading.parentElement!.querySelector('table')!
    const headers = within(table).getAllByRole('columnheader').map((h) => h.textContent)
    // Only suppliers that have quoted get a column -- Gamma has not.
    expect(headers).toEqual(['Raw Material', 'Qty', 'Acme Traders', 'Beta Supplies'])

    const [, cementRow, sandRow] = within(table).getAllByRole('row')
    expect(within(cementRow).getByText('42.000')).toBeInTheDocument()
    expect(within(cementRow).getByText('39.500')).toBeInTheDocument()
    expect(within(sandRow).getByText('3 days')).toBeInTheDocument()
    expect(within(sandRow).getByText('Not quoted')).toBeInTheDocument()
  })

  it('pre-fills the purchase order form from the selected response and sends overrides', async () => {
    const rfq = makeRfq({ status: 'selected', selected_response_id: 2, decided_at: '2026-01-13T10:00:00' })
    mockGets(rfq)
    postMock.mockResolvedValue({ data: { ...rfq, status: 'converted', purchase_order_id: 9 } })
    const user = userEvent.setup()
    renderPage()
    const dialog = await openRfq(user)

    await user.click(within(dialog).getByRole('button', { name: 'Create Purchase Order...' }))
    const convert = await screen.findByRole('dialog', { name: 'Create Purchase Order' })

    const cementPrice = within(convert).getByLabelText('Unit price for Cement') as HTMLInputElement
    const sandPrice = within(convert).getByLabelText('Unit price for Sand') as HTMLInputElement
    expect(cementPrice.value).toBe('39.5')
    // Beta did not quote sand -- no default, and it can be left out.
    expect(sandPrice.value).toBe('')

    await user.selectOptions(within(convert).getByLabelText(/Warehouse/), '5')
    await user.click(within(convert).getByLabelText('Include Sand'))
    await user.clear(cementPrice)
    await user.type(cementPrice, '38')
    await user.click(within(convert).getByRole('button', { name: 'Create Purchase Order' }))

    expect(postMock).toHaveBeenCalledWith('/api/rfqs/1/convert-to-po', {
      warehouse_id: 5,
      lines: [{ rfq_line_id: 100, unit_price: '38' }],
    })
  })

  it('captures a structured response against one invitation, skipping blank lines', async () => {
    const rfq = makeRfq({ status: 'issued' })
    mockGets(rfq)
    postMock.mockResolvedValue({ data: rfq })
    const user = userEvent.setup()
    renderPage()
    const dialog = await openRfq(user)

    await user.click(within(dialog).getByRole('button', { name: 'Capture Response...' }))
    const capture = await screen.findByRole('dialog', { name: 'Capture Response — Gamma Co' })
    await user.type(within(capture).getByLabelText('Unit price for Sand'), '4.75')
    await user.type(within(capture).getByLabelText('Delivery days for Sand'), '2')
    await user.click(within(capture).getByRole('button', { name: 'Save Response' }))

    expect(postMock).toHaveBeenCalledWith(
      '/api/rfqs/1/invitations/3/responses',
      expect.objectContaining({
        lines: [{ rfq_line_id: 101, unit_price: '4.75', delivery_days: 2, remarks: null }],
        file_ids: [],
      }),
    )
  })
})
