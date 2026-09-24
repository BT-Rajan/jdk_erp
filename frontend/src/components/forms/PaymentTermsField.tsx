import { PAYMENT_TERM_CHOICES, PAYMENT_TERM_HINTS, type PaymentTermChoice, type PaymentTerms } from '@/lib/paymentTerms'
import { SelectField } from './SelectField'
import { TextField } from './TextField'

export interface PaymentTermsFieldProps {
  value: PaymentTerms
  onChange: (value: PaymentTerms) => void
}

/** Advance / Prepaid / On Delivery / Others, with a details box for Others. */
export function PaymentTermsField({ value, onChange }: PaymentTermsFieldProps) {
  return (
    <>
      <SelectField
        label="Payment Terms"
        required
        hint={value.choice ? PAYMENT_TERM_HINTS[value.choice] : undefined}
        value={value.choice}
        onChange={(e) => onChange({ choice: e.target.value as PaymentTermChoice | '', details: value.details })}
      >
        <option value="">Select...</option>
        {PAYMENT_TERM_CHOICES.map((choice) => (
          <option key={choice} value={choice}>{choice}</option>
        ))}
      </SelectField>
      {value.choice === 'Others' && (
        <TextField
          label="Payment Terms Details"
          required
          placeholder="e.g. 50% advance, 50% on delivery"
          value={value.details}
          onChange={(e) => onChange({ choice: value.choice, details: e.target.value })}
        />
      )}
    </>
  )
}
