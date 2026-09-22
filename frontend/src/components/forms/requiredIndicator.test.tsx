import type { ReactElement } from 'react'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TextField } from './TextField'
import { NumberField } from './NumberField'
import { DateField } from './DateField'
import { SelectField } from './SelectField'
import { TextareaField } from './TextareaField'
import { RadioGroupField } from './RadioGroupField'

describe('required indicator', () => {
  it('shows the visual indicator on every field type, but never sets the native required attribute', () => {
    const cases: Array<[string, ReactElement]> = [
      ['Name', <TextField key="t" label="Name" required />],
      ['Quantity', <NumberField key="n" label="Quantity" required />],
      ['Due date', <DateField key="d" label="Due date" required />],
      [
        'Status',
        <SelectField key="s" label="Status" required>
          <option value="a">A</option>
        </SelectField>,
      ],
      ['Notes', <TextareaField key="ta" label="Notes" required />],
    ]
    for (const [label, element] of cases) {
      const { container, unmount } = render(element)
      // Not required natively -- see FieldShell's `required` doc comment:
      // native HTML5 constraint validation would silently block a
      // react-hook-form + zod submit before the zod resolver ever runs.
      expect(screen.getByLabelText(label)).not.toBeRequired()
      expect(container.querySelector('label')?.className).toContain("after:content-['*']")
      unmount()
    }
  })

  it('shows no indicator class when not required', () => {
    const { container } = render(<TextField label="Name" />)
    expect(container.querySelector('label')?.className).not.toContain('after:content')
  })

  it('marks a required radiogroup with aria-required, not native required', () => {
    render(
      <RadioGroupField
        label="Payment terms"
        name="terms"
        required
        options={[{ value: 'net30', label: 'Net 30' }]}
      />,
    )
    expect(screen.getByRole('radiogroup')).toHaveAttribute('aria-required', 'true')
    expect(screen.getByRole('radio', { name: 'Net 30' })).not.toBeRequired()
  })
})
