import { Route, Routes } from 'react-router-dom'
import { AppLayout } from '@/components/layout/AppLayout'
import { RequireAuth } from '@/components/routing/RequireAuth'
import { AuthProvider } from '@/lib/auth/AuthContext'
import { BomsPage } from '@/pages/BomsPage'
import { CategoriesPage } from '@/pages/CategoriesPage'
import { CustomersPage } from '@/pages/CustomersPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { EmailSettingsPage } from '@/pages/EmailSettingsPage'
import { LoginPage } from '@/pages/LoginPage'
import { OrganisationSettingsPage } from '@/pages/OrganisationSettingsPage'
import { ProductsPage } from '@/pages/ProductsPage'
import { MachinesPage } from '@/pages/MachinesPage'
import { ProductionLinesPage } from '@/pages/ProductionLinesPage'
import { RawMaterialsPage } from '@/pages/RawMaterialsPage'
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
          <Route path="/customers" element={<CustomersPage />} />
          <Route path="/units-of-measure" element={<UnitsOfMeasurePage />} />
          <Route path="/suppliers" element={<SuppliersPage />} />
          <Route path="/products" element={<ProductsPage />} />
          <Route path="/raw-materials" element={<RawMaterialsPage />} />
          <Route path="/production-lines" element={<ProductionLinesPage />} />
          <Route path="/machines" element={<MachinesPage />} />
          <Route path="/warehouses" element={<WarehousesPage />} />
          <Route path="/boms" element={<BomsPage />} />
          <Route path="/users" element={<UsersPage />} />
          <Route path="/settings/organisation" element={<OrganisationSettingsPage />} />
          <Route path="/settings/email" element={<EmailSettingsPage />} />
          <Route path="/styleguide" element={<StyleGuidePage />} />
        </Route>
      </Routes>
    </AuthProvider>
  )
}
