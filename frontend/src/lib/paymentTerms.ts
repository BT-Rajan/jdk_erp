/** PO payment terms -- mirrors backend/app/core/payment_terms.py. Stored
 * as "Advance", "Prepaid", "On Delivery" or "Others: <details>". */
export const PAYMENT_TERM_CHOICES = ['Advance', 'Prepaid', 'On Delivery', 'Others'] as const
export type PaymentTermChoice = (typeof PAYMENT_TERM_CHOICES)[number]

export interface PaymentTerms {
  choice: PaymentTermChoice | ''
  details: string
}

/** Anything that isn't one of the fixed choices (older free-text terms,
 * a supplier quote's wording) reads as Others with that text. */
export function parsePaymentTerms(value: string | null | undefined): PaymentTerms {
  const text = (value ?? '').trim()
  if (!text) return { choice: '', details: '' }
  const fixed = PAYMENT_TERM_CHOICES.find((c) => c !== 'Others' && c.toLowerCase() === text.toLowerCase())
  if (fixed) return { choice: fixed, details: '' }
  if (text.toLowerCase().startsWith('others')) return { choice: 'Others', details: text.slice(6).replace(/^[\s:-]+/, '') }
  return { choice: 'Others', details: text }
}

export function composePaymentTerms({ choice, details }: PaymentTerms): string {
  return choice === 'Others' ? `Others: ${details.trim()}` : choice
}

export function paymentTermsError({ choice, details }: PaymentTerms): string | null {
  if (!choice) return 'Payment terms are required.'
  if (choice === 'Others' && !details.trim()) return 'Describe the payment terms for Others.'
  return null
}

export const PAYMENT_TERM_HINTS: Record<PaymentTermChoice, string> = {
  Advance: 'Paid before delivery.',
  Prepaid: 'Already paid -- this PO is for record only. Finance records the payment made.',
  'On Delivery': 'Paid when the goods arrive.',
  Others: 'Describe the terms.',
}
