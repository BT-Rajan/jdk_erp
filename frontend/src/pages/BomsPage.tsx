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
import { FormDialog } from '@/components/ui/FormDialog'
import { Modal } from '@/components/ui/Modal'
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

/** Mirrors backend/app/schemas/bom.py's BomOut. */
interface Bom {
  id: number
  organisation_id: number
  product_id: number
  base_quantity: string
  status: 'draft' | 'active'
  notes: string | null
  components: BomComponent[]
}

/** Mirrors backend/app/schemas/bom.py's BomComponentOut -- percentage/
 * conversion_ok/conversion_error are always computed at read time,
 * never stored (docs/modules/boms.md #8). */
interface BomComponent {
  id: number
  raw_material_id: number
  quantity: string
  percentage: string | null
  conversion_ok: boolean
  conversion_error: string | null
}

interface RequirementLine {
  raw_material_id: number
  required_quantity: string
  unit_of_measure_id: number
}

interface LookupOption {
  id: number
  name: string
  code: string | null
  is_active: boolean
  unit_of_measure_id?: number
}

interface PaginatedResponse<T> {
  data: T[]
  pagination: { page: number; page_size: number; total: number; total_pages: number }
}

interface BomsFilters {
  search: string
}

const DECIMAL_RE = /^\d+(\.\d+)?$/

const bomSchema = z.object({
  product_id: z.string().min(1, 'Product is required'),
  base_quantity: z
    .string()
    .min(1, 'Base quantity is required')
    .refine((v) => DECIMAL_RE.test(v) && Number(v) > 0, 'Enter a positive number'),
  notes: z.string(),
})

type BomFormValues = z.infer<typeof bomSchema>

const emptyBomDefaults: BomFormValues = { product_id: '', base_quantity: '', notes: '' }

function toBomFormValues(bom: Bom): BomFormValues {
  return { product_id: String(bom.product_id), base_quantity: bom.base_quantity, notes: bom.notes ?? '' }
}

const componentSchema = z.object({
  raw_material_id: z.string().min(1, 'Raw material is required'),
  quantity: z
    .string()
    .min(1, 'Quantity is required')
    .refine((v) => DECIMAL_RE.test(v) && Number(v) > 0, 'Enter a positive number'),
})

type ComponentFormValues = z.infer<typeof componentSchema>

const emptyComponentDefaults: ComponentFormValues = { raw_material_id: '', quantity: '' }

function toComponentFormValues(component: BomComponent): ComponentFormValues {
  return { raw_material_id: String(component.raw_material_id), quantity: component.quantity }
}

const calculateSchema = z.object({
  production_quantity: z
    .string()
    .min(1, 'Production quantity is required')
    .refine((v) => DECIMAL_RE.test(v) && Number(v) > 0, 'Enter a positive number'),
})

type CalculateFormValues = z.infer<typeof calculateSchema>

async function fetchBoms({
  page,
  pageSize,
  sort,
  filters,
}: {
  page: number
  pageSize: number
  sort: SortState | null
  filters: BomsFilters
}): Promise<ServerTableResult<Bom>> {
  // The common list contract (docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md).
  // BOM has no q= search of its own (docs/api); filters.search is applied
  // client-side against the resolved Product name/code below instead.
  void filters
  const { data } = await apiClient.get<PaginatedResponse<Bom>>('/api/boms', {
    params: { page, page_size: pageSize, sort_by: sort?.field, sort_direction: sort?.direction },
  })
  return { rows: data.data, total: data.pagination.total }
}

/** The single, unambiguous relationship between a finished Product and
 * the Raw Materials required to produce a specified base quantity of it
 * (backend/app/api/boms.py, docs/modules/boms.md). A hardening of a real
 * jdk_clean feature (docs/audit/BOMS_AUDIT.md), not a new manufacturing
 * platform -- one flat list of BOMs (one row per Product with a BOM),
 * each row's "Manage Components..." action opening the header's
 * component table (Raw Material | Quantity | UoM | % | Conversion
 * Status, per the spec's own #12), the same "manage a child relationship
 * in a dialog" pattern RawMaterialsPage's Manage Suppliers dialog
 * already established. Conversion internals are never exposed except
 * via the Conversion Status column's own error message when a component
 * actually has one (docs/modules/boms.md #12). */
export function BomsPage() {
  const { user: currentUser } = useAuth()
  const canManage = isAdminRole(currentUser?.role)

  const [products, setProducts] = useState<LookupOption[]>([])
  const [materials, setMaterials] = useState<LookupOption[]>([])
  const [units, setUnits] = useState<LookupOption[]>([])
  const [pageError, setPageError] = useState<string | undefined>(undefined)

  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 300)

  const [formOpen, setFormOpen] = useState(false)
  const [editingBom, setEditingBom] = useState<Bom | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const [statusTarget, setStatusTarget] = useState<Bom | null>(null)
  const [statusBusy, setStatusBusy] = useState(false)
  const [statusError, setStatusError] = useState<string | undefined>(undefined)

  // --- Manage Components dialog state ---
  const [componentsDialogTarget, setComponentsDialogTarget] = useState<Bom | null>(null)
  const [editingComponent, setEditingComponent] = useState<BomComponent | null>(null)
  const [componentFormOpen, setComponentFormOpen] = useState(false)
  const [componentFormError, setComponentFormError] = useState<string | null>(null)
  const [removeComponentTarget, setRemoveComponentTarget] = useState<BomComponent | null>(null)
  const [removeComponentBusy, setRemoveComponentBusy] = useState(false)

  // --- Calculate Requirements dialog state ---
  const [calculateTarget, setCalculateTarget] = useState<Bom | null>(null)
  const [calculateError, setCalculateError] = useState<string | null>(null)
  const [requirements, setRequirements] = useState<RequirementLine[] | null>(null)

  const {
    register,
    handleSubmit,
    reset,
    setError: setFieldError,
    formState: { errors, isSubmitting },
  } = useForm<BomFormValues>({ resolver: zodResolver(bomSchema), defaultValues: emptyBomDefaults })

  const componentForm = useForm<ComponentFormValues>({
    resolver: zodResolver(componentSchema),
    defaultValues: emptyComponentDefaults,
  })

  const calculateForm = useForm<CalculateFormValues>({
    resolver: zodResolver(calculateSchema),
    defaultValues: { production_quantity: '' },
  })

  const table = useServerTable<Bom, BomsFilters>({
    fetcher: fetchBoms,
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

  const productsById = useMemo(() => new Map(products.map((p) => [p.id, p])), [products])
  const materialsById = useMemo(() => new Map(materials.map((m) => [m.id, m])), [materials])
  const unitsById = useMemo(() => new Map(units.map((u) => [u.id, u])), [units])

  const rows = useMemo(() => {
    if (!debouncedSearch) return table.rows
    const term = debouncedSearch.toLowerCase()
    return table.rows.filter((bom) => {
      const product = productsById.get(bom.product_id)
      return (
        product?.name.toLowerCase().includes(term) || product?.code?.toLowerCase().includes(term) || false
      )
    })
  }, [table.rows, debouncedSearch, productsById])

  const loadLookups = useCallback(async () => {
    try {
      const [productsResponse, materialsResponse, unitsResponse] = await Promise.all([
        apiClient.get<PaginatedResponse<LookupOption>>('/api/products', { params: { page_size: 200 } }),
        apiClient.get<PaginatedResponse<LookupOption>>('/api/raw-materials', { params: { page_size: 200 } }),
        apiClient.get<PaginatedResponse<LookupOption>>('/api/units-of-measure', { params: { page_size: 200 } }),
      ])
      setProducts(productsResponse.data.data)
      setMaterials(materialsResponse.data.data)
      setUnits(unitsResponse.data.data)
    } catch (err) {
      setPageError(err instanceof ApiError ? err.message : 'Failed to load products, raw materials, and units.')
    }
  }, [])

  useEffect(() => {
    void loadLookups()
  }, [loadLookups])

  function openCreate() {
    setEditingBom(null)
    reset(emptyBomDefaults)
    setFormError(null)
    setFormOpen(true)
  }

  function openEdit(bom: Bom) {
    setEditingBom(bom)
    reset(toBomFormValues(bom))
    setFormError(null)
    setFormOpen(true)
  }

  const onFormSubmit = useCallback(
    async (values: BomFormValues) => {
      setFormError(null)
      try {
        if (editingBom) {
          await apiClient.patch(`/api/boms/${editingBom.id}`, {
            base_quantity: values.base_quantity,
            notes: values.notes || null,
          })
        } else {
          await apiClient.post('/api/boms', {
            product_id: Number(values.product_id),
            base_quantity: values.base_quantity,
            notes: values.notes || null,
          })
        }
        setFormOpen(false)
        table.refetch()
      } catch (err) {
        if (err instanceof ApiError) {
          if (err.fields) {
            for (const [field, message] of Object.entries(err.fields)) {
              if (field in emptyBomDefaults) setFieldError(field as keyof BomFormValues, { message })
            }
          }
          setFormError(err.message)
        } else {
          setFormError('Something went wrong. Please try again.')
        }
      }
    },
    [editingBom, setFieldError, table],
  )

  async function confirmStatusChange() {
    if (!statusTarget) return
    setStatusBusy(true)
    setStatusError(undefined)
    try {
      await apiClient.patch(`/api/boms/${statusTarget.id}/status`, {
        status: statusTarget.status === 'active' ? 'draft' : 'active',
      })
      setStatusTarget(null)
      table.refetch()
    } catch (err) {
      setStatusError(err instanceof ApiError ? err.message : 'Failed to change status.')
    } finally {
      setStatusBusy(false)
    }
  }

  // --- Manage Components dialog logic ---
  // Re-fetches the whole BOM (not just its components) after every
  // mutation, since it's the source of truth for the freshly recomputed
  // percentage/conversion_ok/conversion_error on every remaining
  // component too (docs/modules/boms.md #8).

  const refreshComponentsDialog = useCallback(async (bomId: number) => {
    const { data } = await apiClient.get<Bom>(`/api/boms/${bomId}`)
    setComponentsDialogTarget(data)
    table.refetch()
  }, [table])

  function openManageComponents(bom: Bom) {
    setComponentsDialogTarget(bom)
    setEditingComponent(null)
    setComponentFormOpen(false)
  }

  function closeManageComponents() {
    setComponentsDialogTarget(null)
    setComponentFormOpen(false)
    setEditingComponent(null)
  }

  function openAddComponent() {
    setEditingComponent(null)
    componentForm.reset(emptyComponentDefaults)
    setComponentFormError(null)
    setComponentFormOpen(true)
  }

  function openEditComponent(component: BomComponent) {
    setEditingComponent(component)
    componentForm.reset(toComponentFormValues(component))
    setComponentFormError(null)
    setComponentFormOpen(true)
  }

  const onComponentFormSubmit = useCallback(
    async (values: ComponentFormValues) => {
      if (!componentsDialogTarget) return
      setComponentFormError(null)
      try {
        if (editingComponent) {
          await apiClient.patch(
            `/api/boms/${componentsDialogTarget.id}/components/${editingComponent.id}`,
            { quantity: values.quantity },
          )
        } else {
          await apiClient.post(`/api/boms/${componentsDialogTarget.id}/components`, {
            raw_material_id: Number(values.raw_material_id),
            quantity: values.quantity,
          })
        }
        setComponentFormOpen(false)
        await refreshComponentsDialog(componentsDialogTarget.id)
      } catch (err) {
        setComponentFormError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
      }
    },
    [componentsDialogTarget, editingComponent, refreshComponentsDialog],
  )

  async function confirmRemoveComponent() {
    if (!componentsDialogTarget || !removeComponentTarget) return
    setRemoveComponentBusy(true)
    try {
      await apiClient.delete(
        `/api/boms/${componentsDialogTarget.id}/components/${removeComponentTarget.id}`,
      )
      setRemoveComponentTarget(null)
      await refreshComponentsDialog(componentsDialogTarget.id)
    } catch (err) {
      setComponentFormError(err instanceof ApiError ? err.message : 'Failed to remove component.')
    } finally {
      setRemoveComponentBusy(false)
    }
  }

  // --- Calculate Requirements dialog logic ---

  function openCalculate(bom: Bom) {
    setCalculateTarget(bom)
    calculateForm.reset({ production_quantity: '' })
    setCalculateError(null)
    setRequirements(null)
  }

  function closeCalculate() {
    setCalculateTarget(null)
    setRequirements(null)
  }

  const onCalculateSubmit = useCallback(
    async (values: CalculateFormValues) => {
      if (!calculateTarget) return
      setCalculateError(null)
      setRequirements(null)
      try {
        const { data } = await apiClient.post<{ requirements: RequirementLine[] }>(
          `/api/boms/${calculateTarget.id}/calculate-requirements`,
          { production_quantity: values.production_quantity },
        )
        setRequirements(data.requirements)
      } catch (err) {
        setCalculateError(err instanceof ApiError ? err.message : 'Failed to calculate requirements.')
      }
    },
    [calculateTarget],
  )

  const columns: DataTableColumn<Bom>[] = [
    {
      key: 'product',
      label: 'Product',
      render: (b) => {
        const product = productsById.get(b.product_id)
        return product ? `${product.name} (${product.code ?? '—'})` : `#${b.product_id}`
      },
    },
    {
      key: 'base_quantity',
      label: 'Base Quantity',
      hideBelow: 'sm',
      render: (b) => {
        const product = productsById.get(b.product_id)
        const unit = product?.unit_of_measure_id != null ? unitsById.get(product.unit_of_measure_id) : undefined
        return `${b.base_quantity}${unit ? ` ${unit.code}` : ''}`
      },
    },
    {
      key: 'components',
      label: 'Components',
      hideBelow: 'md',
      render: (b) => b.components.length,
    },
    {
      key: 'status',
      label: 'Status',
      render: (b) => <Badge tone={b.status === 'active' ? 'success' : 'neutral'}>{b.status === 'active' ? 'Active' : 'Draft'}</Badge>,
    },
    {
      key: 'actions',
      label: '',
      alwaysVisible: true,
      align: 'right' as const,
      render: (b: Bom) => {
        const productLabel = productsById.get(b.product_id)?.name ?? `product #${b.product_id}`
        const options: ActionMenuOption[] = [
          { key: 'calculate', label: 'Calculate Requirements...', onSelect: () => openCalculate(b) },
          ...(canManage
            ? [
                { key: 'edit', label: 'Edit', onSelect: () => openEdit(b) },
                {
                  key: 'components',
                  label: 'Manage Components...',
                  onSelect: () => openManageComponents(b),
                },
                b.status === 'active'
                  ? { key: 'deactivate', label: 'Move to Draft', danger: true, onSelect: () => setStatusTarget(b) }
                  : { key: 'activate', label: 'Activate', onSelect: () => setStatusTarget(b) },
              ]
            : []),
        ]
        return <ActionMenu label={`Actions for ${productLabel}`} options={options} />
      },
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Bills of Materials"
        subtitle="For a given quantity of a Product, exactly how much of each Raw Material is required."
        actions={canManage ? <Button onClick={openCreate}>New BOM</Button> : undefined}
      />

      <Alert variant="danger">{pageError}</Alert>

      <FilterBar>
        <TextField
          label="Search"
          placeholder="Search by product name or code..."
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
        />
      </FilterBar>

      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(b) => b.id}
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
        emptyTitle={debouncedSearch ? 'No matching BOMs' : 'No BOMs yet'}
        emptyMessage={
          debouncedSearch
            ? 'Try a different search term.'
            : canManage
              ? 'Create the first BOM with the New BOM button above.'
              : 'No BOMs have been created yet.'
        }
      />

      {canManage && (
        <>
          <FormDialog
            open={formOpen}
            title={editingBom ? 'Edit BOM' : 'New BOM'}
            onClose={() => setFormOpen(false)}
            onSubmit={handleSubmit(onFormSubmit)}
            submitting={isSubmitting}
            submitLabel={editingBom ? 'Save' : 'Create BOM'}
          >
            <Alert variant="danger">{formError}</Alert>
            <SelectField
              label="Product"
              required
              disabled={!!editingBom}
              hint={editingBom ? 'Product cannot be changed after creation.' : undefined}
              {...register('product_id')}
              error={errors.product_id?.message}
            >
              <option value="">Select a product...</option>
              {products
                .filter((p) => p.is_active)
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.code})
                  </option>
                ))}
            </SelectField>
            <TextField
              label="Base Quantity"
              required
              hint="Expressed in the Product's own unit of measure."
              {...register('base_quantity')}
              error={errors.base_quantity?.message}
            />
            <TextareaField label="Notes" {...register('notes')} error={errors.notes?.message} />
          </FormDialog>

          <ConfirmDialog
            open={!!statusTarget}
            title={statusTarget?.status === 'active' ? 'Move BOM to draft' : 'Activate BOM'}
            message={
              statusError ??
              (statusTarget?.status === 'active'
                ? 'This BOM will no longer be usable to calculate production requirements.'
                : 'Every component will be re-checked for a valid unit conversion before activation.')
            }
            confirmLabel={statusTarget?.status === 'active' ? 'Move to draft' : 'Activate'}
            danger={statusTarget?.status === 'active'}
            busy={statusBusy}
            onConfirm={confirmStatusChange}
            onCancel={() => setStatusTarget(null)}
          />

          <Modal
            open={!!componentsDialogTarget}
            title={`Components for ${componentsDialogTarget ? (productsById.get(componentsDialogTarget.product_id)?.name ?? `product #${componentsDialogTarget.product_id}`) : ''}`}
            size="wide"
            onClose={closeManageComponents}
            footer={
              <Button variant="secondary" onClick={closeManageComponents}>
                Close
              </Button>
            }
          >
            <div className="flex flex-col gap-4">
              <Alert variant="danger">{componentFormError}</Alert>

              {componentsDialogTarget && componentsDialogTarget.components.length === 0 ? (
                <p className="text-sm text-gold-100/60">No components on this BOM yet.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                        <th className="py-2 pr-3">Raw Material</th>
                        <th className="py-2 pr-3">Quantity</th>
                        <th className="py-2 pr-3">UoM</th>
                        <th className="py-2 pr-3">%</th>
                        <th className="py-2 pr-3">Conversion Status</th>
                        <th className="py-2"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {componentsDialogTarget?.components.map((component) => {
                        const material = materialsById.get(component.raw_material_id)
                        const unit =
                          material?.unit_of_measure_id != null ? unitsById.get(material.unit_of_measure_id) : undefined
                        return (
                          <tr key={component.id} className="border-t border-ink-700 align-top">
                            <td className="py-2 pr-3">{material?.name ?? `#${component.raw_material_id}`}</td>
                            <td className="py-2 pr-3">{component.quantity}</td>
                            <td className="py-2 pr-3">{unit?.code ?? '—'}</td>
                            <td className="py-2 pr-3">
                              {component.percentage != null ? `${Number(component.percentage).toFixed(2)}%` : '—'}
                            </td>
                            <td className="py-2 pr-3 max-w-xs">
                              <Badge tone={component.conversion_ok ? 'success' : 'danger'}>
                                {component.conversion_ok ? 'OK' : 'Invalid'}
                              </Badge>
                              {component.conversion_error && (
                                <p className="mt-1 text-xs text-red-400">{component.conversion_error}</p>
                              )}
                            </td>
                            <td className="py-2 text-right">
                              <ActionMenu
                                label={`Actions for ${material?.name ?? 'component'}`}
                                options={[
                                  { key: 'edit', label: 'Edit', onSelect: () => openEditComponent(component) },
                                  {
                                    key: 'remove',
                                    label: 'Remove',
                                    danger: true,
                                    onSelect: () => setRemoveComponentTarget(component),
                                  },
                                ]}
                              />
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {!componentFormOpen && (
                <Button type="button" variant="secondary" onClick={openAddComponent}>
                  Add Component
                </Button>
              )}

              {componentFormOpen && (
                <form
                  onSubmit={componentForm.handleSubmit(onComponentFormSubmit)}
                  className="flex flex-col gap-4 rounded-md border border-ink-700 p-4"
                >
                  <SelectField
                    label="Raw Material"
                    required
                    disabled={!!editingComponent}
                    hint="Quantity is always expressed in the material's own unit of measure."
                    {...componentForm.register('raw_material_id')}
                    error={componentForm.formState.errors.raw_material_id?.message}
                  >
                    <option value="">Select a raw material...</option>
                    {materials
                      .filter((m) => m.is_active)
                      .map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name} ({m.code})
                        </option>
                      ))}
                  </SelectField>
                  <TextField
                    label="Quantity"
                    required
                    {...componentForm.register('quantity')}
                    error={componentForm.formState.errors.quantity?.message}
                  />
                  <div className="flex gap-2">
                    <Button type="submit" isLoading={componentForm.formState.isSubmitting}>
                      {editingComponent ? 'Save' : 'Add component'}
                    </Button>
                    <Button type="button" variant="secondary" onClick={() => setComponentFormOpen(false)}>
                      Cancel
                    </Button>
                  </div>
                </form>
              )}
            </div>
          </Modal>

          <ConfirmDialog
            open={!!removeComponentTarget}
            title="Remove component"
            message="This raw material will no longer be part of this BOM."
            confirmLabel="Remove"
            danger
            busy={removeComponentBusy}
            onConfirm={confirmRemoveComponent}
            onCancel={() => setRemoveComponentTarget(null)}
          />
        </>
      )}

      <Modal
        open={!!calculateTarget}
        title={`Calculate Requirements for ${calculateTarget ? (productsById.get(calculateTarget.product_id)?.name ?? `product #${calculateTarget.product_id}`) : ''}`}
        onClose={closeCalculate}
        footer={
          <Button variant="secondary" onClick={closeCalculate}>
            Close
          </Button>
        }
      >
        <form onSubmit={calculateForm.handleSubmit(onCalculateSubmit)} className="flex flex-col gap-4">
          <Alert variant="danger">{calculateError}</Alert>
          {calculateTarget?.status !== 'active' && (
            <Alert variant="warning">Only an active BOM can be used to calculate production requirements.</Alert>
          )}
          <TextField
            label="Production Quantity"
            required
            hint="Expressed in the Product's own unit of measure."
            {...calculateForm.register('production_quantity')}
            error={calculateForm.formState.errors.production_quantity?.message}
          />
          <Button type="submit" isLoading={calculateForm.formState.isSubmitting}>
            Calculate
          </Button>

          {requirements && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                    <th className="py-2 pr-3">Raw Material</th>
                    <th className="py-2 pr-3">Required Quantity</th>
                    <th className="py-2">UoM</th>
                  </tr>
                </thead>
                <tbody>
                  {requirements.map((line) => (
                    <tr key={line.raw_material_id} className="border-t border-ink-700">
                      <td className="py-2 pr-3">{materialsById.get(line.raw_material_id)?.name ?? `#${line.raw_material_id}`}</td>
                      <td className="py-2 pr-3">{line.required_quantity}</td>
                      <td className="py-2">{unitsById.get(line.unit_of_measure_id)?.code ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </form>
      </Modal>
    </div>
  )
}
