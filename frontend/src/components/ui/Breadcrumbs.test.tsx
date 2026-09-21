import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { Breadcrumbs } from './Breadcrumbs'

describe('Breadcrumbs', () => {
  it('renders earlier items as links and the last item as plain, current-page text', () => {
    render(
      <MemoryRouter>
        <Breadcrumbs
          items={[
            { label: 'Suppliers', to: '/suppliers' },
            { label: 'Acme Corp', to: '/suppliers/1' },
            { label: 'Edit' },
          ]}
        />
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: 'Suppliers' })).toHaveAttribute('href', '/suppliers')
    expect(screen.getByRole('link', { name: 'Acme Corp' })).toHaveAttribute('href', '/suppliers/1')

    const current = screen.getByText('Edit')
    expect(current.tagName).toBe('SPAN')
    expect(current).toHaveAttribute('aria-current', 'page')
  })

  it('has an accessible nav landmark labeled Breadcrumb', () => {
    render(
      <MemoryRouter>
        <Breadcrumbs items={[{ label: 'Home' }]} />
      </MemoryRouter>,
    )
    expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toBeInTheDocument()
  })
})
