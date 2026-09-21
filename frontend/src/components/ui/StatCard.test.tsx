import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatCard } from './StatCard'

describe('StatCard', () => {
  it('renders label, value and hint', () => {
    render(<StatCard label="Open orders" value={42} hint="+5 this week" />)
    expect(screen.getByText('Open orders')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(screen.getByText('+5 this week')).toBeInTheDocument()
  })
})
