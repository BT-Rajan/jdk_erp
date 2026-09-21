import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { KeyValue } from './KeyValue'

describe('KeyValue', () => {
  it('renders a label and value', () => {
    render(<KeyValue label="Email" value="ada@example.com" />)
    expect(screen.getByText('Email')).toBeInTheDocument()
    expect(screen.getByText('ada@example.com')).toBeInTheDocument()
  })

  it('falls back to an em-dash when there is no value', () => {
    render(<KeyValue label="Phone" />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('renders children over value when both are given', () => {
    render(
      <KeyValue label="Status" value="ignored">
        <strong>Active</strong>
      </KeyValue>,
    )
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.queryByText('ignored')).not.toBeInTheDocument()
  })
})
