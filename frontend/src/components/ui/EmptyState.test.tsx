import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { EmptyState } from './EmptyState'

describe('EmptyState', () => {
  it('renders title, optional message and optional action', () => {
    render(<EmptyState title="No suppliers yet" message="Add your first one to get started." action={<button type="button">Add supplier</button>} />)
    expect(screen.getByText('No suppliers yet')).toBeInTheDocument()
    expect(screen.getByText('Add your first one to get started.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add supplier' })).toBeInTheDocument()
  })

  it('renders with only a title', () => {
    render(<EmptyState title="No results" />)
    expect(screen.getByText('No results')).toBeInTheDocument()
  })
})
