import { useRef, type DragEvent } from 'react'
import { Upload, X } from 'lucide-react'
import { useFieldIds } from '@/lib/useFieldIds'
import { cn } from '@/lib/cn'
import { IconButton } from '@/components/ui/IconButton'
import { FieldShell } from './FieldShell'
import { describedBy } from './describedBy'

export interface FileUploadFieldProps {
  label: string
  error?: string
  hint?: string
  accept?: string
  multiple?: boolean
  value: File[]
  onChange: (files: File[]) => void
  id?: string
  disabled?: boolean
  /** Defaults to spanning both grid columns -- the drag-and-drop target
   * and selected-file list need more than half a modal's width. */
  fullWidth?: boolean
}

/** One shared drag-and-drop/click-to-browse file picker with a
 * selected-file list, replacing jdk_clean's ~9 pages that each
 * hand-rolled their own file input UI. */
export function FileUploadField({
  label,
  error,
  hint,
  accept,
  multiple = false,
  value,
  onChange,
  id,
  disabled,
  fullWidth = true,
}: FileUploadFieldProps) {
  const { fieldId, hintId, errorId } = useFieldIds(id)
  const inputRef = useRef<HTMLInputElement>(null)

  function addFiles(fileList: FileList | null) {
    if (!fileList) return
    const incoming = Array.from(fileList)
    onChange(multiple ? [...value, ...incoming] : incoming.slice(0, 1))
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    if (disabled) return
    addFiles(event.dataTransfer.files)
  }

  function removeFile(index: number) {
    onChange(value.filter((_, i) => i !== index))
  }

  return (
    <FieldShell label={label} fieldId={fieldId} hintId={hintId} errorId={errorId} hint={hint} error={error} fullWidth={fullWidth}>
      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-disabled={disabled || undefined}
        aria-describedby={describedBy(hint, error, hintId, errorId)}
        onClick={() => !disabled && inputRef.current?.click()}
        onKeyDown={(event) => {
          if (!disabled && (event.key === 'Enter' || event.key === ' ')) {
            event.preventDefault()
            inputRef.current?.click()
          }
        }}
        onDragOver={(event) => event.preventDefault()}
        onDrop={handleDrop}
        className={cn(
          'flex cursor-pointer flex-col items-center gap-2 rounded-md border border-dashed px-4 py-6 text-center transition-colors',
          error ? 'border-danger-500' : 'border-ink-600 hover:border-gold-400',
          disabled && 'cursor-not-allowed opacity-50',
        )}
      >
        <Upload size={20} aria-hidden="true" className="text-gold-100/50" />
        <p className="text-sm text-gold-100/70">
          Drag a file here, or <span className="text-gold-300">browse</span>
        </p>
        <input
          ref={inputRef}
          id={fieldId}
          type="file"
          accept={accept}
          multiple={multiple}
          disabled={disabled}
          className="hidden"
          onChange={(event) => addFiles(event.target.files)}
        />
      </div>
      {value.length > 0 && (
        <ul className="mt-2 flex flex-col gap-1">
          {value.map((file, index) => (
            <li key={`${file.name}-${index}`} className="flex items-center justify-between rounded-md bg-ink-800 px-3 py-1.5 text-sm text-gold-100">
              <span className="truncate">{file.name}</span>
              <IconButton
                icon={<X size={14} />}
                aria-label={`Remove ${file.name}`}
                size="sm"
                onClick={() => removeFile(index)}
              />
            </li>
          ))}
        </ul>
      )}
    </FieldShell>
  )
}
