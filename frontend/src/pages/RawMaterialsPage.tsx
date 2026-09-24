import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ActionMenu, type ActionMenuOption } from "@/components/ui/ActionMenu";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { DataTable, type DataTableColumn } from "@/components/ui/DataTable";
import { FilterBar } from "@/components/ui/FilterBar";
import { FormPage } from "@/components/ui/FormPage";
import { Modal } from "@/components/ui/Modal";
import { PageHeader } from "@/components/ui/PageHeader";
import type { SortState } from "@/components/ui/sort";
import { CheckboxField } from "@/components/forms/CheckboxField";
import { SelectField } from "@/components/forms/SelectField";
import { TextField } from "@/components/forms/TextField";
import { TextareaField } from "@/components/forms/TextareaField";
import { ApiError, apiClient } from "@/lib/apiClient";
import { useAuth } from "@/lib/auth/AuthContext";
import { isAdminRole } from "@/lib/auth/roles";
import { useDebouncedValue } from "@/lib/useDebouncedValue";
import { useServerTable, type ServerTableResult } from "@/lib/useServerTable";
import { useFormRoute } from "@/lib/useFormRoute";

/** Mirrors backend/app/schemas/raw_material.py's RawMaterialOut.
 * `alternate_conversion_*` is BOM's material-specific conversion
 * mechanism (docs/modules/boms.md #3, docs/modules/raw_materials.md
 * #5a) -- both null, or both set. */
interface RawMaterial {
  id: number;
  organisation_id: number;
  code: string;
  name: string;
  category_id: number;
  unit_of_measure_id: number;
  description: string | null;
  reference_cost: string | null;
  alternate_conversion_unit_of_measure_id: number | null;
  alternate_conversion_factor: string | null;
  is_active: boolean;
}

/** Mirrors backend/app/schemas/raw_material.py's SupplierMaterialOut --
 * the Supplier <-> Raw Material relationship, the one part of this
 * module built with real depth (docs/modules/raw_materials.md #6). */
interface SupplierMaterial {
  id: number;
  supplier_id: number;
  raw_material_id: number;
  supplier_material_code: string | null;
  purchase_price: string | null;
  lead_time_days: number | null;
  moq: string | null;
  max_supply_quantity: string | null;
  is_preferred: boolean;
  is_active: boolean;
}

interface LookupOption {
  id: number;
  name: string;
  code: string | null;
  is_active: boolean;
}

interface PaginatedResponse<T> {
  data: T[];
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
  };
}

interface RawMaterialsFilters {
  search: string;
}

const DECIMAL_RE = /^\d+(\.\d{1,4})?$/;
const INTEGER_RE = /^\d+$/;

const materialSchema = z
  .object({
    name: z.string().min(1, "Name is required"),
    category_id: z.string().min(1, "Category is required"),
    unit_of_measure_id: z.string().min(1, "Unit of measure is required"),
    description: z.string(),
    reference_cost: z
      .string()
      .refine((v) => v === "" || DECIMAL_RE.test(v), "Enter a valid amount"),
    alternate_conversion_unit_of_measure_id: z.string(),
    alternate_conversion_factor: z
      .string()
      .refine((v) => v === "" || DECIMAL_RE.test(v), "Enter a valid factor"),
  })
  // Both-or-neither, same discipline as UnitOfMeasure's Dimension/
  // Conversion Factor pair (docs/modules/boms.md #3).
  .refine(
    (data) =>
      (data.alternate_conversion_unit_of_measure_id.trim() === "") ===
      (data.alternate_conversion_factor.trim() === ""),
    {
      message:
        "Alternate conversion unit and factor must be provided together, or both left blank.",
      path: ["alternate_conversion_factor"],
    },
  )
  .refine(
    (data) =>
      data.alternate_conversion_unit_of_measure_id === "" ||
      data.alternate_conversion_unit_of_measure_id !==
        data.unit_of_measure_id,
    {
      message: "Alternate conversion unit must differ from the material's own unit.",
      path: ["alternate_conversion_unit_of_measure_id"],
    },
  );

type MaterialFormValues = z.infer<typeof materialSchema>;

const emptyMaterialDefaults: MaterialFormValues = {
  name: "",
  category_id: "",
  unit_of_measure_id: "",
  description: "",
  reference_cost: "",
  alternate_conversion_unit_of_measure_id: "",
  alternate_conversion_factor: "",
};

function toMaterialFormValues(material: RawMaterial): MaterialFormValues {
  return {
    name: material.name,
    category_id: String(material.category_id),
    unit_of_measure_id: String(material.unit_of_measure_id),
    description: material.description ?? "",
    reference_cost: material.reference_cost ?? "",
    alternate_conversion_unit_of_measure_id:
      material.alternate_conversion_unit_of_measure_id == null
        ? ""
        : String(material.alternate_conversion_unit_of_measure_id),
    alternate_conversion_factor: material.alternate_conversion_factor ?? "",
  };
}

const linkSchema = z.object({
  supplier_id: z.string().min(1, "Supplier is required"),
  supplier_material_code: z.string(),
  purchase_price: z
    .string()
    .refine((v) => v === "" || DECIMAL_RE.test(v), "Enter a valid amount"),
  lead_time_days: z
    .string()
    .refine(
      (v) => v === "" || INTEGER_RE.test(v),
      "Enter a whole number of days",
    ),
  moq: z
    .string()
    .refine((v) => v === "" || DECIMAL_RE.test(v), "Enter a valid quantity"),
  max_supply_quantity: z
    .string()
    .refine((v) => v === "" || DECIMAL_RE.test(v), "Enter a valid quantity"),
  is_preferred: z.boolean(),
});

type LinkFormValues = z.infer<typeof linkSchema>;

const emptyLinkDefaults: LinkFormValues = {
  supplier_id: "",
  supplier_material_code: "",
  purchase_price: "",
  lead_time_days: "",
  moq: "",
  max_supply_quantity: "",
  is_preferred: false,
};

function toLinkFormValues(link: SupplierMaterial): LinkFormValues {
  return {
    supplier_id: String(link.supplier_id),
    supplier_material_code: link.supplier_material_code ?? "",
    purchase_price: link.purchase_price ?? "",
    lead_time_days:
      link.lead_time_days == null ? "" : String(link.lead_time_days),
    moq: link.moq ?? "",
    max_supply_quantity: link.max_supply_quantity ?? "",
    is_preferred: link.is_preferred,
  };
}

async function fetchRawMaterials({
  page,
  pageSize,
  sort,
  filters,
}: {
  page: number;
  pageSize: number;
  sort: SortState | null;
  filters: RawMaterialsFilters;
}): Promise<ServerTableResult<RawMaterial>> {
  // The common list contract (docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md).
  const { data } = await apiClient.get<PaginatedResponse<RawMaterial>>(
    "/api/raw-materials",
    {
      params: {
        page,
        page_size: pageSize,
        sort_by: sort?.field,
        sort_direction: sort?.direction,
        include_inactive: true,
        q: filters.search || undefined,
      },
    },
  );
  return { rows: data.data, total: data.pagination.total };
}

/** The authoritative material identity bridging Supplier -> Purchase
 * Order -> Receipt -> Inventory on one side, and BOM -> Production on
 * the other (backend/app/api/raw_materials.py,
 * docs/modules/raw_materials.md). The master itself is as flat and
 * admin-gated as Category/Unit/Supplier/Product -- the one addition is
 * "Manage Suppliers" per row, opening the Supplier <-> Raw Material
 * relationship dialog (docs/modules/raw_materials.md #6), the single
 * piece of this module built with real relational depth. That
 * relationship is live-managed (add/edit/remove), not a read-only
 * summary -- "Used in BOMs"/"Current Stock" summaries are deliberately
 * not built here since BOM/Inventory don't exist yet to source them
 * from. */
export function RawMaterialsPage() {
  const { user: currentUser } = useAuth();
  const canManage = isAdminRole(currentUser?.role);

  const [categories, setCategories] = useState<LookupOption[]>([]);
  const [units, setUnits] = useState<LookupOption[]>([]);
  const [suppliers, setSuppliers] = useState<LookupOption[]>([]);
  const [pageError, setPageError] = useState<string | undefined>(undefined);

  const [searchInput, setSearchInput] = useState("");
  const debouncedSearch = useDebouncedValue(searchInput, 300);

  const [editingMaterial, setEditingMaterial] = useState<RawMaterial | null>(
    null,
  );
  const [formError, setFormError] = useState<string | null>(null);

  const [statusTarget, setStatusTarget] = useState<RawMaterial | null>(null);
  const [statusBusy, setStatusBusy] = useState(false);

  // --- Manage Suppliers dialog state ---
  const [suppliersDialogTarget, setSuppliersDialogTarget] =
    useState<RawMaterial | null>(null);
  const [links, setLinks] = useState<SupplierMaterial[]>([]);
  const [linksLoading, setLinksLoading] = useState(false);
  const [linksError, setLinksError] = useState<string | undefined>(undefined);
  const [editingLink, setEditingLink] = useState<SupplierMaterial | null>(null);
  const [linkFormOpen, setLinkFormOpen] = useState(false);
  const [linkFormError, setLinkFormError] = useState<string | null>(null);
  const [removeLinkTarget, setRemoveLinkTarget] =
    useState<SupplierMaterial | null>(null);
  const [removeLinkBusy, setRemoveLinkBusy] = useState(false);

  const {
    register,
    watch,
    handleSubmit,
    reset,
    setError: setFieldError,
    formState: { errors, isSubmitting },
  } = useForm<MaterialFormValues>({
    resolver: zodResolver(materialSchema),
    defaultValues: emptyMaterialDefaults,
  });

  const linkForm = useForm<LinkFormValues>({
    resolver: zodResolver(linkSchema),
    defaultValues: emptyLinkDefaults,
  });

  const table = useServerTable<RawMaterial, RawMaterialsFilters>({
    fetcher: fetchRawMaterials,
    pageSize: 20,
    initialFilters: { search: "" },
  });

  const isFirstSearchRender = useRef(true);
  useEffect(() => {
    if (isFirstSearchRender.current) {
      isFirstSearchRender.current = false;
      return;
    }
    table.setFilters({ search: debouncedSearch });
  }, [debouncedSearch]);

  const categoriesById = useMemo(
    () => new Map(categories.map((c) => [c.id, c])),
    [categories],
  );
  const unitsById = useMemo(
    () => new Map(units.map((u) => [u.id, u])),
    [units],
  );
  const suppliersById = useMemo(
    () => new Map(suppliers.map((s) => [s.id, s])),
    [suppliers],
  );

  const loadLookups = useCallback(async () => {
    try {
      const [categoriesResponse, unitsResponse, suppliersResponse] =
        await Promise.all([
          apiClient.get<PaginatedResponse<LookupOption>>("/api/categories", {
            params: { page_size: 200, applies_to: "raw_material", include_inactive: true },
          }),
          apiClient.get<PaginatedResponse<LookupOption>>(
            "/api/units-of-measure",
            { params: { page_size: 200 } },
          ),
          apiClient.get<PaginatedResponse<LookupOption>>("/api/suppliers", {
            params: { page_size: 200 },
          }),
        ]);
      setCategories(categoriesResponse.data.data);
      setUnits(unitsResponse.data.data);
      setSuppliers(suppliersResponse.data.data);
    } catch (err) {
      setPageError(
        err instanceof ApiError
          ? err.message
          : "Failed to load categories, units, and suppliers.",
      );
    }
  }, []);

  useEffect(() => {
    // Everyone needs the names for the list; only the form needs is_active.
    void loadLookups();
  }, [loadLookups]);

  function prepareCreate() {
    setEditingMaterial(null);
    reset(emptyMaterialDefaults);
    setFormError(null);
  }

  function prepareEdit(material: RawMaterial) {
    setEditingMaterial(material);
    reset(toMaterialFormValues(material));
    setFormError(null);
  }

  const { formOpen, loading: formLoading, loadError: formLoadError, openCreate, openEdit, closeForm } = useFormRoute<RawMaterial>(
    "/raw-materials",
    "/api/raw-materials",
    { onCreate: prepareCreate, onEdit: prepareEdit },
  );

  const onFormSubmit = useCallback(
    async (values: MaterialFormValues) => {
      setFormError(null);
      const payload = {
        name: values.name,
        category_id: Number(values.category_id),
        unit_of_measure_id: Number(values.unit_of_measure_id),
        description: values.description || null,
        reference_cost: values.reference_cost || null,
        alternate_conversion_unit_of_measure_id:
          values.alternate_conversion_unit_of_measure_id
            ? Number(values.alternate_conversion_unit_of_measure_id)
            : null,
        alternate_conversion_factor: values.alternate_conversion_factor || null,
      };
      try {
        if (editingMaterial) {
          await apiClient.patch(
            `/api/raw-materials/${editingMaterial.id}`,
            payload,
          );
        } else {
          await apiClient.post("/api/raw-materials", payload);
        }
        closeForm();
        table.refetch();
      } catch (err) {
        if (err instanceof ApiError) {
          if (err.fields) {
            for (const [field, message] of Object.entries(err.fields)) {
              if (field in emptyMaterialDefaults)
                setFieldError(field as keyof MaterialFormValues, { message });
            }
          }
          setFormError(err.message);
        } else {
          setFormError("Something went wrong. Please try again.");
        }
      }
    },
    [editingMaterial, setFieldError, table],
  );

  async function confirmStatusChange() {
    if (!statusTarget) return;
    setStatusBusy(true);
    setPageError(undefined);
    try {
      await apiClient.patch(`/api/raw-materials/${statusTarget.id}/status`, {
        is_active: !statusTarget.is_active,
      });
      setStatusTarget(null);
      table.refetch();
    } catch (err) {
      setPageError(
        err instanceof ApiError ? err.message : "Failed to change status.",
      );
    } finally {
      setStatusBusy(false);
    }
  }

  // --- Manage Suppliers dialog logic ---

  const loadLinks = useCallback(async (materialId: number) => {
    setLinksLoading(true);
    setLinksError(undefined);
    try {
      const { data } = await apiClient.get<SupplierMaterial[]>(
        `/api/raw-materials/${materialId}/suppliers`,
      );
      setLinks(data);
    } catch (err) {
      setLinksError(
        err instanceof ApiError ? err.message : "Failed to load suppliers.",
      );
    } finally {
      setLinksLoading(false);
    }
  }, []);

  function openManageSuppliers(material: RawMaterial) {
    setSuppliersDialogTarget(material);
    setEditingLink(null);
    setLinkFormOpen(false);
    void loadLinks(material.id);
  }

  function closeManageSuppliers() {
    setSuppliersDialogTarget(null);
    setLinks([]);
    setLinkFormOpen(false);
    setEditingLink(null);
  }

  function openAddLink() {
    setEditingLink(null);
    linkForm.reset(emptyLinkDefaults);
    setLinkFormError(null);
    setLinkFormOpen(true);
  }

  function openEditLink(link: SupplierMaterial) {
    setEditingLink(link);
    linkForm.reset(toLinkFormValues(link));
    setLinkFormError(null);
    setLinkFormOpen(true);
  }

  const onLinkFormSubmit = useCallback(
    async (values: LinkFormValues) => {
      if (!suppliersDialogTarget) return;
      setLinkFormError(null);
      const payload = {
        supplier_material_code: values.supplier_material_code || null,
        purchase_price: values.purchase_price || null,
        lead_time_days:
          values.lead_time_days === "" ? null : Number(values.lead_time_days),
        moq: values.moq || null,
        max_supply_quantity: values.max_supply_quantity || null,
        is_preferred: values.is_preferred,
      };
      try {
        if (editingLink) {
          await apiClient.patch(
            `/api/raw-materials/${suppliersDialogTarget.id}/suppliers/${editingLink.id}`,
            payload,
          );
        } else {
          await apiClient.post(
            `/api/raw-materials/${suppliersDialogTarget.id}/suppliers`,
            {
              ...payload,
              supplier_id: Number(values.supplier_id),
            },
          );
        }
        setLinkFormOpen(false);
        void loadLinks(suppliersDialogTarget.id);
      } catch (err) {
        if (err instanceof ApiError) {
          setLinkFormError(err.message);
        } else {
          setLinkFormError("Something went wrong. Please try again.");
        }
      }
    },
    [editingLink, suppliersDialogTarget, loadLinks],
  );

  async function confirmRemoveLink() {
    if (!suppliersDialogTarget || !removeLinkTarget) return;
    setRemoveLinkBusy(true);
    setLinksError(undefined);
    try {
      await apiClient.delete(
        `/api/raw-materials/${suppliersDialogTarget.id}/suppliers/${removeLinkTarget.id}`,
      );
      setRemoveLinkTarget(null);
      void loadLinks(suppliersDialogTarget.id);
    } catch (err) {
      setLinksError(
        err instanceof ApiError ? err.message : "Failed to remove supplier.",
      );
    } finally {
      setRemoveLinkBusy(false);
    }
  }

  const columns: DataTableColumn<RawMaterial>[] = [
    {
      key: "code",
      label: "Code",
      sortable: true,
      hideBelow: "sm",
      render: (m) => m.code,
    },
    {
      key: "name",
      label: "Raw Material",
      sortable: true,
      render: (m) => m.name,
    },
    {
      key: "category",
      label: "Category",
      hideBelow: "md",
      render: (m) =>
        categoriesById.get(m.category_id)?.name ?? (
          <span className="text-gold-100/40">—</span>
        ),
    },
    {
      key: "unit",
      label: "UoM",
      hideBelow: "lg",
      render: (m) =>
        unitsById.get(m.unit_of_measure_id)?.code ?? (
          <span className="text-gold-100/40">—</span>
        ),
    },
    {
      key: "status",
      label: "Status",
      render: (m) => (
        <Badge tone={m.is_active ? "success" : "danger"}>
          {m.is_active ? "Active" : "Inactive"}
        </Badge>
      ),
    },
    ...(canManage
      ? [
          {
            key: "actions",
            label: "",
            alwaysVisible: true,
            align: "right" as const,
            render: (m: RawMaterial) => {
              const options: ActionMenuOption[] = [
                { key: "edit", label: "Edit", onSelect: () => openEdit(m) },
                {
                  key: "suppliers",
                  label: "Manage Suppliers...",
                  onSelect: () => openManageSuppliers(m),
                },
                m.is_active
                  ? {
                      key: "deactivate",
                      label: "Deactivate",
                      danger: true,
                      onSelect: () => setStatusTarget(m),
                    }
                  : {
                      key: "activate",
                      label: "Activate",
                      onSelect: () => setStatusTarget(m),
                    },
              ];
              return (
                <ActionMenu label={`Actions for ${m.name}`} options={options} />
              );
            },
          },
        ]
      : []),
  ];

  return (
    <div className="space-y-6">
      <div hidden={formOpen} className="space-y-6">
        <PageHeader
          title="Raw Materials"
          subtitle="The authoritative material identity for Procurement and Production."
          actions={
            canManage ? (
              <Button onClick={openCreate}>New Raw Material</Button>
            ) : undefined
          }
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
          rowKey={(m) => m.id}
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
          emptyTitle={
            debouncedSearch ? "No matching raw materials" : "No raw materials yet"
          }
          emptyMessage={
            debouncedSearch
              ? "Try a different search term."
              : canManage
                ? "Create the first raw material with the New Raw Material button above."
                : "No raw materials have been created yet."
          }
        />
      </div>

      {canManage && (
        <>
          <FormPage
            loading={formLoading}
            loadError={formLoadError}
            open={formOpen}
            title={editingMaterial ? "Edit Raw Material" : "New Raw Material"}
            onClose={closeForm}
            onSubmit={handleSubmit(onFormSubmit)}
            submitting={isSubmitting}
            submitLabel={editingMaterial ? "Save" : "Create raw material"}
          >
            <Alert variant="danger">{formError}</Alert>
            {editingMaterial && (
              <TextField
                label="Code"
                disabled
                readOnly
                hint="System-generated. Cannot be changed."
                value={editingMaterial.code}
              />
            )}
            <TextField
              label="Name"
              required
              {...register("name")}
              error={errors.name?.message}
            />
            <SelectField
              label="Category"
              required
              {...register("category_id")}
              error={errors.category_id?.message}
            >
              <option value="">Select a category...</option>
              {categories
                .filter((c) => c.is_active || String(c.id) === watch("category_id"))
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
            </SelectField>
            <SelectField
              label="Unit of Measure"
              required
              {...register("unit_of_measure_id")}
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
            <TextareaField
              label="Description / Specification"
              {...register("description")}
              error={errors.description?.message}
            />
            <TextField
              label="Reference Cost"
              hint="Current/default reference value only -- not a historical purchase price."
              {...register("reference_cost")}
              error={errors.reference_cost?.message}
            />
            <SelectField
              label="Alternate Conversion Unit"
              hint="Optional. For BOM: a material-specific conversion, e.g. a Litre of this material weighs some number of kg. Leave blank if this material needs no such conversion."
              {...register("alternate_conversion_unit_of_measure_id")}
              error={errors.alternate_conversion_unit_of_measure_id?.message}
            >
              <option value="">None</option>
              {units
                .filter((u) => u.is_active)
                .map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name} ({u.code})
                  </option>
                ))}
            </SelectField>
            <TextField
              label="Alternate Conversion Factor"
              hint="Optional. 1 [this material's own unit] = this many [Alternate Conversion Unit]. Must be set together with Alternate Conversion Unit."
              {...register("alternate_conversion_factor")}
              error={errors.alternate_conversion_factor?.message}
            />
          </FormPage>

          <ConfirmDialog
            open={!!statusTarget}
            title={
              statusTarget?.is_active
                ? "Deactivate raw material"
                : "Activate raw material"
            }
            message={
              statusTarget?.is_active
                ? `${statusTarget.name} will no longer be selectable for new records. Existing records that reference it are unaffected.`
                : `${statusTarget?.name ?? ""} will be selectable for new records again.`
            }
            confirmLabel={statusTarget?.is_active ? "Deactivate" : "Activate"}
            danger={statusTarget?.is_active}
            busy={statusBusy}
            onConfirm={confirmStatusChange}
            onCancel={() => setStatusTarget(null)}
          />

          <Modal
            open={!!suppliersDialogTarget}
            title={`Suppliers for ${suppliersDialogTarget?.name ?? ""}`}
            size="wide"
            onClose={closeManageSuppliers}
            footer={
              <Button variant="secondary" onClick={closeManageSuppliers}>
                Close
              </Button>
            }
          >
            <div className="flex flex-col gap-4">
              <Alert variant="danger">{linksError}</Alert>

              {linksLoading ? (
                <p className="text-sm text-gold-100/60">Loading suppliers...</p>
              ) : links.length === 0 ? (
                <p className="text-sm text-gold-100/60">
                  No suppliers linked to this material yet.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                        <th className="py-2 pr-3">Supplier</th>
                        <th className="py-2 pr-3">Supplier Code</th>
                        <th className="py-2 pr-3">Price</th>
                        <th className="py-2 pr-3">Lead Time</th>
                        <th className="py-2 pr-3">MOQ</th>
                        <th className="py-2 pr-3">Max Supply</th>
                        <th className="py-2 pr-3"></th>
                        <th className="py-2"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {links.map((link) => (
                        <tr key={link.id} className="border-t border-ink-700">
                          <td className="py-2 pr-3">
                            {suppliersById.get(link.supplier_id)?.name ??
                              `#${link.supplier_id}`}
                          </td>
                          <td className="py-2 pr-3">
                            {link.supplier_material_code ?? "—"}
                          </td>
                          <td className="py-2 pr-3">
                            {link.purchase_price ?? "—"}
                          </td>
                          <td className="py-2 pr-3">
                            {link.lead_time_days ?? "—"}
                          </td>
                          <td className="py-2 pr-3">{link.moq ?? "—"}</td>
                          <td className="py-2 pr-3">
                            {link.max_supply_quantity ?? "—"}
                          </td>
                          <td className="py-2 pr-3">
                            {link.is_preferred && (
                              <Badge tone="info">Preferred</Badge>
                            )}
                            {!link.is_active && (
                              <Badge tone="danger">Inactive</Badge>
                            )}
                          </td>
                          <td className="py-2 text-right">
                            <ActionMenu
                              label={`Actions for ${suppliersById.get(link.supplier_id)?.name ?? "supplier"}`}
                              options={[
                                {
                                  key: "edit",
                                  label: "Edit",
                                  onSelect: () => openEditLink(link),
                                },
                                {
                                  key: "remove",
                                  label: "Remove",
                                  danger: true,
                                  onSelect: () => setRemoveLinkTarget(link),
                                },
                              ]}
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {!linkFormOpen && (
                <Button type="button" variant="secondary" onClick={openAddLink}>
                  Add Supplier
                </Button>
              )}

              {linkFormOpen && (
                <form
                  onSubmit={linkForm.handleSubmit(onLinkFormSubmit)}
                  className="flex flex-col gap-4 rounded-md border border-ink-700 p-4"
                >
                  <Alert variant="danger">{linkFormError}</Alert>
                  <SelectField
                    label="Supplier"
                    required
                    disabled={!!editingLink}
                    {...linkForm.register("supplier_id")}
                    error={linkForm.formState.errors.supplier_id?.message}
                  >
                    <option value="">Select a supplier...</option>
                    {suppliers
                      .filter((s) => s.is_active)
                      .map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.name}
                        </option>
                      ))}
                  </SelectField>
                  <TextField
                    label="Supplier's Material Code"
                    {...linkForm.register("supplier_material_code")}
                    error={
                      linkForm.formState.errors.supplier_material_code?.message
                    }
                  />
                  <TextField
                    label="Purchase Price"
                    {...linkForm.register("purchase_price")}
                    error={linkForm.formState.errors.purchase_price?.message}
                  />
                  <TextField
                    label="Lead Time (days)"
                    {...linkForm.register("lead_time_days")}
                    error={linkForm.formState.errors.lead_time_days?.message}
                  />
                  <TextField
                    label="MOQ"
                    {...linkForm.register("moq")}
                    error={linkForm.formState.errors.moq?.message}
                  />
                  <TextField
                    label="Max Supply Quantity"
                    {...linkForm.register("max_supply_quantity")}
                    error={
                      linkForm.formState.errors.max_supply_quantity?.message
                    }
                  />
                  <CheckboxField
                    label="Preferred supplier for this material"
                    {...linkForm.register("is_preferred")}
                  />
                  <div className="flex gap-2">
                    <Button
                      type="submit"
                      isLoading={linkForm.formState.isSubmitting}
                    >
                      {editingLink ? "Save" : "Add supplier"}
                    </Button>
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() => setLinkFormOpen(false)}
                    >
                      Cancel
                    </Button>
                  </div>
                </form>
              )}
            </div>
          </Modal>

          <ConfirmDialog
            open={!!removeLinkTarget}
            title="Remove supplier relationship"
            message={`This supplier will no longer be listed as able to supply ${suppliersDialogTarget?.name ?? "this material"}.`}
            confirmLabel="Remove"
            danger
            busy={removeLinkBusy}
            onConfirm={confirmRemoveLink}
            onCancel={() => setRemoveLinkTarget(null)}
          />
        </>
      )}
    </div>
  );
}
