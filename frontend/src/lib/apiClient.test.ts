import type { AxiosAdapter, AxiosResponse } from 'axios'
import { AxiosHeaders } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient, ApiError, setOnSessionExpired } from './apiClient'
import { getStoredTokens, setStoredTokens } from './auth/tokenStorage'

/** Routes requests to hand-written canned responses instead of a real
 * network call -- axios's own `adapter` config is the transport layer,
 * so swapping it here exercises the real interceptor chain end to end
 * with no new test dependency (docs/ENGINEERING_PRINCIPLES.md #2). */
function fakeAdapter(
  handler: (url: string, body: unknown) => { status: number; data: unknown },
): AxiosAdapter {
  return async (config) => {
    const { status, data } = handler(config.url ?? '', config.data ? JSON.parse(config.data as string) : undefined)
    const response: AxiosResponse = {
      data,
      status,
      statusText: String(status),
      headers: {},
      config,
    }
    if (status >= 200 && status < 300) return response
    const error = Object.assign(new Error(String(status)), {
      isAxiosError: true,
      response,
      config,
      toJSON: () => ({}),
    })
    throw error
  }
}

beforeEach(() => {
  localStorage.clear()
  setOnSessionExpired(null)
  apiClient.defaults.headers.common = new AxiosHeaders()
})

describe('apiClient request interceptor', () => {
  it('attaches no Authorization header when no tokens are stored', async () => {
    let seenAuth: unknown
    apiClient.defaults.adapter = async (config) => {
      seenAuth = config.headers.get('Authorization')
      return { data: { ok: true }, status: 200, statusText: '200', headers: {}, config }
    }
    await apiClient.get('/api/ping')
    expect(seenAuth).toBeUndefined()
  })

  it('attaches Bearer <access token> when tokens are stored', async () => {
    setStoredTokens({ accessToken: 'access-1', refreshToken: 'refresh-1' })
    let seenAuth: unknown
    apiClient.defaults.adapter = async (config) => {
      seenAuth = config.headers.get('Authorization')
      return { data: { ok: true }, status: 200, statusText: '200', headers: {}, config }
    }
    await apiClient.get('/api/ping')
    expect(seenAuth).toBe('Bearer access-1')
  })
})

describe('apiClient response interceptor', () => {
  it('refreshes once on a 401, retries the original request, and stores the new tokens', async () => {
    setStoredTokens({ accessToken: 'expired', refreshToken: 'refresh-1' })
    let pingCalls = 0

    apiClient.defaults.adapter = fakeAdapter((url) => {
      if (url.includes('/api/auth/refresh')) {
        return { status: 200, data: { access_token: 'fresh', refresh_token: 'refresh-2', token_type: 'bearer' } }
      }
      if (url.includes('/api/ping')) {
        pingCalls += 1
        if (pingCalls === 1) {
          return { status: 401, data: { error: { code: 'AUTHENTICATION_ERROR', message: 'expired' } } }
        }
        return { status: 200, data: { ok: true } }
      }
      return { status: 404, data: {} }
    })

    const { data } = await apiClient.get('/api/ping')

    expect(data).toEqual({ ok: true })
    expect(pingCalls).toBe(2)
    expect(getStoredTokens()).toEqual({ accessToken: 'fresh', refreshToken: 'refresh-2' })
  })

  it('shares one refresh call across concurrent 401s', async () => {
    setStoredTokens({ accessToken: 'expired', refreshToken: 'refresh-1' })
    let refreshCalls = 0
    let pingAttempts = 0

    apiClient.defaults.adapter = fakeAdapter((url) => {
      if (url.includes('/api/auth/refresh')) {
        refreshCalls += 1
        return { status: 200, data: { access_token: 'fresh', refresh_token: 'refresh-2', token_type: 'bearer' } }
      }
      pingAttempts += 1
      // Each request's first attempt (odd count) is unauthenticated;
      // its retry (even count) succeeds -- two concurrent requests
      // means four attempts total, but only one refresh.
      if (pingAttempts <= 2) return { status: 401, data: { error: { code: 'AUTHENTICATION_ERROR', message: 'expired' } } }
      return { status: 200, data: { ok: true } }
    })

    await Promise.all([apiClient.get('/api/one'), apiClient.get('/api/two')])

    expect(refreshCalls).toBe(1)
  })

  it('clears tokens and notifies onSessionExpired when the refresh call itself fails', async () => {
    setStoredTokens({ accessToken: 'expired', refreshToken: 'stale' })
    const sessionExpired = vi.fn()
    setOnSessionExpired(sessionExpired)

    apiClient.defaults.adapter = fakeAdapter((url) => {
      if (url.includes('/api/auth/refresh')) {
        return { status: 401, data: { error: { code: 'AUTHENTICATION_ERROR', message: 'Refresh token is invalid.' } } }
      }
      return { status: 401, data: { error: { code: 'AUTHENTICATION_ERROR', message: 'expired' } } }
    })

    await expect(apiClient.get('/api/ping')).rejects.toMatchObject({
      message: 'Your session has expired. Please sign in again.',
    })
    expect(getStoredTokens()).toBeNull()
    expect(sessionExpired).toHaveBeenCalledOnce()
  })

  it('does not attempt a refresh for a 401 from /api/auth/login -- the real error reaches the caller', async () => {
    apiClient.defaults.adapter = fakeAdapter((url) => {
      if (url.includes('/api/auth/login')) {
        return { status: 401, data: { error: { code: 'AUTHENTICATION_ERROR', message: 'Invalid username or password.' } } }
      }
      return { status: 404, data: {} }
    })

    await expect(apiClient.post('/api/auth/login', { username: 'a', password: 'b' })).rejects.toMatchObject({
      message: 'Invalid username or password.',
    })
  })

  it('wraps a response with no error envelope as a generic network error', async () => {
    apiClient.defaults.adapter = fakeAdapter(() => ({ status: 500, data: 'unexpected' }))

    const rejection = apiClient.get('/api/ping').catch((error: unknown) => error)
    await expect(rejection).resolves.toBeInstanceOf(ApiError)
    await expect(rejection).resolves.toMatchObject({ code: 'NETWORK_ERROR' })
  })
})
