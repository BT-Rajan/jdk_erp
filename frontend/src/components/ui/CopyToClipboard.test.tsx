import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CopyToClipboard } from './CopyToClipboard'

describe('CopyToClipboard', () => {
  const writeText = vi.fn().mockResolvedValue(undefined)

  beforeEach(() => {
    Object.assign(navigator, { clipboard: { writeText } })
    writeText.mockClear()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('copies the given value to the clipboard on click', async () => {
    render(<CopyToClipboard value="INV-2026-001" />)
    await userEvent.click(screen.getByRole('button', { name: 'Copy' }))
    expect(writeText).toHaveBeenCalledWith('INV-2026-001')
  })

  it('shows a "Copied" accessible label briefly after copying', async () => {
    render(<CopyToClipboard value="INV-2026-001" />)
    await userEvent.click(screen.getByRole('button', { name: 'Copy' }))
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()
  })

  it('does not throw when the clipboard API rejects', async () => {
    writeText.mockRejectedValueOnce(new Error('denied'))
    render(<CopyToClipboard value="INV-2026-001" />)
    await userEvent.click(screen.getByRole('button', { name: 'Copy' }))
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument()
  })
})
