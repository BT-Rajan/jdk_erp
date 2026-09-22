import { useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { IconButton } from './IconButton'
import { Tooltip } from './Tooltip'

export interface CopyToClipboardProps {
  value: string
  label?: string
  className?: string
}

export function CopyToClipboard({ value, label = 'Copy', className }: CopyToClipboardProps) {
  const [copied, setCopied] = useState(false)

  async function handleClick() {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard access denied/unavailable -- a convenience action,
      // not a critical one, so this fails silently rather than showing
      // an error state for a copy button.
    }
  }

  return (
    <Tooltip label={copied ? 'Copied!' : label}>
      <IconButton
        icon={copied ? <Check size={14} /> : <Copy size={14} />}
        aria-label={copied ? 'Copied' : label}
        size="sm"
        onClick={handleClick}
        className={className}
      />
    </Tooltip>
  )
}
