import { Button, type ButtonVariant } from '@/components/ui/Button'

export interface FormActionsProps {
  onCancel: () => void
  submitting?: boolean
  cancelLabel?: string
  submitLabel?: string
  submitVariant?: ButtonVariant
  /** Associates Save with a `<form>` elsewhere in the DOM via the
   * native HTML `form` attribute -- for FormDialog, where Save sits in
   * Modal's footer, a sibling of the `<form>` in the body, not a
   * descendant of it. */
  formId?: string
}

/** The one Save/Cancel row every form ends with -- Cancel disables
 * while submitting (so a mid-submit click can't cancel it) and Save
 * shows its loading state. Assumes it renders inside a `<form
 * onSubmit={handleSubmit(...)}>` -- Save is `type="submit"`, not a
 * click handler of its own -- unless `formId` is given. */
export function FormActions({
  onCancel,
  submitting = false,
  cancelLabel = 'Cancel',
  submitLabel = 'Save',
  submitVariant = 'primary',
  formId,
}: FormActionsProps) {
  return (
    <div className="flex justify-end gap-2">
      <Button type="button" variant="secondary" onClick={onCancel} disabled={submitting}>
        {cancelLabel}
      </Button>
      <Button type="submit" form={formId} variant={submitVariant} isLoading={submitting}>
        {submitLabel}
      </Button>
    </div>
  )
}
