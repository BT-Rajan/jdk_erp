import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FinishedGoodsStockPositionPage } from './FinishedGoodsStockPositionPage'

const { getMock } = vi.hoisted(() => ({ getMock: vi.fn() }))

vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock } }
})

const STOCK_POSITIONS = [
  {
    product_id: 1,
    product_code: 'PRD001',
    product_name: 'Widget',
    product_is_active: true,
    category_id: 3,
    category_name: 'Electronics',
    warehouse_id: 5,
    warehouse_name: 'Factory Warehouse',
    unit_of_measure_id: 10,
    unit_code: 'PCS',
    quantity_on_hand: '250.0000',
    status: 'in_stock',
  },
]

const MOVEMENTS = [
  {
    id: 2,
    movement_type: 'adjustment',
    quantity: '-15.0000',
    unit_of_measure_id: 10,
    unit_code: 'PCS',
    resulting_balance: '250.0000',
    reference_type: 'finished_goods_adjustment',
    reference_id: 1,
    created_by_user_id: 1,
    created_by_name: 'Admin Person',
    created_at: '2026-09-25T11:00:00',
  },
  {
    id: 1,
    movement_type: 'production_completion',
    quantity: '265.0000',
    unit_of_measure_id: 10,
    unit_code: 'PCS',
    resulting_balance: '265.0000',
    reference_type: 'test_seed',
    reference_id: 1,
    created_by_user_id: null,
    created_by_name: null,
    created_at: '2026-09-25T10:00:00',
  },
]

beforeEach(() => {
  getMock.mockReset()
})

describe('FinishedGoodsStockPositionPage', () => {
  it('fetches and lists stock positions with product, code, category, warehouse, UOM, quantity, status and active flag', async () => {
    getMock.mockResolvedValue({ data: STOCK_POSITIONS })

    render(<FinishedGoodsStockPositionPage />)

    expect(await screen.findByText('Widget')).toBeInTheDocument()
    expect(getMock).toHaveBeenCalledWith('/api/finished-goods-inventory')
    expect(screen.getByText('PRD001')).toBeInTheDocument()
    expect(screen.getByText('Electronics')).toBeInTheDocument()
    expect(screen.getByText('Factory Warehouse')).toBeInTheDocument()
    expect(screen.getByText('PCS')).toBeInTheDocument()
    expect(screen.getByText('250 PCS')).toBeInTheDocument()
    expect(screen.getByText('In Stock')).toBeInTheDocument()
    expect(screen.getAllByText('Active').length).toBeGreaterThan(0)
  })

  it('shows Out of Stock once quantity on hand is zero', async () => {
    getMock.mockResolvedValue({
      data: [{ ...STOCK_POSITIONS[0], quantity_on_hand: '0.0000', status: 'out_of_stock' }],
    })

    render(<FinishedGoodsStockPositionPage />)

    expect(await screen.findByText('Out of Stock')).toBeInTheDocument()
  })

  it('flags an inactive Product without hiding its stock', async () => {
    getMock.mockResolvedValue({ data: [{ ...STOCK_POSITIONS[0], product_is_active: false }] })

    render(<FinishedGoodsStockPositionPage />)

    expect(await screen.findByText('Widget')).toBeInTheDocument()
    expect(screen.getByText('Inactive')).toBeInTheDocument()
    expect(screen.getByText('250 PCS')).toBeInTheDocument()
  })

  it('shows a Product with no Finished Goods movement yet as No Stock Record, with no warehouse or quantity to view history against', async () => {
    getMock.mockResolvedValue({
      data: [
        {
          product_id: 2,
          product_code: 'PRD-TON',
          product_name: 'Product A',
          product_is_active: true,
          category_id: 3,
          category_name: 'Electronics',
          warehouse_id: null,
          warehouse_name: null,
          unit_of_measure_id: 11,
          unit_code: 'TON',
          quantity_on_hand: null,
          status: 'no_record',
        },
      ],
    })

    render(<FinishedGoodsStockPositionPage />)

    expect(await screen.findByText('Product A')).toBeInTheDocument()
    expect(screen.getByText('No Stock Record')).toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: 'View History' })).not.toBeInTheDocument()
    expect(screen.getByText('No movements yet')).toBeInTheDocument()
  })

  it('shows a load error when stock positions fail to load', async () => {
    const { ApiError } = await import('@/lib/apiClient')
    getMock.mockRejectedValue(new ApiError({ code: 'FORBIDDEN', message: 'You do not have permission to view this.' }, 403))

    render(<FinishedGoodsStockPositionPage />)

    expect(await screen.findByText('You do not have permission to view this.')).toBeInTheDocument()
  })

  it('shows an empty state when no Finished Goods Products exist', async () => {
    getMock.mockResolvedValue({ data: [] })

    render(<FinishedGoodsStockPositionPage />)

    expect(await screen.findByText('No Finished Goods Products yet')).toBeInTheDocument()
  })

  it('opens a movement history drawer for a row, newest first, with the resulting balance', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/finished-goods-inventory') return Promise.resolve({ data: STOCK_POSITIONS })
      if (url === '/api/finished-goods-inventory/movements') return Promise.resolve({ data: MOVEMENTS })
      return Promise.reject(new Error(`Unexpected GET ${url}`))
    })

    render(<FinishedGoodsStockPositionPage />)
    await screen.findByText('Widget')

    await userEvent.click(screen.getByRole('button', { name: 'View History' }))

    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith('/api/finished-goods-inventory/movements', {
        params: { product_id: 1, warehouse_id: 5 },
      }),
    )
    expect(await screen.findByText('Adjustment')).toBeInTheDocument()
    expect(screen.getByText('Production Completion')).toBeInTheDocument()
    expect(screen.getByText(/Balance: 265 PCS/)).toBeInTheDocument()
    expect(screen.getByText(/Balance: 250 PCS/)).toBeInTheDocument()
  })

  it('shows no movements recorded yet when a pair has an empty history', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/finished-goods-inventory') return Promise.resolve({ data: STOCK_POSITIONS })
      if (url === '/api/finished-goods-inventory/movements') return Promise.resolve({ data: [] })
      return Promise.reject(new Error(`Unexpected GET ${url}`))
    })

    render(<FinishedGoodsStockPositionPage />)
    await screen.findByText('Widget')
    await userEvent.click(screen.getByRole('button', { name: 'View History' }))

    expect(await screen.findByText('No movements recorded yet.')).toBeInTheDocument()
  })
})
