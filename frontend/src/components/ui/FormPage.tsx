import { useId, type FormEvent, type ReactNode } from 'react'
import { FormActions } from '@/components/forms/FormActions'
import { Alert } from './Alert'
import { Button } from './Button'
import { PageHeader } from './PageHeader'
import { Spinner } from './Spinner'

export interface FormPageProps {
  open: boolean
  title: string
  onClose: () => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  submitting?: boolean
  submitLabel?: string
  cancelLabel?: string
  /** Set while an edit route loads its record. */
  loading?: boolean
  /** The record for an edit route couldn't be loaded. */
  loadError?: string | null
  children: ReactNode
}

/** A master-data record's create/edit form as a page rather than a
 * dialog. Same props as FormDialog, so a page swaps one for the other;
 * the list page hides its table while this is open (see useFormRoute). */
export function FormPage({
  open,
  title,
  onClose,
  onSubmit,
  submitting = false,
  submitLabel = 'Save',
  cancelLabel = 'Cancel',
  loading = false,
  loadError = null,
  children,
}: FormPageProps) {
  const formId = useId()
  if (!open) return null

  return (
    <div className="space-y-6">
      <PageHeader title={title} />
      {loadError ? (
        <>
          <Alert variant="danger">{loadError}</Alert>
          <div>
            <Button variant="secondary" onClick={onClose}>Back to the list</Button>
          </div>
        </>
      ) : loading ? (
        <Spinner />
      ) : (
        <>
          <form id={formId} onSubmit={onSubmit} className="grid grid-cols-1 gap-x-4 gap-y-4 sm:grid-cols-2">
            {children}
          </form>
          <div className="border-t border-ink-700 pt-4">
            <FormActions formId={formId} onCancel={onClose} submitting={submitting} submitLabel={submitLabel} cancelLabel={cancelLabel} />
          </div>
        </>
      )}
    </div>
  )
}
