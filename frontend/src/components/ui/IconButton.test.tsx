import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { IconButton } from './IconButton'

describe('IconButton', () => {
  it('uses aria-label as its accessible name since it has no visible text', () => {
    render(<IconButton icon={<span>x</span>} aria-label="Delete row" />)
    expect(screen.getByRole('button', { name: 'Delete row' })).toBeInTheDocument()
  })
})
