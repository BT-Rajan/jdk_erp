import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { DataTable, type DataTableColumn } from './DataTable'
import type { SortState } from './sort'

interface Supplier {
  id: number
  name: string
  balance: number
}

const suppliers: Supplier[] = [
  { id: 1, name: 'Acme Corp', balance: 100 },
  { id: 2, name: 'Globex Inc', balance: 200 },
]

const columns: DataTableColumn<Supplier>[] = [
  { key: 'name', label: 'Name', sortable: true, render: (row) => row.name },
  { key: 'balance', label: 'Balance', sortable: true, align: 'right', render: (row) => row.balance },
]

describe('DataTable', () => {
  it('renders rows via each column render function', () => {
    render(<DataTable columns={columns} rows={suppliers} rowKey={(row) => row.id} />)
    expect(screen.getByText('Acme Corp')).toBeInTheDocument()
    expect(screen.getByText('200')).toBeInTheDocument()
  })

  it('shows a spinner while loading instead of the table', () => {
    render(<DataTable columns={columns} rows={[]} rowKey={(row) => row.id} loading />)
    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('shows an empty state when there are no rows', () => {
    render(<DataTable columns={columns} rows={[]} rowKey={(row) => row.id} emptyTitle="No suppliers" />)
    expect(screen.getByText('No suppliers')).toBeInTheDocument()
  })

  it('shows an error alert without hiding it behind a falsy-children check at the call site', () => {
    render(<DataTable columns={columns} rows={suppliers} rowKey={(row) => row.id} error="Failed to load" />)
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to load')
  })

  it('cycles sort asc -> desc -> unsorted on repeated clicks of the same column', async () => {
    function Fixture() {
      const [sort, setSort] = useState<SortState | null>(null)
      return <DataTable columns={columns} rows={suppliers} rowKey={(row) => row.id} sort={sort} onSortChange={setSort} />
    }
    render(<Fixture />)
    const nameHeader = screen.getByRole('button', { name: /Sort by Name/ })

    await userEvent.click(nameHeader)
    expect(screen.getByRole('button', { name: /currently sorted ascending/ })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /Sort by Name/ }))
    expect(screen.getByRole('button', { name: /currently sorted descending/ })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /Sort by Name/ }))
    expect(screen.queryByRole('button', { name: /currently sorted/ })).not.toBeInTheDocument()
  })

  it('renders pagination only when all pagination props are provided', () => {
    const { rerender } = render(<DataTable columns={columns} rows={suppliers} rowKey={(row) => row.id} />)
    expect(screen.queryByText(/Page \d/)).not.toBeInTheDocument()

    rerender(
      <DataTable columns={columns} rows={suppliers} rowKey={(row) => row.id} page={1} totalPages={3} total={30} onPageChange={vi.fn()} />,
    )
    expect(screen.getByText('Page 1 of 3')).toBeInTheDocument()
  })

  it('hides a column via the column-visibility menu when enabled', async () => {
    render(<DataTable columns={columns} rows={suppliers} rowKey={(row) => row.id} enableColumnVisibility />)
    expect(screen.getByRole('columnheader', { name: /Balance/ })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Choose visible columns' }))
    await userEvent.click(screen.getByRole('checkbox', { name: 'Balance' }))

    expect(screen.queryByRole('columnheader', { name: /Balance/ })).not.toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: /Name/ })).toBeInTheDocument()
  })
})
