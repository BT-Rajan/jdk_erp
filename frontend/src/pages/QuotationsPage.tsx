import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { DataTable, type DataTableColumn } from '@/components/ui/DataTable'
import { FilterBar } from '@/components/ui/FilterBar'
import { PageHeader } from '@/components/ui/PageHeader'
import { TextField } from '@/components/forms/TextField'
import { apiClient } from '@/lib/apiClient'
import { formatDate, formatDateTime, formatNumber } from '@/lib/format'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { useServerTable, type ServerTableResult } from '@/lib/useServerTable'
import type { PaginatedResponse } from './rfqShared'
import { READINESS_LABELS, READINESS_TONES, STATUS_LABELS, STATUS_TONES, WINDOW_LABELS, type Quotation } from './quotationShared'

interface Filters {
  search: string
}

async function fetchQuotations({
  page,
  pageSize,
  filters,
}: {
  page: number
  pageSize: number
  filters: Filters
}): Promise<ServerTableResult<Quotation>> {
  const { data } = await apiClient.get<PaginatedResponse<Quotation>>('/api/quotations', {
    params: { page, page_size: pageSize, q: filters.search || undefined },
  })
  return { rows: data.data, total: data.pagination.total }
}

/** Sales -> Quotations (backend/app/api/quotations.py). The server returns
 * only quotations whose customer is in the caller's scope, each with its
 * current delivery window and readiness already worked out; this page
 * only displays them. */
export function QuotationsPage() {
  const navigate = useNavigate()
  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 300)
  const fetcher = useCallback(fetchQuotations, [])
  const table = useServerTable<Quotation, Filters>({ fetcher, pageSize: 20, initialFilters: { search: '' } })

  const isFirstSearch = useRef(true)
  useEffect(() => {
    if (isFirstSearch.current) {
      isFirstSearch.current = false
      return
    }
    table.setFilters({ search: debouncedSearch })
    // Same wiring as GoodsReceivingPage: re-run only when the search changes.
  }, [debouncedSearch])

  const columns: DataTableColumn<Quotation>[] = [
    {
      key: 'quotation_number',
      label: 'Quotation',
      alwaysVisible: true,
      render: (q) => (
        <button type="button" className="font-medium text-gold-300 underline-offset-2 hover:underline" onClick={() => navigate(`/sales/quotations/${q.id}`)}>
          {q.quotation_number}
        </button>
      ),
    },
    { key: 'customer', label: 'Customer', render: (q) => q.customer_name ?? '—' },
    { key: 'quotation_date', label: 'Date', hideBelow: 'md', render: (q) => formatDate(q.quotation_date) },
    { key: 'requested', label: 'Requested Delivery', hideBelow: 'sm', render: (q) => formatDate(q.requested_delivery_date) },
    {
      key: 'window',
      label: 'Delivery Window',
      hideBelow: 'lg',
      render: (q) => (q.delivery_window ? WINDOW_LABELS[q.delivery_window] ?? q.delivery_window : '—'),
    },
    {
      key: 'total',
      label: 'Total',
      align: 'right',
      render: (q) => `${formatNumber(q.total_amount, { minimumFractionDigits: 3, maximumFractionDigits: 3 })} ${q.currency}`,
    },
    {
      key: 'status',
      label: 'Status',
      render: (q) => (
        <>
          <Badge tone={STATUS_TONES[q.status] ?? 'neutral'}>{STATUS_LABELS[q.status] ?? q.status}</Badge>
          {q.is_expired && <Badge tone="warning" className="ml-1">Expired</Badge>}
        </>
      ),
    },
    {
      key: 'readiness',
      label: 'Readiness',
      render: (q) =>
        q.readiness_status ? (
          <Badge tone={READINESS_TONES[q.readiness_status] ?? 'neutral'}>{READINESS_LABELS[q.readiness_status] ?? q.readiness_status}</Badge>
        ) : (
          '—'
        ),
    },
    { key: 'created_by', label: 'Created By', hideBelow: 'lg', render: (q) => q.created_by_name ?? '—' },
    { key: 'updated', label: 'Last Updated', hideBelow: 'lg', render: (q) => formatDateTime(q.updated_at) },
    {
      key: 'open',
      label: '',
      alwaysVisible: true,
      align: 'right',
      render: (q) => (
        <Button variant="secondary" onClick={() => navigate(`/sales/quotations/${q.id}`)}>
          Open
        </Button>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Quotations"
        subtitle="Quotations for your customers, with their delivery window and readiness."
        actions={<Button onClick={() => navigate('/sales/quotations/new')}>New Quotation</Button>}
      />
      <FilterBar>
        <TextField
          label="Search"
          placeholder="Quotation number or customer..."
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />
      </FilterBar>
      <DataTable
        columns={columns}
        rows={table.rows}
        rowKey={(q) => q.id}
        loading={table.loading}
        error={table.error}
        page={table.page}
        totalPages={table.totalPages}
        total={table.total}
        onPageChange={table.setPage}
        pageSize={table.pageSize}
        onPageSizeChange={table.setPageSize}
        emptyTitle="No quotations"
        emptyMessage="Create a quotation for one of your customers to get started."
      />
    </div>
  )
}
