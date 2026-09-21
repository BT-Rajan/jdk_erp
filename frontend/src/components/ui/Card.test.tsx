import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Card } from './Card'

describe('Card', () => {
  it('spreads native div props and renders children', () => {
    render(
      <Card data-testid="card">
        <p>Content</p>
      </Card>,
    )
    expect(screen.getByTestId('card')).toBeInTheDocument()
    expect(screen.getByText('Content')).toBeInTheDocument()
  })
})
