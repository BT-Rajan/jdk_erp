import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AccessDeniedState } from './AccessDeniedState'

describe('AccessDeniedState', () => {
  it('renders a default message', () => {
    render(<AccessDeniedState />)
    expect(screen.getByText('Access denied')).toBeInTheDocument()
    expect(screen.getByText("You don't have permission to view this.")).toBeInTheDocument()
  })

  it('renders a custom message', () => {
    render(<AccessDeniedState message="Only admins can view audit events." />)
    expect(screen.getByText('Only admins can view audit events.')).toBeInTheDocument()
  })
})
