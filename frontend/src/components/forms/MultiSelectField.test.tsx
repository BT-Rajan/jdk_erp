import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { MultiSelectField } from './MultiSelectField'

describe('MultiSelectField', () => {
  it('allows selecting multiple options', async () => {
    render(
      <MultiSelectField label="Teams">
        <option value="sales">Sales</option>
        <option value="ops">Operations</option>
        <option value="finance">Finance</option>
      </MultiSelectField>,
    )
    const select = screen.getByLabelText('Teams')
    await userEvent.selectOptions(select, ['sales', 'finance'])
    expect(select).toHaveValue(['sales', 'finance'])
  })
})
