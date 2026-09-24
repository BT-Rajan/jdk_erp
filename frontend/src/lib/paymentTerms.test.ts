import { describe, expect, it } from 'vitest'
import { composePaymentTerms, parsePaymentTerms, paymentTermsError } from './paymentTerms'

describe('payment terms', () => {
  it('reads the fixed choices and Others with details', () => {
    expect(parsePaymentTerms('Prepaid')).toEqual({ choice: 'Prepaid', details: '' })
    expect(parsePaymentTerms('on delivery')).toEqual({ choice: 'On Delivery', details: '' })
    expect(parsePaymentTerms('Others: 50% advance')).toEqual({ choice: 'Others', details: '50% advance' })
    expect(parsePaymentTerms('30 days')).toEqual({ choice: 'Others', details: '30 days' })
    expect(parsePaymentTerms(null)).toEqual({ choice: '', details: '' })
  })

  it('stores Others with its details and requires them', () => {
    expect(composePaymentTerms({ choice: 'Others', details: ' 30 days ' })).toBe('Others: 30 days')
    expect(composePaymentTerms({ choice: 'Advance', details: 'ignored' })).toBe('Advance')
    expect(paymentTermsError({ choice: '', details: '' })).toBe('Payment terms are required.')
    expect(paymentTermsError({ choice: 'Others', details: ' ' })).toBe('Describe the payment terms for Others.')
    expect(paymentTermsError({ choice: 'On Delivery', details: '' })).toBeNull()
  })
})
