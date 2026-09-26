import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { DataTable, type DataTableColumn } from '@/components/ui/DataTable'
import { FilterBar } from '@/components/ui/FilterBar'
import { PageHeader } from '@/components/ui/PageHeader'
import { TextField } from '@/components/forms/TextField'
import { apiClient } from '@/lib/apiClient'
import { formatDate, formatNumber } from '@/lib/format'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { useServerTable, type ServerTableResult } from '@/lib/useServerTable'
import type { PaginatedResponse } from './rfqShared'
import { ORDER_STATUS_LABELS, ORDER_STATUS_TONES, type SalesOrder } from './quotationShared'

interface Filters {
  search: string
}

async function fetchOrders({
  page,
  pageSize,
  filters,
}: {
  page: number
  pageSize: number
  filters: Filters
}): Promise<ServerTableResult<SalesOrder>> {
  const { data } = await apiClient.get<PaginatedResponse<SalesOrder>>('/api/sales-orders', {
    params: { page, page_size: pageSize, q: filters.search || undefined },
  })
  return { rows: data.data, total: data.pagination.total }
}

/** Sales -> Sales Orders (backend/app/api/sales_orders.py). Orders are
 * created from an accepted quotation; the server returns only orders
 * whose customer is in the caller's scope. */
export function SalesOrdersPage() {
  const navigate = useNavigate()
  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 300)
  const fetcher = useCallback(fetchOrders, [])
  const table = useServerTable<SalesOrder, Filters>({ fetcher, pageSize: 20, initialFilters: { search: '' } })

  const isFirstSearch = useRef(true)
  useEffect(() => {
    if (isFirstSearch.current) {
      isFirstSearch.current = false
      return
    }
    table.setFilters({ search: debouncedSearch })
  }, [debouncedSearch])

  const open = (order: SalesOrder) => navigate(`/sales/orders/${order.id}`)
  const columns: DataTableColumn<SalesOrder>[] = [
    {
      key: 'order_number',
      label: 'Order',
      alwaysVisible: true,
      render: (o) => (
        <button type="button" className="font-medium text-gold-300 underline-offset-2 hover:underline" onClick={() => open(o)}>
          {o.order_number}
        </button>
      ),
    },
    { key: 'customer', label: 'Customer', render: (o) => o.customer_name ?? '—' },
    { key: 'quotation', label: 'Quotation', hideBelow: 'md', render: (o) => o.quotation_number ?? '—' },
    { key: 'order_date', label: 'Order Date', hideBelow: 'md', render: (o) => formatDate(o.order_date) },
    { key: 'requested', label: 'Requested Delivery', hideBelow: 'sm', render: (o) => formatDate(o.requested_delivery_date) },
    {
      key: 'total',
      label: 'Total',
      align: 'right',
      render: (o) => `${formatNumber(o.total_amount, { minimumFractionDigits: 3, maximumFractionDigits: 3 })} ${o.currency}`,
    },
    {
      key: 'status',
      label: 'Status',
      render: (o) => <Badge tone={ORDER_STATUS_TONES[o.status] ?? 'neutral'}>{ORDER_STATUS_LABELS[o.status] ?? o.status}</Badge>,
    },
    {
      key: 'open',
      label: '',
      alwaysVisible: true,
      align: 'right',
      render: (o) => (
        <Button variant="secondary" onClick={() => open(o)}>
          Open
        </Button>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader title="Sales Orders" subtitle="Orders created from accepted quotations." />
      <FilterBar>
        <TextField label="Search" placeholder="Order number or customer..." value={searchInput} onChange={(e) => setSearchInput(e.target.value)} />
      </FilterBar>
      <DataTable
        columns={columns}
        rows={table.rows}
        rowKey={(o) => o.id}
        loading={table.loading}
        error={table.error}
        page={table.page}
        totalPages={table.totalPages}
        total={table.total}
        onPageChange={table.setPage}
        pageSize={table.pageSize}
        onPageSizeChange={table.setPageSize}
        emptyTitle="No sales orders"
        emptyMessage="Create one from an accepted quotation."
      />
    </div>
  )
}
