import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { clearStoredTokens, getStoredTokens, setStoredTokens } from './auth/tokenStorage'
import type { TokenResponse } from './auth/types'

/** The one envelope every AppError subclass produces
 * (backend/app/core/error_handlers.py) -- `fields` carries per-field
 * validation errors (docs/modules/api_error_handling.md #7), `message`
 * is always safe, hand-written text a form/page can show directly. */
export interface ApiErrorShape {
  code: string
  message: string
  fields?: Record<string, string> | null
}

export class ApiError extends Error {
  code: string
  fields: Record<string, string> | null
  status: number | null

  constructor(shape: ApiErrorShape, status: number | null) {
    super(shape.message)
    this.name = 'ApiError'
    this.code = shape.code
    this.fields = shape.fields ?? null
    this.status = status
  }
}

const baseURL = import.meta.env.VITE_API_URL

export const apiClient = axios.create({ baseURL })

// Registered by AuthProvider on mount (frontend/src/lib/auth/AuthContext.tsx).
// apiClient stays framework-agnostic -- same convention as every other
// lib/ module mirroring a backend concern -- so a refresh failure
// notifies the app through this one callback instead of importing
// AuthContext directly and risking a circular import.
let onSessionExpired: (() => void) | null = null

export function setOnSessionExpired(handler: (() => void) | null): void {
  onSessionExpired = handler
}

apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const tokens = getStoredTokens()
  if (tokens) {
    config.headers.set('Authorization', `Bearer ${tokens.accessToken}`)
  }
  return config
})

// /login and /refresh are exempt from the 401-retry dance below: a bad
// password legitimately returns 401 (backend/app/services/auth_service.py's
// GENERIC_LOGIN_ERROR) and must reach the caller as-is, not be
// swallowed into a "session expired" refresh attempt with whatever
// stale tokens happen to be in storage. This exemption is also what
// makes it safe for refreshAccessToken below to issue its POST through
// apiClient itself, rather than a second bare instance -- a 401 on the
// refresh call is exempt from this same retry logic, so it can never
// recurse.
const REFRESH_EXEMPT_PATHS = ['/api/auth/login', '/api/auth/refresh']

let refreshPromise: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  const tokens = getStoredTokens()
  if (!tokens) throw new Error('No refresh token available.')

  // Concurrent 401s from several in-flight requests share one refresh
  // call rather than each firing their own -- refresh tokens rotate on
  // use (auth_service.refresh()), so a second concurrent call would
  // just fail against an already-spent token.
  refreshPromise ??= apiClient
    .post<TokenResponse>('/api/auth/refresh', { refresh_token: tokens.refreshToken })
    .then(({ data }) => {
      setStoredTokens({ accessToken: data.access_token, refreshToken: data.refresh_token })
      return data.access_token
    })
    .finally(() => {
      refreshPromise = null
    })

  return refreshPromise
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined
    const isRefreshExempt = REFRESH_EXEMPT_PATHS.some((path) => original?.url?.includes(path))

    if (error.response?.status === 401 && original && !original._retried && !isRefreshExempt) {
      original._retried = true
      try {
        const accessToken = await refreshAccessToken()
        original.headers.set('Authorization', `Bearer ${accessToken}`)
        return apiClient(original)
      } catch {
        clearStoredTokens()
        onSessionExpired?.()
        return Promise.reject(
          new ApiError({ code: 'AUTHENTICATION_ERROR', message: 'Your session has expired. Please sign in again.' }, 401),
        )
      }
    }

    const data = error.response?.data as { error?: ApiErrorShape } | undefined
    if (data?.error) {
      return Promise.reject(new ApiError(data.error, error.response?.status ?? null))
    }
    return Promise.reject(
      new ApiError({ code: 'NETWORK_ERROR', message: 'Could not reach the server. Please check your connection.' }, null),
    )
  },
)
