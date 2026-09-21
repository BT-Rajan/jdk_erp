import type { ReactNode } from 'react'

export interface FieldShellProps {
  label: string
  fieldId: string
  hintId: string
  errorId: string
  hint?: string
  error?: string
  children: ReactNode
}

/** The label/error/hint contract every form field shares -- one
 * implementation instead of each field re-declaring the same
 * label+message markup (jdk_clean's fields all followed this same
 * convention, but each one carried its own copy of the JSX). */
export function FieldShell({ label, fieldId, hintId, errorId, hint, error, children }: FieldShellProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={fieldId} className="text-sm font-medium text-gold-100">
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
