import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { TextareaField } from './TextareaField'

describe('TextareaField', () => {
  it('defaults to 3 rows and accepts typed input', async () => {
    render(<TextareaField label="Notes" />)
    const textarea = screen.getByLabelText('Notes')
    expect(textarea).toHaveAttribute('rows', '3')
    await userEvent.type(textarea, 'Some notes')
    expect(textarea).toHaveValue('Some notes')
  })
})
