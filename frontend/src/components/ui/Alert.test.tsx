import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Alert } from './Alert'

describe('Alert', () => {
  it('renders nothing when children is falsy, so callers need no conditional', () => {
    const { container } = render(<Alert variant="danger">{null}</Alert>)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders the message when children is truthy', () => {
    render(<Alert variant="danger">Something went wrong</Alert>)
    expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong')
  })

  it('supports all four variants required by the spec, including warning', () => {
    const variants = ['success', 'warning', 'danger', 'info'] as const
    for (const variant of variants) {
      const { unmount } = render(<Alert variant={variant}>Message</Alert>)
      expect(screen.getByRole('alert')).toBeInTheDocument()
      unmount()
    }
  })
})
