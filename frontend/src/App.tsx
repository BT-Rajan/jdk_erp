import { Route, Routes } from 'react-router-dom'
import { AppLayout } from '@/components/layout/AppLayout'
import { RequireAuth } from '@/components/routing/RequireAuth'
import { AuthProvider } from '@/lib/auth/AuthContext'
import { BomsPage } from '@/pages/BomsPage'
import { CategoriesPage } from '@/pages/CategoriesPage'
import { CustomersPage } from '@/pages/CustomersPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { DocumentSettingsPage } from '@/pages/DocumentSettingsPage'
import { EmailSettingsPage } from '@/pages/EmailSettingsPage'
import { FinancePaymentsPage } from '@/pages/FinancePaymentsPage'
import { GoodsReceivingPage } from '@/pages/GoodsReceivingPage'
import { InventoryAdjustmentsPage } from '@/pages/InventoryAdjustmentsPage'
import { InventoryOpeningStockPage } from '@/pages/InventoryOpeningStockPage'
import { LoginPage } from '@/pages/LoginPage'
import { OrganisationSettingsPage } from '@/pages/OrganisationSettingsPage'
import { ProductsPage } from '@/pages/ProductsPage'
import { MachinesPage } from '@/pages/MachinesPage'
import { ProductionLinesPage } from '@/pages/ProductionLinesPage'
import { PurchaseOrderFormPage } from '@/pages/PurchaseOrderFormPage'
import { PurchaseOrdersPage } from '@/pages/PurchaseOrdersPage'
import { RawMaterialsPage } from '@/pages/RawMaterialsPage'
import { RfqFormPage } from '@/pages/RfqFormPage'
import { RfqsPage } from '@/pages/RfqsPage'
import { WarehousesPage } from '@/pages/WarehousesPage'
import { StyleGuidePage } from '@/pages/StyleGuidePage'
import { SuppliersPage } from '@/pages/SuppliersPage'
import { UnitsOfMeasurePage } from '@/pages/UnitsOfMeasurePage'
import { UsersPage } from '@/pages/UsersPage'

/** The app's one route table. `/login` is the only public route;
 * everything else renders inside AppLayout, gated by RequireAuth
 * (docs/modules/authentication.md). A future module adds a `<Route>`
 * here and a NAV_ENTRIES entry in components/layout/AppLayout.tsx --
 * nothing else in this file changes. */
export function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <RequireAuth>
              <AppLayout />
            </RequireAuth>
          }
        >
          <Route path="/" element={<DashboardPage />} />
          <Route path="/categories" element={<CategoriesPage />} />
          <Route path="/categories/new" element={<CategoriesPage />} />
          <Route path="/categories/:recordId/edit" element={<CategoriesPage />} />
          <Route path="/customers" element={<CustomersPage />} />
          <Route path="/customers/new" element={<CustomersPage />} />
          <Route path="/customers/:recordId/edit" element={<CustomersPage />} />
          <Route path="/units-of-measure" element={<UnitsOfMeasurePage />} />
          <Route path="/units-of-measure/new" element={<UnitsOfMeasurePage />} />
          <Route path="/units-of-measure/:recordId/edit" element={<UnitsOfMeasurePage />} />
          <Route path="/suppliers" element={<SuppliersPage />} />
          <Route path="/suppliers/new" element={<SuppliersPage />} />
          <Route path="/suppliers/:recordId/edit" element={<SuppliersPage />} />
          <Route path="/products" element={<ProductsPage />} />
          <Route path="/products/new" element={<ProductsPage />} />
          <Route path="/products/:recordId/edit" element={<ProductsPage />} />
          <Route path="/raw-materials" element={<RawMaterialsPage />} />
          <Route path="/raw-materials/new" element={<RawMaterialsPage />} />
          <Route path="/raw-materials/:recordId/edit" element={<RawMaterialsPage />} />
          <Route path="/production-lines" element={<ProductionLinesPage />} />
          <Route path="/production-lines/new" element={<ProductionLinesPage />} />
          <Route path="/production-lines/:recordId/edit" element={<ProductionLinesPage />} />
          <Route path="/machines" element={<MachinesPage />} />
          <Route path="/machines/new" element={<MachinesPage />} />
          <Route path="/machines/:recordId/edit" element={<MachinesPage />} />
          <Route path="/warehouses" element={<WarehousesPage />} />
          <Route path="/warehouses/new" element={<WarehousesPage />} />
          <Route path="/warehouses/:recordId/edit" element={<WarehousesPage />} />
          <Route path="/boms" element={<BomsPage />} />
          <Route path="/boms/new" element={<BomsPage />} />
          <Route path="/boms/:recordId/edit" element={<BomsPage />} />
          <Route path="/rfqs" element={<RfqsPage />} />
          <Route path="/rfqs/new" element={<RfqFormPage />} />
          <Route path="/rfqs/:rfqId" element={<RfqsPage />} />
          <Route path="/rfqs/:rfqId/edit" element={<RfqFormPage />} />
          <Route path="/purchase-orders" element={<PurchaseOrdersPage />} />
          <Route path="/purchase-orders/new" element={<PurchaseOrderFormPage />} />
          <Route path="/purchase-orders/:purchaseOrderId" element={<PurchaseOrdersPage />} />
          <Route path="/purchase-orders/:purchaseOrderId/edit" element={<PurchaseOrderFormPage />} />
          <Route path="/receiving" element={<GoodsReceivingPage />} />
          <Route path="/inventory/adjustments" element={<InventoryAdjustmentsPage />} />
          <Route path="/inventory/opening-stock" element={<InventoryOpeningStockPage />} />
          <Route path="/finance/payments" element={<FinancePaymentsPage />} />
          <Route path="/finance/payments/:purchaseOrderId" element={<FinancePaymentsPage />} />
          <Route path="/users" element={<UsersPage />} />
          <Route path="/settings/organisation" element={<OrganisationSettingsPage />} />
          <Route path="/settings/email" element={<EmailSettingsPage />} />
          <Route path="/settings/documents" element={<DocumentSettingsPage />} />
          <Route path="/styleguide" element={<StyleGuidePage />} />
        </Route>
      </Routes>
    </AuthProvider>
  )
}
