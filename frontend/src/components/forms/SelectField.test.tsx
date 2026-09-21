import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { SelectField } from './SelectField'

describe('SelectField', () => {
  it('renders options passed as children and supports selection', async () => {
    render(
      <SelectField label="Status">
        <option value="active">Active</option>
        <option value="inactive">Inactive</option>
      </SelectField>,
    )
    const select = screen.getByLabelText('Status')
    await userEvent.selectOptions(select, 'inactive')
    expect(select).toHaveValue('inactive')
  })
})
