import { beforeEach, describe, expect, it } from 'vitest'
import { clearStoredTokens, getStoredTokens, setStoredTokens } from './tokenStorage'

describe('tokenStorage', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('returns null when nothing is stored', () => {
    expect(getStoredTokens()).toBeNull()
  })

  it('round-trips whatever was stored', () => {
    setStoredTokens({ accessToken: 'access-1', refreshToken: 'refresh-1' })
    expect(getStoredTokens()).toEqual({ accessToken: 'access-1', refreshToken: 'refresh-1' })
  })

  it('overwrites a previous pair rather than merging', () => {
    setStoredTokens({ accessToken: 'access-1', refreshToken: 'refresh-1' })
    setStoredTokens({ accessToken: 'access-2', refreshToken: 'refresh-2' })
    expect(getStoredTokens()).toEqual({ accessToken: 'access-2', refreshToken: 'refresh-2' })
  })

  it('treats a partial pair (one key missing) as no tokens at all', () => {
    localStorage.setItem('jdk_erp.access_token', 'access-1')
    expect(getStoredTokens()).toBeNull()
  })

  it('clears both keys', () => {
    setStoredTokens({ accessToken: 'access-1', refreshToken: 'refresh-1' })
    clearStoredTokens()
    expect(getStoredTokens()).toBeNull()
  })
})
