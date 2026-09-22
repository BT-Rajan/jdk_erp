import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { DateRangeField, type DateRangeValue } from './DateRangeField'

function Fixture() {
  const [value, setValue] = useState<DateRangeValue>({ from: null, to: null })
  return <DateRangeField label="Order date" value={value} onChange={setValue} />
}

describe('DateRangeField', () => {
  it('renders two distinctly-labeled date inputs', () => {
    render(<Fixture />)
    expect(screen.getByLabelText('Order date from')).toHaveAttribute('type', 'date')
    expect(screen.getByLabelText('Order date to')).toHaveAttribute('type', 'date')
  })

  it('updates from and to independently', async () => {
    render(<Fixture />)
    await userEvent.type(screen.getByLabelText('Order date from'), '2026-01-01')
    await userEvent.type(screen.getByLabelText('Order date to'), '2026-01-31')

    expect(screen.getByLabelText('Order date from')).toHaveValue('2026-01-01')
    expect(screen.getByLabelText('Order date to')).toHaveValue('2026-01-31')
  })
})
