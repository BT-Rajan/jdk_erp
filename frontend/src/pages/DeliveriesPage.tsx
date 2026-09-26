import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AccessDeniedState } from '@/components/ui/AccessDeniedState'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { DataTable, type DataTableColumn } from '@/components/ui/DataTable'
import { FilterBar } from '@/components/ui/FilterBar'
import { FormSectionHeading } from '@/components/ui/FormSectionHeading'
import { PageHeader } from '@/components/ui/PageHeader'
import { TextField } from '@/components/forms/TextField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { formatDate, formatDateTime } from '@/lib/format'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { useServerTable, type ServerTableResult } from '@/lib/useServerTable'
import type { PaginatedResponse } from './rfqShared'
import { ORDER_STATUS_LABELS, ORDER_STATUS_TONES } from './quotationShared'
import {
  DELIVERY_STATUS_LABELS,
  DELIVERY_STATUS_TONES,
  type DeliverableOrder,
  type DeliveryInstruction,
} from './deliveryShared'

interface Filters {
  search: string
}

/** Inventory -> Deliveries (backend/app/api/delivery_instructions.py):
 * Sales Orders that can take a delivery now, and every Delivery
 * Instruction. Needs the inventory:deliver grant -- the server refuses
 * everything here without it (the page then shows access denied). */
export function DeliveriesPage() {
  const navigate = useNavigate()
  const [denied, setDenied] = useState(false)
  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 300)

  const onError = useCallback((err: unknown) => {
    if (err instanceof ApiError && err.status === 403) setDenied(true)
    throw err
  }, [])
  const fetchOrders = useCallback(
    async ({ page, pageSize, filters }: { page: number; pageSize: number; filters: Filters }): Promise<ServerTableResult<DeliverableOrder>> => {
      const { data } = await apiClient
        .get<PaginatedResponse<DeliverableOrder>>('/api/delivery-instructions/eligible-orders', {
          params: { page, page_size: pageSize, q: filters.search || undefined },
        })
        .catch(onError)
      return { rows: data.data, total: data.pagination.total }
    },
    [onError],
  )
  const fetchInstructions = useCallback(
    async ({ page, pageSize }: { page: number; pageSize: number }): Promise<ServerTableResult<DeliveryInstruction>> => {
      const { data } = await apiClient
        .get<PaginatedResponse<DeliveryInstruction>>('/api/delivery-instructions', { params: { page, page_size: pageSize } })
        .catch(onError)
      return { rows: data.data, total: data.pagination.total }
    },
    [onError],
  )
  const orders = useServerTable<DeliverableOrder, Filters>({ fetcher: fetchOrders, pageSize: 10, initialFilters: { search: '' } })
  const instructions = useServerTable<DeliveryInstruction, Record<string, never>>({
    fetcher: fetchInstructions,
    pageSize: 10,
    initialFilters: {},
  })

  const isFirstSearch = useRef(true)
  useEffect(() => {
    if (isFirstSearch.current) {
      isFirstSearch.current = false
      return
    }
    orders.setFilters({ search: debouncedSearch })
  }, [debouncedSearch])

  if (denied) return <AccessDeniedState message="Deliveries need the warehouse delivery permission." />

  const orderColumns: DataTableColumn<DeliverableOrder>[] = [
    { key: 'order', label: 'Sales Order', alwaysVisible: true, render: (o) => o.order_number },
    { key: 'customer', label: 'Customer', render: (o) => o.customer_name ?? '—' },
    { key: 'requested', label: 'Requested Delivery', hideBelow: 'sm', render: (o) => formatDate(o.requested_delivery_date) },
    {
      key: 'status',
      label: 'Status',
      hideBelow: 'md',
      render: (o) => <Badge tone={ORDER_STATUS_TONES[o.status] ?? 'neutral'}>{ORDER_STATUS_LABELS[o.status] ?? o.status}</Badge>,
    },
    {
      key: 'open',
      label: '',
      alwaysVisible: true,
      align: 'right',
      render: (o) => (
        <Button variant="secondary" onClick={() => navigate(`/deliveries/orders/${o.id}`)}>
          Deliver
        </Button>
      ),
    },
  ]
  const instructionColumns: DataTableColumn<DeliveryInstruction>[] = [
    { key: 'number', label: 'Delivery', alwaysVisible: true, render: (d) => d.delivery_number },
    { key: 'order', label: 'Sales Order', render: (d) => d.sales_order_number ?? '—' },
    { key: 'customer', label: 'Customer', hideBelow: 'md', render: (d) => d.customer_name ?? '—' },
    { key: 'created', label: 'Created', hideBelow: 'sm', render: (d) => formatDateTime(d.created_at) },
    {
      key: 'status',
      label: 'Status',
      render: (d) => <Badge tone={DELIVERY_STATUS_TONES[d.status] ?? 'neutral'}>{DELIVERY_STATUS_LABELS[d.status] ?? d.status}</Badge>,
    },
    {
      key: 'open',
      label: '',
      alwaysVisible: true,
      align: 'right',
      render: (d) => (
        <Button variant="secondary" onClick={() => navigate(`/deliveries/${d.id}`)}>
          Open
        </Button>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader title="Deliveries" subtitle="Ship Sales Orders in one or more deliveries from finished goods stock." />
      <Card className="space-y-3 p-4 sm:p-6">
        <FormSectionHeading>Sales Orders ready for delivery</FormSectionHeading>
        <FilterBar>
          <TextField label="Search" placeholder="Order number or customer..." value={searchInput} onChange={(e) => setSearchInput(e.target.value)} />
        </FilterBar>
        <DataTable
          columns={orderColumns}
          rows={orders.rows}
          rowKey={(o) => o.id}
          loading={orders.loading}
          error={orders.error}
          page={orders.page}
          totalPages={orders.totalPages}
          total={orders.total}
          onPageChange={orders.setPage}
          pageSize={orders.pageSize}
          onPageSizeChange={orders.setPageSize}
          emptyTitle="Nothing to deliver"
          emptyMessage="Handed-off and partially delivered Sales Orders appear here."
        />
      </Card>
      <Card className="space-y-3 p-4 sm:p-6">
        <FormSectionHeading>Delivery Instructions</FormSectionHeading>
        <DataTable
          columns={instructionColumns}
          rows={instructions.rows}
          rowKey={(d) => d.id}
          loading={instructions.loading}
          error={instructions.error}
          page={instructions.page}
          totalPages={instructions.totalPages}
          total={instructions.total}
          onPageChange={instructions.setPage}
          pageSize={instructions.pageSize}
          onPageSizeChange={instructions.setPageSize}
          emptyTitle="No deliveries yet"
          emptyMessage="Create one from a Sales Order above."
        />
      </Card>
    </div>
  )
}
