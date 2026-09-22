import { Route, Routes } from 'react-router-dom'
import { AppLayout } from '@/components/layout/AppLayout'
import { RequireAuth } from '@/components/routing/RequireAuth'
import { AuthProvider } from '@/lib/auth/AuthContext'
import { DashboardPage } from '@/pages/DashboardPage'
import { EmailSettingsPage } from '@/pages/EmailSettingsPage'
import { LoginPage } from '@/pages/LoginPage'
import { OrganisationSettingsPage } from '@/pages/OrganisationSettingsPage'
import { StyleGuidePage } from '@/pages/StyleGuidePage'
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
          <Route path="/users" element={<UsersPage />} />
          <Route path="/settings/organisation" element={<OrganisationSettingsPage />} />
          <Route path="/settings/email" element={<EmailSettingsPage />} />
          <Route path="/styleguide" element={<StyleGuidePage />} />
        </Route>
      </Routes>
    </AuthProvider>
  )
}
