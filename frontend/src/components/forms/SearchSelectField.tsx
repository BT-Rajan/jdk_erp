import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useFieldIds } from '@/lib/useFieldIds'
import { useDismissableOverlay } from '@/lib/useDismissableOverlay'
import { cn } from '@/lib/cn'
import { FieldShell } from './FieldShell'
import { describedBy } from './describedBy'
import { inputClasses } from './inputClasses'

export interface SearchSelectOption {
  value: string
  label: string
}

export interface SearchSelectFieldProps {
  label: string
  error?: string
  hint?: string
  options: SearchSelectOption[]
  value: string | null
  onChange: (value: string | null) => void
  placeholder?: string
  id?: string
  disabled?: boolean
  required?: boolean
  fullWidth?: boolean
  /** Only list options once this many characters are typed -- for long
   * lists where scrolling everything is useless (e.g. 2 for suppliers). */
  minQueryLength?: number
}

/** "Pick one record via search" -- jdk_clean had no form-field-level
 * autocomplete/combobox at all (its closest analogs, the command palette
 * and the assistant drawer's search, are full-app search UIs, not a
 * field). A real ARIA combobox: typing filters the option list, arrow
 * keys move a visual+aria-activedescendant highlight, Enter selects,
 * Escape closes without changing the value. */
export function SearchSelectField({
  label,
  error,
  hint,
  options,
  value,
  onChange,
  placeholder,
  id,
  disabled,
  required,
  fullWidth,
  minQueryLength = 0,
}: SearchSelectFieldProps) {
  const { fieldId, hintId, errorId } = useFieldIds(id)
  const selected = options.find((option) => option.value === value) ?? null

  const [query, setQuery] = useState(selected?.label ?? '')
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)
  const containerRef = useRef<HTMLDivElement>(null)
  const listboxId = `${fieldId}-listbox`

  useEffect(() => {
    if (!open) setQuery(selected?.label ?? '')
  }, [selected, open])

  useDismissableOverlay(containerRef, {
    open,
    onDismiss: () => {
      setOpen(false)
      setQuery(selected?.label ?? '')
    },
  })

  const tooShort = query.trim().length < minQueryLength && query !== selected?.label
  const filtered = tooShort
    ? []
    : query.trim() === '' || query === selected?.label
      ? options
      : options.filter((option) => option.label.toLowerCase().includes(query.toLowerCase()))

  function selectOption(option: SearchSelectOption | null) {
    onChange(option?.value ?? null)
    setQuery(option?.label ?? '')
    setOpen(false)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      if (!open) {
        setOpen(true)
        return
      }
      setActiveIndex((index) => Math.min(index + 1, filtered.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActiveIndex((index) => Math.max(index - 1, 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      if (open && filtered[activeIndex]) selectOption(filtered[activeIndex])
    } else if (event.key === 'Escape') {
      setOpen(false)
      setQuery(selected?.label ?? '')
    }
  }

  return (
    <FieldShell label={label} fieldId={fieldId} hintId={hintId} errorId={errorId} hint={hint} error={error} required={required} fullWidth={fullWidth}>
      <div ref={containerRef} className="relative">
        <input
          id={fieldId}
          role="combobox"
          aria-expanded={open}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={open && filtered[activeIndex] ? `${listboxId}-${filtered[activeIndex].value}` : undefined}
          aria-invalid={!!error || undefined}
          aria-describedby={describedBy(hint, error, hintId, errorId)}
          disabled={disabled}
          placeholder={placeholder}
          autoComplete="off"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
            setOpen(true)
            setActiveIndex(0)
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => {
            setOpen(false)
            setQuery(selected?.label ?? '')
          }}
          onKeyDown={handleKeyDown}
          className={inputClasses(!!error)}
        />
        {open && (
          <ul id={listboxId} role="listbox" className="absolute z-10 mt-1 max-h-56 w-full overflow-y-auto rounded-md border border-ink-600 bg-ink-800 py-1 shadow-lg">
            {filtered.length === 0 ? (
              <li className="px-3 py-2 text-sm text-gold-100/40">
                {tooShort ? `Type at least ${minQueryLength} letters` : 'No matches'}
              </li>
            ) : (
              filtered.map((option, index) => (
                <li
                  key={option.value}
                  id={`${listboxId}-${option.value}`}
                  role="option"
                  aria-selected={option.value === value}
                  onMouseDown={(event) => {
                    event.preventDefault()
                    selectOption(option)
                  }}
                  className={cn(
                    'cursor-pointer px-3 py-2 text-sm text-gold-100',
                    index === activeIndex ? 'bg-ink-700' : 'hover:bg-ink-700',
                  )}
                >
                  {option.label}
                </li>
              ))
            )}
          </ul>
        )}
      </div>
    </FieldShell>
  )
}
