/** The one place tokens are read from / written to storage -- every
 * other module goes through this, never `localStorage` directly, so
 * there's a single implementation to change if the storage mechanism
 * ever does (docs/ENGINEERING_PRINCIPLES.md #2, "one source of truth").
 *
 * localStorage, not an httpOnly cookie: this API is a pure Bearer-token
 * JSON API (backend/app/api/deps.py reads only the Authorization
 * header, never a cookie), so there's no session cookie for the
 * backend to set as httpOnly in the first place. The tradeoff is real
 * -- a token in localStorage is readable by any script that runs on
 * this origin, so it's only as safe as this app's own XSS surface is
 * small. Revisit this file first if that changes (e.g. moving refresh
 * to a backend-set httpOnly cookie).
 */

const ACCESS_TOKEN_KEY = 'jdk_erp.access_token'
const REFRESH_TOKEN_KEY = 'jdk_erp.refresh_token'

export interface StoredTokens {
  accessToken: string
  refreshToken: string
}

export function getStoredTokens(): StoredTokens | null {
  const accessToken = localStorage.getItem(ACCESS_TOKEN_KEY)
  const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY)
  if (!accessToken || !refreshToken) return null
  return { accessToken, refreshToken }
}

export function setStoredTokens(tokens: StoredTokens): void {
  localStorage.setItem(ACCESS_TOKEN_KEY, tokens.accessToken)
  localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refreshToken)
}

export function clearStoredTokens(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY)
  localStorage.removeItem(REFRESH_TOKEN_KEY)
}
