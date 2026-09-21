import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PageHeader } from './PageHeader'

describe('PageHeader', () => {
  it('renders title, subtitle and actions', () => {
    render(<PageHeader title="Suppliers" subtitle="Manage your suppliers" actions={<button type="button">New</button>} />)
    expect(screen.getByRole('heading', { name: 'Suppliers' })).toBeInTheDocument()
    expect(screen.getByText('Manage your suppliers')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New' })).toBeInTheDocument()
  })

  it('renders with only a title', () => {
    render(<PageHeader title="Suppliers" />)
    expect(screen.getByRole('heading', { name: 'Suppliers' })).toBeInTheDocument()
  })
})
