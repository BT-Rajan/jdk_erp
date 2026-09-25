import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { InventoryReconciliationPage } from './InventoryReconciliationPage'

const { getMock } = vi.hoisted(() => ({ getMock: vi.fn() }))

vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock } }
})

beforeEach(() => {
  getMock.mockReset()
})

describe('InventoryReconciliationPage', () => {
  it('fetches the report from the reconciliation endpoint and lists each pair', async () => {
    getMock.mockResolvedValue({
      data: {
        pairs_checked: 2,
        mismatches_found: 1,
        pairs: [
          {
            raw_material_id: 1,
            material_name: 'Cement',
            warehouse_id: 5,
            warehouse_name: 'Factory Warehouse',
            ledger_sum: '100.0000',
            quantity_on_hand: '100.0000',
            difference: '0.0000',
            matches: true,
          },
          {
            raw_material_id: 2,
            material_name: 'Sand',
            warehouse_id: 5,
            warehouse_name: 'Factory Warehouse',
            ledger_sum: '77.0000',
            quantity_on_hand: '80.0000',
            difference: '3.0000',
            matches: false,
          },
        ],
      },
    })

    render(<InventoryReconciliationPage />)

    expect(await screen.findByText('Cement')).toBeInTheDocument()
    expect(getMock).toHaveBeenCalledWith('/api/inventory/reconciliation')
    expect(screen.getByText('Sand')).toBeInTheDocument()
    expect(screen.getByText('Matches')).toBeInTheDocument()
    expect(screen.getByText('Mismatch')).toBeInTheDocument()
    expect(screen.getByText('2 pairs checked, 1 mismatch found.')).toBeInTheDocument()
  })

  it('shows a load error when the report fails to load', async () => {
    const { ApiError } = await import('@/lib/apiClient')
    getMock.mockRejectedValue(new ApiError({ code: 'FORBIDDEN', message: 'You do not have permission to view this report.' }, 403))

    render(<InventoryReconciliationPage />)

    expect(await screen.findByText('You do not have permission to view this report.')).toBeInTheDocument()
  })

  it('shows an empty state when there are no snapshots yet', async () => {
    getMock.mockResolvedValue({ data: { pairs_checked: 0, mismatches_found: 0, pairs: [] } })

    render(<InventoryReconciliationPage />)

    expect(await screen.findByText('Nothing to reconcile')).toBeInTheDocument()
  })
})
