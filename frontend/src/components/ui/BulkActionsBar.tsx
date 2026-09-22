import { Button, type ButtonVariant } from './Button'

export interface BulkAction {
  key: string
  label: string
  onSelect: () => void
  danger?: boolean
}

export interface BulkActionsBarProps {
  count: number
  onClear: () => void
  actions: BulkAction[]
}

/** Pairs with DataTable's `selectable` prop -- renders nothing when
 * nothing is selected, so callers don't need `{count > 0 && ...}` at
 * the call site (the same convention Alert already established). Only
 * worth composing when a workflow genuinely has bulk actions -- it's
 * not part of DataTable itself. */
export function BulkActionsBar({ count, onClear, actions }: BulkActionsBarProps) {
  if (count === 0) return null

  return (
    <div className="flex items-center justify-between rounded-md border border-gold-400/30 bg-ink-800 px-4 py-2">
      <span className="text-sm text-gold-100">{count} selected</span>
      <div className="flex items-center gap-2">
        {actions.map((action) => (
          <Button
            key={action.key}
            size="sm"
            variant={(action.danger ? 'danger' : 'secondary') satisfies ButtonVariant}
            onClick={action.onSelect}
          >
            {action.label}
          </Button>
        ))}
        <Button size="sm" variant="ghost" onClick={onClear}>
          Clear
        </Button>
      </div>
    </div>
  )
}
