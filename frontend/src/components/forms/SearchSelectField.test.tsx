import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { SearchSelectField, type SearchSelectOption } from './SearchSelectField'

const options: SearchSelectOption[] = [
  { value: 'acme', label: 'Acme Corp' },
  { value: 'globex', label: 'Globex Inc' },
  { value: 'initech', label: 'Initech' },
]

function Fixture() {
  const [value, setValue] = useState<string | null>(null)
  return <SearchSelectField label="Customer" options={options} value={value} onChange={setValue} />
}

describe('SearchSelectField', () => {
  it('is a combobox that is closed until focused/typed into', () => {
    render(<Fixture />)
    const input = screen.getByRole('combobox', { name: 'Customer' })
    expect(input).toHaveAttribute('aria-expanded', 'false')
  })

  it('filters options as the user types', async () => {
    render(<Fixture />)
    const input = screen.getByRole('combobox', { name: 'Customer' })
    await userEvent.type(input, 'glob')

    expect(screen.getByRole('option', { name: 'Globex Inc' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Acme Corp' })).not.toBeInTheDocument()
  })

  it('selects an option on click and closes the list', async () => {
    render(<Fixture />)
    const input = screen.getByRole('combobox', { name: 'Customer' })
    await userEvent.type(input, 'ini')
    await userEvent.click(screen.getByRole('option', { name: 'Initech' }))

    expect(input).toHaveValue('Initech')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('selects the highlighted option with Enter after ArrowDown navigation', async () => {
    render(<Fixture />)
    const input = screen.getByRole('combobox', { name: 'Customer' })
    // Clicking already opens the list (onFocus), starting at index 0
    // (Acme Corp) -- one ArrowDown moves the highlight to Globex Inc.
    await userEvent.click(input)
    await userEvent.keyboard('{ArrowDown}{Enter}')

    expect(input).toHaveValue('Globex Inc')
  })

  it('shows "No matches" for a query with no results', async () => {
    render(<Fixture />)
    const input = screen.getByRole('combobox', { name: 'Customer' })
    await userEvent.type(input, 'nonexistent')
    expect(screen.getByText('No matches')).toBeInTheDocument()
  })

  it('closes the list and moves focus to the next field on Tab', async () => {
    render(
      <div>
        <Fixture />
        <button type="button">Next field</button>
      </div>,
    )
    const input = screen.getByRole('combobox', { name: 'Customer' })
    await userEvent.click(input)
    expect(screen.getByRole('listbox')).toBeInTheDocument()

    await userEvent.tab()

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Next field' })).toHaveFocus()
  })

  it('reverts the typed query back to the selected label on outside click without selecting', async () => {
    render(
      <div>
        <button type="button">Outside</button>
        <Fixture />
      </div>,
    )
    const input = screen.getByRole('combobox', { name: 'Customer' })
    await userEvent.type(input, 'partial query')
    await userEvent.click(screen.getByRole('button', { name: 'Outside' }))

    expect(input).toHaveValue('')
  })
})
