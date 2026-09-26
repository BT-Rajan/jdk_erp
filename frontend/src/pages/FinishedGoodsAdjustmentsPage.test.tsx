import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { FinishedGoodsAdjustmentsPage } from './FinishedGoodsAdjustmentsPage'

const { getMock, postMock } = vi.hoisted(() => ({ getMock: vi.fn(), postMock: vi.fn() }))

vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock, post: postMock } }
})

const PRODUCTS_RESPONSE = {
  data: [{ id: 1, code: 'PRD001', name: 'Widget', unit_of_measure_id: 10, is_active: true }],
  pagination: { page: 1, page_size: 200, total: 1, total_pages: 1 },
}

const WAREHOUSES_RESPONSE = {
  data: [{ id: 5, code: 'WH-001', name: 'Factory Warehouse', is_active: true }],
  pagination: { page: 1, page_size: 200, total: 1, total_pages: 1 },
}

function adjustmentResult(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 1,
    product_id: 1,
    product_name: 'Widget',
    warehouse_id: 5,
    warehouse_name: 'Factory Warehouse',
    quantity: '5.0000',
    unit_of_measure_id: 10,
    unit_code: 'PCS',
    reason: 'Cycle count correction',
    created_by_user_id: 1,
    created_by_name: 'Admin Person',
    created_at: '2026-09-25T10:00:00',
    quantity_on_hand: '105.0000',
    ...overrides,
  }
}

beforeEach(() => {
  getMock.mockReset()
  postMock.mockReset()
  getMock.mockImplementation((url: string) => {
    if (url === '/api/products') return Promise.resolve({ data: PRODUCTS_RESPONSE })
    if (url === '/api/warehouses') return Promise.resolve({ data: WAREHOUSES_RESPONSE })
    return Promise.reject(new Error(`Unexpected GET ${url}`))
  })
})

async function selectProductAndWarehouse() {
  await userEvent.type(screen.getByRole('combobox', { name: 'Product' }), 'Widget')
  await userEvent.click(screen.getByRole('option', { name: 'Widget (PRD001)' }))
  await userEvent.type(screen.getByRole('combobox', { name: 'Warehouse' }), 'Factory')
  await userEvent.click(screen.getByRole('option', { name: 'Factory Warehouse (WH-001)' }))
}

describe('FinishedGoodsAdjustmentsPage', () => {
  it('loads products and warehouses on mount', async () => {
    render(<MemoryRouter><FinishedGoodsAdjustmentsPage /></MemoryRouter>)
    await waitFor(() => expect(getMock).toHaveBeenCalledWith('/api/products', { params: { page_size: 200 } }))
    expect(getMock).toHaveBeenCalledWith('/api/warehouses', { params: { page_size: 200 } })
  })

  it('shows a load error when products/warehouses fail to load', async () => {
    getMock.mockImplementation(() => Promise.reject(new Error('boom')))
    render(<MemoryRouter><FinishedGoodsAdjustmentsPage /></MemoryRouter>)
    expect(await screen.findByText('Failed to load products and warehouses.')).toBeInTheDocument()
  })

  it('rejects submission with no product, warehouse, quantity or reason selected', async () => {
    render(<MemoryRouter><FinishedGoodsAdjustmentsPage /></MemoryRouter>)
    await screen.findByRole('combobox', { name: 'Product' })

    await userEvent.click(screen.getByRole('button', { name: 'Record Adjustment' }))

    expect(await screen.findByText('Select a product.')).toBeInTheDocument()
    expect(screen.getByText('Select a warehouse.')).toBeInTheDocument()
    expect(screen.getByText('Enter a quantity greater than zero.')).toBeInTheDocument()
    expect(screen.getByText('A reason is required.')).toBeInTheDocument()
    expect(postMock).not.toHaveBeenCalled()
  })

  it('posts a positive quantity for Stock In', async () => {
    postMock.mockResolvedValue({ data: adjustmentResult() })
    render(<MemoryRouter><FinishedGoodsAdjustmentsPage /></MemoryRouter>)
    await selectProductAndWarehouse()
    await userEvent.type(screen.getByLabelText('Quantity'), '5')
    await userEvent.type(screen.getByLabelText('Reason'), 'Cycle count correction')
    await userEvent.click(screen.getByRole('button', { name: 'Record Adjustment' }))

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/api/finished-goods-inventory/adjustments', {
        product_id: 1,
        warehouse_id: 5,
        quantity: '5',
        reason: 'Cycle count correction',
      }),
    )
  })

  it('negates the quantity for Stock Out', async () => {
    postMock.mockResolvedValue({ data: adjustmentResult({ quantity: '-3.0000' }) })
    render(<MemoryRouter><FinishedGoodsAdjustmentsPage /></MemoryRouter>)
    await selectProductAndWarehouse()
    await userEvent.selectOptions(screen.getByLabelText('Direction'), 'Stock Out (decrease)')
    await userEvent.type(screen.getByLabelText('Quantity'), '3')
    await userEvent.type(screen.getByLabelText('Reason'), 'Damaged units written off')
    await userEvent.click(screen.getByRole('button', { name: 'Record Adjustment' }))

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        '/api/finished-goods-inventory/adjustments',
        expect.objectContaining({ quantity: '-3' }),
      ),
    )
  })

  it('shows the resulting balance on success and clears the quantity/reason fields', async () => {
    postMock.mockResolvedValue({ data: adjustmentResult() })
    render(<MemoryRouter><FinishedGoodsAdjustmentsPage /></MemoryRouter>)
    await selectProductAndWarehouse()
    await userEvent.type(screen.getByLabelText('Quantity'), '5')
    await userEvent.type(screen.getByLabelText('Reason'), 'Cycle count correction')
    await userEvent.click(screen.getByRole('button', { name: 'Record Adjustment' }))

    expect(await screen.findByText(/New balance: 105 PCS/)).toBeInTheDocument()
    expect(screen.getByLabelText('Quantity')).toHaveValue(null)
    expect(screen.getByLabelText('Reason')).toHaveValue('')
  })

  it('shows the API error message when the adjustment is rejected', async () => {
    const { ApiError } = await import('@/lib/apiClient')
    postMock.mockRejectedValue(
      new ApiError({ code: 'BUSINESS_RULE_ERROR', message: 'This would leave negative Finished Goods stock on hand.' }, 400),
    )
    render(<MemoryRouter><FinishedGoodsAdjustmentsPage /></MemoryRouter>)
    await selectProductAndWarehouse()
    await userEvent.selectOptions(screen.getByLabelText('Direction'), 'Stock Out (decrease)')
    await userEvent.type(screen.getByLabelText('Quantity'), '999')
    await userEvent.type(screen.getByLabelText('Reason'), 'Cycle count correction')
    await userEvent.click(screen.getByRole('button', { name: 'Record Adjustment' }))

    expect(await screen.findByText('This would leave negative Finished Goods stock on hand.')).toBeInTheDocument()
  })
})
