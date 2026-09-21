import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DateField } from './DateField'

describe('DateField', () => {
  it('renders a date input by default', () => {
    render(<DateField label="Due date" />)
    expect(screen.getByLabelText('Due date')).toHaveAttribute('type', 'date')
  })

  it('renders a datetime-local input when withTime is set', () => {
    render(<DateField label="Delivery time" withTime />)
    expect(screen.getByLabelText('Delivery time')).toHaveAttribute('type', 'datetime-local')
  })
})
