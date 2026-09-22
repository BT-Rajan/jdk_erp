import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export interface FieldShellProps {
  label: string
  fieldId: string
  hintId: string
  errorId: string
  hint?: string
  error?: string
  /** Shows a required-field indicator next to the label ONLY -- fields
   * deliberately do not also set the native HTML `required` attribute
   * from this prop. The browser's own constraint validation fires on
   * submit and silently blocks it before react-hook-form's handleSubmit
   * (and therefore the zod resolver) ever runs, which would mean a
   * required field either shows a native, unstyled browser popup, or
   * -- worse -- appears to do nothing at all while the JDK-styled error
   * message a module wrote in its zod schema never shows. Per this
   * module's own rule ("UI validation for immediate feedback; server
   * (schema) validation is authoritative"), zod + this field's `error`
   * prop is that one validation path -- native HTML5 validation is a
   * second, uncoordinated one this deliberately avoids triggering. */
  required?: boolean
  children: ReactNode
}

/** The label/error/hint contract every form field shares -- one
 * implementation instead of each field re-declaring the same
 * label+message markup (jdk_clean's fields all followed this same
 * convention, but each one carried its own copy of the JSX). */
export function FieldShell({ label, fieldId, hintId, errorId, hint, error, required, children }: FieldShellProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <label
        htmlFor={fieldId}
        className={cn(
          'text-sm font-medium text-gold-100',
          // A CSS pseudo-element, not a DOM node: the accessible name
          // (and getByLabelText's plain text match) for the label stays
          // exactly the label text, so a screen reader doesn't announce
          // "asterisk" on every required field, and "Name" still finds
          // the field named "Name" -- only the visual indicator differs.
          required && "after:ml-0.5 after:text-danger-500 after:content-['*']",
        )}
      >
        {label}
      </label>
      {children}
      {error ? (
        <p id={errorId} role="alert" className="text-xs text-danger-500">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="text-xs text-gold-100/50">
          {hint}
        </p>
      ) : null}
    </div>
  )
}
