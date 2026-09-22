import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { apiClient, setOnSessionExpired } from '@/lib/apiClient'
import { clearStoredTokens, getStoredTokens, setStoredTokens } from './tokenStorage'
import type { TokenResponse, User } from './types'

interface AuthContextValue {
  user: User | null
  /** True until the initial session-rehydration check (or an
   * in-progress login) resolves -- RequireAuth shows a loading state
   * rather than bouncing straight to /login while this is true. */
  isLoading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const loadCurrentUser = useCallback(async () => {
    if (!getStoredTokens()) {
      setUser(null)
      setIsLoading(false)
      return
    }
    try {
      const { data } = await apiClient.get<User>('/api/auth/me')
      setUser(data)
    } catch {
      // apiClient's own response interceptor already clears storage on
      // a genuine 401/refresh failure; any other error (e.g. offline)
      // just leaves the user logged out for this load -- the stored
      // tokens are untouched, so the next successful load recovers.
      setUser(null)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    // Registered once, for the provider's whole lifetime -- a refresh
    // failure on any request, on any page, clears local auth state the
    // same way an explicit logout does.
    setOnSessionExpired(() => setUser(null))
    loadCurrentUser()
    return () => setOnSessionExpired(null)
  }, [loadCurrentUser])

  const login = useCallback(async (username: string, password: string) => {
    const { data } = await apiClient.post<TokenResponse>('/api/auth/login', { username, password })
    setStoredTokens({ accessToken: data.access_token, refreshToken: data.refresh_token })
    const { data: currentUser } = await apiClient.get<User>('/api/auth/me')
    setUser(currentUser)
  }, [])

  const logout = useCallback(async () => {
    const tokens = getStoredTokens()
    if (tokens) {
      try {
        await apiClient.post('/api/auth/logout', { refresh_token: tokens.refreshToken })
      } catch {
        // Best-effort server-side revocation -- local state clears
        // either way, mirroring auth_service.logout()'s own idempotent
        // handling of an already-invalid token.
      }
    }
    clearStoredTokens()
    setUser(null)
  }, [])

  const value = useMemo(() => ({ user, isLoading, login, logout }), [user, isLoading, login, logout])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within an AuthProvider.')
  return context
}
