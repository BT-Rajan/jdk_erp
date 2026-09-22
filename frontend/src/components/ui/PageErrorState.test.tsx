import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { PageErrorState } from './PageErrorState'

describe('PageErrorState', () => {
  it('renders the default message matching the backend generic error text', () => {
    render(<PageErrorState />)
    expect(screen.getByText('Something went wrong. Please try again.')).toBeInTheDocument()
  })

  it('does not render a retry button when onRetry is not given', () => {
    render(<PageErrorState />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('renders and calls onRetry when given', async () => {
    const onRetry = vi.fn()
    render(<PageErrorState onRetry={onRetry} />)
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })
})
