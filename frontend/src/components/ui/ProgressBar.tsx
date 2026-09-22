export interface ProgressBarProps {
  /** 0-100; clamped into range. */
  value: number
  label?: string
  className?: string
}

export function ProgressBar({ value, label, className }: ProgressBarProps) {
  const clamped = Math.min(100, Math.max(0, value))

  return (
    <div className={className}>
      {label && <p className="mb-1 text-xs text-gold-100/60">{label}</p>}
      <div
        role="progressbar"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-2 w-full overflow-hidden rounded-full bg-ink-700"
      >
        <div className="h-full rounded-full bg-gold-400 transition-[width]" style={{ width: `${clamped}%` }} />
      </div>
    </div>
  )
}
