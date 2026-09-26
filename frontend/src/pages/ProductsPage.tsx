import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { ActionMenu, type ActionMenuOption } from '@/components/ui/ActionMenu'
import { Alert } from '@/components/ui/Alert'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { DataTable, type DataTableColumn } from '@/components/ui/DataTable'
import { FilterBar } from '@/components/ui/FilterBar'
import { FormPage } from '@/components/ui/FormPage'
import { PageHeader } from '@/components/ui/PageHeader'
import type { SortState } from '@/components/ui/sort'
import { SelectField } from '@/components/forms/SelectField'
import { TextField } from '@/components/forms/TextField'
import { TextareaField } from '@/components/forms/TextareaField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { useAuth } from '@/lib/auth/AuthContext'
import { isAdminRole } from '@/lib/auth/roles'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { useServerTable, type ServerTableResult } from '@/lib/useServerTable'
import { useFormRoute } from '@/lib/useFormRoute'

/** Mirrors backend/app/schemas/product.py's ProductOut. */
interface Product {
  id: number
  organisation_id: number
  code: string
  name: string
  category_id: number
  unit_of_measure_id: number
  description: string | null
  selling_price: string
  min_selling_price: string | null
  max_selling_price: string | null
  manufacturing_lead_time_days: number | null
  customer_lead_time_days: number | null
  is_active: boolean
}

/** Local shapes for the Category/UoM pickers -- only the fields this
 * page needs from their own CategoryOut/UnitOfMeasureOut. */
interface LookupOption {
  id: number
  name: string
  code: string | null
  is_active: boolean
}

interface PaginatedResponse<T> {
  data: T[]
  pagination: { page: number; page_size: number; total: number; total_pages: number }
}

interface ProductsFilters {
  search: string
}

const DECIMAL_RE = /^\d+(\.\d{1,2})?$/
const INTEGER_RE = /^\d+$/

const productSchema = z.object({
  name: z.string().min(1, 'Name is required'),
  category_id: z.string().min(1, 'Category is required'),
  unit_of_measure_id: z.string().min(1, 'Unit of measure is required'),
  description: z.string(),
  selling_price: z.string().min(1, 'Selling price is required').refine((v) => DECIMAL_RE.test(v), 'Enter a valid amount'),
  min_selling_price: z.string().refine((v) => v === '' || DECIMAL_RE.test(v), 'Enter a valid amount'),
  max_selling_price: z.string().refine((v) => v === '' || DECIMAL_RE.test(v), 'Enter a valid amount'),
  manufacturing_lead_time_days: z.string().refine((v) => v === '' || INTEGER_RE.test(v), 'Enter a whole number of days'),
  customer_lead_time_days: z.string().refine((v) => v === '' || INTEGER_RE.test(v), 'Enter a whole number of days'),
})

type ProductFormValues = z.infer<typeof productSchema>

const emptyDefaults: ProductFormValues = {
  name: '',
  category_id: '',
  unit_of_measure_id: '',
  description: '',
  selling_price: '',
  min_selling_price: '',
  max_selling_price: '',
  manufacturing_lead_time_days: '',
  customer_lead_time_days: '',
}

function toFormValues(product: Product): ProductFormValues {
  return {
    name: product.name,
    category_id: String(product.category_id),
    unit_of_measure_id: String(product.unit_of_measure_id),
    description: product.description ?? '',
    selling_price: product.selling_price,
    min_selling_price: product.min_selling_price ?? '',
    max_selling_price: product.max_selling_price ?? '',
    manufacturing_lead_time_days: product.manufacturing_lead_time_days == null ? '' : String(product.manufacturing_lead_time_days),
    customer_lead_time_days: product.customer_lead_time_days == null ? '' : String(product.customer_lead_time_days),
  }
}

async function fetchProducts({
  page,
  pageSize,
  sort,
  filters,
}: {
  page: number
  pageSize: number
  sort: SortState | null
  filters: ProductsFilters
}): Promise<ServerTableResult<Product>> {
  // The common list contract (docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md).
  const { data } = await apiClient.get<PaginatedResponse<Product>>('/api/products', {
    params: {
      page,
      page_size: pageSize,
      sort_by: sort?.field,
      sort_direction: sort?.direction,
      include_inactive: true,
      q: filters.search || undefined,
    },
  })
  return { rows: data.data, total: data.pagination.total }
}

/** The authoritative definition of what JDK sells and manufactures
 * (backend/app/api/products.py, docs/modules/products.md). Composed
 * identically to CategoriesPage/SuppliersPage -- the same flat
 * admin-gated shape (no ownership dimension, so no permission-scope
 * engine). Category and Unit of Measure are rendered as dropdowns of the
 * caller's own active records, reusing GET /api/categories and
 * GET /api/units-of-measure rather than a new lookup endpoint. `code` is
 * system-generated and immutable -- there is no Code input on Create at
 * all (nothing to type), and the Edit dialog shows it disabled purely
 * for reference. Manufacturing Lead Time and Customer Lead Time are deliberately
 * separate fields with distinct meanings (docs/modules/products.md
 * #4/#5) -- this page never combines or derives one from the other. */
export function ProductsPage() {
  const { user: currentUser } = useAuth()
  const canManage = isAdminRole(currentUser?.role)

  const [categories, setCategories] = useState<LookupOption[]>([])
  const [units, setUnits] = useState<LookupOption[]>([])
  const [pageError, setPageError] = useState<string | undefined>(undefined)

  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 300)

  const [editingProduct, setEditingProduct] = useState<Product | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const [statusTarget, setStatusTarget] = useState<Product | null>(null)
  const [statusBusy, setStatusBusy] = useState(false)

  const {
    register,
    handleSubmit,
    reset,
    setError: setFieldError,
    formState: { errors, isSubmitting },
  } = useForm<ProductFormValues>({ resolver: zodResolver(productSchema), defaultValues: emptyDefaults })

  const table = useServerTable<Product, ProductsFilters>({
    fetcher: fetchProducts,
    pageSize: 20,
    initialFilters: { search: '' },
  })

  const isFirstSearchRender = useRef(true)
  useEffect(() => {
    if (isFirstSearchRender.current) {
      isFirstSearchRender.current = false
      return
    }
    table.setFilters({ search: debouncedSearch })
  }, [debouncedSearch])

  const categoriesById = useMemo(() => new Map(categories.map((c) => [c.id, c])), [categories])
  const unitsById = useMemo(() => new Map(units.map((u) => [u.id, u])), [units])

  const loadLookups = useCallback(async () => {
    try {
      const [categoriesResponse, unitsResponse] = await Promise.all([
        apiClient.get<PaginatedResponse<LookupOption>>('/api/categories', { params: { page_size: 200 } }),
        apiClient.get<PaginatedResponse<LookupOption>>('/api/units-of-measure', { params: { page_size: 200 } }),
      ])
      setCategories(categoriesResponse.data.data)
      setUnits(unitsResponse.data.data)
    } catch (err) {
      setPageError(err instanceof ApiError ? err.message : 'Failed to load categories and units of measure.')
    }
  }, [])

  useEffect(() => {
    if (canManage) void loadLookups()
  }, [canManage, loadLookups])

  function prepareCreate() {
    setEditingProduct(null)
    reset(emptyDefaults)
    setFormError(null)
  }

  function prepareEdit(product: Product) {
    setEditingProduct(product)
    reset(toFormValues(product))
    setFormError(null)
  }

  const { formOpen, loading: formLoading, loadError: formLoadError, openCreate, openEdit, closeForm } = useFormRoute<Product>(
    '/products',
    '/api/products',
    { onCreate: prepareCreate, onEdit: prepareEdit },
  )

  const onFormSubmit = useCallback(
    async (values: ProductFormValues) => {
      setFormError(null)
      const payload = {
        name: values.name,
        category_id: Number(values.category_id),
        unit_of_measure_id: Number(values.unit_of_measure_id),
        description: values.description || null,
        selling_price: values.selling_price,
        min_selling_price: values.min_selling_price || null,
        max_selling_price: values.max_selling_price || null,
        manufacturing_lead_time_days: values.manufacturing_lead_time_days === '' ? null : Number(values.manufacturing_lead_time_days),
        customer_lead_time_days: values.customer_lead_time_days === '' ? null : Number(values.customer_lead_time_days),
      }
      try {
        if (editingProduct) {
          await apiClient.patch(`/api/products/${editingProduct.id}`, payload)
        } else {
          await apiClient.post('/api/products', payload)
        }
        closeForm()
        table.refetch()
      } catch (err) {
        if (err instanceof ApiError) {
          if (err.fields) {
            for (const [field, message] of Object.entries(err.fields)) {
              if (field in emptyDefaults) setFieldError(field as keyof ProductFormValues, { message })
            }
          }
          setFormError(err.message)
        } else {
          setFormError('Something went wrong. Please try again.')
        }
      }
    },
    [editingProduct, setFieldError, table],
  )

  async function confirmStatusChange() {
    if (!statusTarget) return
    setStatusBusy(true)
    setPageError(undefined)
    try {
      await apiClient.patch(`/api/products/${statusTarget.id}/status`, { is_active: !statusTarget.is_active })
      setStatusTarget(null)
      table.refetch()
    } catch (err) {
      setPageError(err instanceof ApiError ? err.message : 'Failed to change status.')
    } finally {
      setStatusBusy(false)
    }
  }

  const columns: DataTableColumn<Product>[] = [
    { key: 'code', label: 'Code', sortable: true, hideBelow: 'sm', render: (p) => p.code },
    { key: 'name', label: 'Product', sortable: true, render: (p) => p.name },
    {
      key: 'category',
      label: 'Category',
      hideBelow: 'md',
      render: (p) => categoriesById.get(p.category_id)?.name ?? <span className="text-gold-100/40">—</span>,
    },
    {
      key: 'unit',
      label: 'UoM',
      hideBelow: 'lg',
      render: (p) => unitsById.get(p.unit_of_measure_id)?.code ?? <span className="text-gold-100/40">—</span>,
    },
    {
      key: 'selling_price',
      label: 'Selling Price',
      sortable: true,
      hideBelow: 'md',
      render: (p) => p.selling_price,
    },
    {
      key: 'status',
      label: 'Status',
      render: (p) => <Badge tone={p.is_active ? 'success' : 'danger'}>{p.is_active ? 'Active' : 'Inactive'}</Badge>,
    },
    ...(canManage
      ? [
          {
            key: 'actions',
            label: '',
            alwaysVisible: true,
            align: 'right' as const,
            render: (p: Product) => {
              const options: ActionMenuOption[] = [
                { key: 'edit', label: 'Edit', onSelect: () => openEdit(p) },
                p.is_active
                  ? { key: 'deactivate', label: 'Deactivate', danger: true, onSelect: () => setStatusTarget(p) }
                  : { key: 'activate', label: 'Activate', onSelect: () => setStatusTarget(p) },
              ]
              return <ActionMenu label={`Actions for ${p.name}`} options={options} />
            },
          },
        ]
      : []),
  ]

  return (
    <div className="space-y-6">
      <div hidden={formOpen} className="space-y-6">
        <PageHeader
          title="Products"
          subtitle="The authoritative definition of what JDK sells and manufactures."
          actions={canManage ? <Button onClick={openCreate}>New Product</Button> : undefined}
        />

        <Alert variant="danger">{pageError}</Alert>

        <FilterBar>
          <TextField
            label="Search"
            placeholder="Search by name or code..."
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
        </FilterBar>

        <DataTable
          columns={columns}
          rows={table.rows}
          rowKey={(p) => p.id}
          loading={table.loading}
          error={table.error}
          sort={table.sort}
          onSortChange={table.setSort}
          page={table.page}
          totalPages={table.totalPages}
          total={table.total}
          onPageChange={table.setPage}
          pageSize={table.pageSize}
          onPageSizeChange={table.setPageSize}
          emptyTitle={debouncedSearch ? 'No matching products' : 'No products yet'}
          emptyMessage={
            debouncedSearch
              ? 'Try a different search term.'
              : canManage
                ? 'Create the first product with the New Product button above.'
                : 'No products have been created yet.'
          }
        />
      </div>

      {canManage && (
        <>
          <FormPage
            loading={formLoading}
            loadError={formLoadError}
            open={formOpen}
            title={editingProduct ? 'Edit Product' : 'New Product'}
            onClose={closeForm}
            onSubmit={handleSubmit(onFormSubmit)}
            submitting={isSubmitting}
            submitLabel={editingProduct ? 'Save' : 'Create product'}
          >
            <Alert variant="danger">{formError}</Alert>
            {editingProduct && (
              <TextField
                label="Product Code"
                disabled
                hint="System-generated. Cannot be changed."
                value={editingProduct.code}
                readOnly
              />
            )}
            <TextField label="Product Name" required {...register('name')} error={errors.name?.message} />
            <SelectField label="Category" required {...register('category_id')} error={errors.category_id?.message}>
              <option value="">Select a category...</option>
              {categories
                .filter((c) => c.is_active)
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
            </SelectField>
            <SelectField
              label="Unit of Measure"
              required
              {...register('unit_of_measure_id')}
              error={errors.unit_of_measure_id?.message}
            >
              <option value="">Select a unit of measure...</option>
              {units
                .filter((u) => u.is_active)
                .map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name} ({u.code})
                  </option>
                ))}
            </SelectField>
            <TextareaField label="Description" {...register('description')} error={errors.description?.message} />
            <TextField
              label="Default Selling Price"
              required
              hint="Current/default reference price only -- not historical transaction pricing."
              {...register('selling_price')}
              error={errors.selling_price?.message}
            />
            <TextField
              label="Minimum Selling Price"
              hint="Quoting below this needs Admin approval. Leave both blank and every quoted price needs approval."
              {...register('min_selling_price')}
              error={errors.min_selling_price?.message}
            />
            <TextField
              label="Maximum Selling Price"
              hint="Quoting above this needs Admin approval."
              {...register('max_selling_price')}
              error={errors.max_selling_price?.message}
            />
            <TextField
              label="Manufacturing Lead Time (days)"
              hint="Reference value for Feasibility/Planning -- not a production schedule."
              {...register('manufacturing_lead_time_days')}
              error={errors.manufacturing_lead_time_days?.message}
            />
            <TextField
              label="Customer Lead Time (days)"
              hint="Reference value Sales uses when committing a delivery date."
              {...register('customer_lead_time_days')}
              error={errors.customer_lead_time_days?.message}
            />
          </FormPage>

          <ConfirmDialog
            open={!!statusTarget}
            title={statusTarget?.is_active ? 'Deactivate product' : 'Activate product'}
            message={
              statusTarget?.is_active
                ? `${statusTarget.name} will no longer be selectable for new records. Existing records that reference it are unaffected.`
                : `${statusTarget?.name ?? ''} will be selectable for new records again.`
            }
            confirmLabel={statusTarget?.is_active ? 'Deactivate' : 'Activate'}
            danger={statusTarget?.is_active}
            busy={statusBusy}
            onConfirm={confirmStatusChange}
            onCancel={() => setStatusTarget(null)}
          />
        </>
      )}
    </div>
  )
}
