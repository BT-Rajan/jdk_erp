import { useId, type FormEvent, type ReactNode } from 'react'
import { FormActions } from '@/components/forms/FormActions'
import { Modal, type ModalSize } from './Modal'

export interface FormDialogProps {
  open: boolean
  title: string
  onClose: () => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  submitting?: boolean
  submitLabel?: string
  cancelLabel?: string
  size?: ModalSize
  children: ReactNode
}

/** For small, self-contained forms -- one of the four fixed dialog
 * patterns (docs/modules/tables_forms_modals_filters.md). A large or
 * multi-step workflow belongs on its own page, not in here. The form
 * and its Save button live in different parts of Modal's layout (the
 * body vs. the footer), associated via the native HTML `form`
 * attribute rather than nesting one inside the other. */
export function FormDialog({
  open,
  title,
  onClose,
  onSubmit,
  submitting = false,
  submitLabel = 'Save',
  cancelLabel = 'Cancel',
  size = 'default',
  children,
}: FormDialogProps) {
  const formId = useId()

  return (
    <Modal
      open={open}
      title={title}
      onClose={onClose}
      size={size}
      footer={
        <FormActions
          formId={formId}
          onCancel={onClose}
          submitting={submitting}
          submitLabel={submitLabel}
          cancelLabel={cancelLabel}
        />
      }
    >
      {/* Two columns on sm+ so a modal with several fields uses the
       * uniform modal width well instead of stacking everything into one
       * narrow strip; individual fields opt into spanning both columns
       * via their `fullWidth` prop (see FieldShell) when a field -- a
       * textarea, a file upload, an alert banner -- genuinely needs the
       * full row. */}
      <form id={formId} onSubmit={onSubmit} className="grid grid-cols-1 gap-x-4 gap-y-4 sm:grid-cols-2">
        {children}
      </form>
    </Modal>
  )
}
