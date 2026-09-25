import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { InventoryOpeningStockPage } from './InventoryOpeningStockPage'

const { getMock, postMock } = vi.hoisted(() => ({ getMock: vi.fn(), postMock: vi.fn() }))

vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock, post: postMock } }
})

const MATERIALS_RESPONSE = {
  data: [{ id: 1, code: 'RM001', name: 'Cement', unit_of_measure_id: 10, is_active: true }],
  pagination: { page: 1, page_size: 200, total: 1, total_pages: 1 },
}

const WAREHOUSES_RESPONSE = {
  data: [{ id: 5, code: 'WH-001', name: 'Factory Warehouse', is_active: true }],
  pagination: { page: 1, page_size: 200, total: 1, total_pages: 1 },
}

function openingStockResult(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 1,
    raw_material_id: 1,
    material_name: 'Cement',
    warehouse_id: 5,
    warehouse_name: 'Factory Warehouse',
    quantity: '100.0000',
    unit_of_measure_id: 10,
    unit_code: 'KG',
    reason: 'Initial physical stock count at go-live',
    created_by_user_id: 1,
    created_by_name: 'Admin Person',
    created_at: '2026-09-25T10:00:00',
    quantity_on_hand: '100.0000',
    ...overrides,
  }
}

beforeEach(() => {
  getMock.mockReset()
  postMock.mockReset()
  getMock.mockImplementation((url: string) => {
    if (url === '/api/raw-materials') return Promise.resolve({ data: MATERIALS_RESPONSE })
    if (url === '/api/warehouses') return Promise.resolve({ data: WAREHOUSES_RESPONSE })
    return Promise.reject(new Error(`Unexpected GET ${url}`))
  })
})

async function selectMaterialAndWarehouse() {
  await userEvent.type(screen.getByRole('combobox', { name: 'Raw Material' }), 'Cement')
  await userEvent.click(screen.getByRole('option', { name: 'Cement (RM001)' }))
  await userEvent.type(screen.getByRole('combobox', { name: 'Warehouse' }), 'Factory')
  await userEvent.click(screen.getByRole('option', { name: 'Factory Warehouse (WH-001)' }))
}

describe('InventoryOpeningStockPage', () => {
  it('loads materials and warehouses on mount', async () => {
    render(<InventoryOpeningStockPage />)
    await waitFor(() => expect(getMock).toHaveBeenCalledWith('/api/raw-materials', { params: { page_size: 200 } }))
    expect(getMock).toHaveBeenCalledWith('/api/warehouses', { params: { page_size: 200 } })
  })

  it('shows a load error when materials/warehouses fail to load', async () => {
    getMock.mockImplementation(() => Promise.reject(new Error('boom')))
    render(<InventoryOpeningStockPage />)
    expect(await screen.findByText('Failed to load raw materials and warehouses.')).toBeInTheDocument()
  })

  it('does not render a Direction field', async () => {
    render(<InventoryOpeningStockPage />)
    await screen.findByRole('combobox', { name: 'Raw Material' })
    expect(screen.queryByLabelText('Direction')).not.toBeInTheDocument()
  })

  it('rejects submission with no material, warehouse, quantity or reason', async () => {
    render(<InventoryOpeningStockPage />)
    await screen.findByRole('combobox', { name: 'Raw Material' })

    await userEvent.click(screen.getByRole('button', { name: 'Record Opening Stock' }))

    expect(await screen.findByText('Select a raw material.')).toBeInTheDocument()
    expect(screen.getByText('Select a warehouse.')).toBeInTheDocument()
    expect(screen.getByText('Enter a quantity greater than zero.')).toBeInTheDocument()
    expect(screen.getByText('A reason/description is required.')).toBeInTheDocument()
    expect(postMock).not.toHaveBeenCalled()
  })

  it('posts the opening stock quantity unsigned', async () => {
    postMock.mockResolvedValue({ data: openingStockResult() })
    render(<InventoryOpeningStockPage />)
    await selectMaterialAndWarehouse()
    await userEvent.type(screen.getByLabelText('Quantity'), '100')
    await userEvent.type(screen.getByLabelText('Reason'), 'Initial physical stock count at go-live')
    await userEvent.click(screen.getByRole('button', { name: 'Record Opening Stock' }))

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/api/inventory/opening-stock', {
        raw_material_id: 1,
        warehouse_id: 5,
        quantity: '100',
        reason: 'Initial physical stock count at go-live',
      }),
    )
  })

  it('shows the resulting balance on success and clears the whole form', async () => {
    postMock.mockResolvedValue({ data: openingStockResult() })
    render(<InventoryOpeningStockPage />)
    await selectMaterialAndWarehouse()
    await userEvent.type(screen.getByLabelText('Quantity'), '100')
    await userEvent.type(screen.getByLabelText('Reason'), 'Initial physical stock count at go-live')
    await userEvent.click(screen.getByRole('button', { name: 'Record Opening Stock' }))

    expect(await screen.findByText(/New balance: 100 KG/)).toBeInTheDocument()
    expect(screen.getByLabelText('Quantity')).toHaveValue(null)
    expect(screen.getByLabelText('Reason')).toHaveValue('')
    expect(screen.getByRole('combobox', { name: 'Raw Material' })).toHaveValue('')
  })

  it('shows the API error message when a duplicate opening stock is rejected', async () => {
    const { ApiError } = await import('@/lib/apiClient')
    postMock.mockRejectedValue(
      new ApiError(
        { code: 'BUSINESS_RULE_ERROR', message: 'This material/warehouse pair already has stock movements.' },
        400,
      ),
    )
    render(<InventoryOpeningStockPage />)
    await selectMaterialAndWarehouse()
    await userEvent.type(screen.getByLabelText('Quantity'), '50')
    await userEvent.type(screen.getByLabelText('Reason'), 'Retry after an earlier mistaken entry')
    await userEvent.click(screen.getByRole('button', { name: 'Record Opening Stock' }))

    expect(await screen.findByText('This material/warehouse pair already has stock movements.')).toBeInTheDocument()
  })
})
