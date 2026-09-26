import { forwardRef, useState } from 'react'
import { TextField } from './TextField'
import type { TextFieldProps } from './TextField'

/** A `TextField` that toggles between masked and plain text -- reusable
 * anywhere a password is entered (login today; change-password/invite
 * flows can adopt it too) rather than a one-off per page. */
export const PasswordField = forwardRef<HTMLInputElement, Omit<TextFieldProps, 'type' | 'trailingSlot'>>(
  function PasswordField(props, ref) {
    const [visible, setVisible] = useState(false)

    return (
      <TextField
        ref={ref}
        type={visible ? 'text' : 'password'}
        trailingSlot={
          <button
            type="button"
            onClick={() => setVisible((v) => !v)}
            className="text-xs font-medium text-gold-100/40 transition-colors hover:text-gold-300"
            aria-label={visible ? 'Hide password' : 'Show password'}
          >
            {visible ? 'Hide' : 'Show'}
          </button>
        }
        {...props}
      />
    )
  },
)

PasswordField.displayName = 'PasswordField'
