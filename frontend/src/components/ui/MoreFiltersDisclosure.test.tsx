import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { MoreFiltersDisclosure } from './MoreFiltersDisclosure'

describe('MoreFiltersDisclosure', () => {
  it('is collapsed by default', () => {
    render(
      <MoreFiltersDisclosure>
        <p>Advanced filter</p>
      </MoreFiltersDisclosure>,
    )
    expect(screen.queryByText('Advanced filter')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'More filters' })).toHaveAttribute('aria-expanded', 'false')
  })

  it('expands to reveal its content on click', async () => {
    render(
      <MoreFiltersDisclosure>
        <p>Advanced filter</p>
      </MoreFiltersDisclosure>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'More filters' }))
    expect(screen.getByText('Advanced filter')).toBeInTheDocument()
  })

  it('supports a custom label', () => {
    render(
      <MoreFiltersDisclosure label="Advanced">
        <p>Content</p>
      </MoreFiltersDisclosure>,
    )
    expect(screen.getByRole('button', { name: 'Advanced' })).toBeInTheDocument()
  })
})
