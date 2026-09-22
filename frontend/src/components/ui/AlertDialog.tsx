import { Button } from './Button'
import { Modal } from './Modal'
import { Alert, type AlertVariant } from './Alert'

export interface AlertDialogProps {
  open: boolean
  title: string
  message: string
  onClose: () => void
  closeLabel?: string
  variant?: AlertVariant
}

/** For important information, warnings and errors that need
 * acknowledgement, not a decision -- ConfirmDialog's two buttons
 * (Cancel + Confirm) are the wrong shape when there's nothing to
 * decide. Composes the existing Alert for the message tone instead of
 * a new colour/icon scheme. */
export function AlertDialog({ open, title, message, onClose, closeLabel = 'OK', variant = 'info' }: AlertDialogProps) {
  return (
    <Modal open={open} title={title} onClose={onClose} footer={<Button onClick={onClose}>{closeLabel}</Button>}>
      <Alert variant={variant}>{message}</Alert>
    </Modal>
  )
}
