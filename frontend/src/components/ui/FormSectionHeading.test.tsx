import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FormSectionHeading } from './FormSectionHeading'

describe('FormSectionHeading', () => {
  it('renders its label as a heading', () => {
    render(<FormSectionHeading>Contact details</FormSectionHeading>)
    expect(screen.getByRole('heading', { name: 'Contact details' })).toBeInTheDocument()
  })
})
