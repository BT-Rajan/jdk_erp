import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Avatar } from './Avatar'

describe('Avatar', () => {
  it('renders an image when src is given', () => {
    render(<Avatar src="https://example.com/ada.png" name="Ada Lovelace" />)
    expect(screen.getByRole('img', { name: 'Ada Lovelace' })).toHaveAttribute('src', 'https://example.com/ada.png')
  })

  it('falls back to two-letter initials from first and last name when there is no src', () => {
    render(<Avatar src={null} name="Ada Lovelace" />)
    expect(screen.getByText('AL')).toBeInTheDocument()
  })

  it('uses the first two letters of a single-word name', () => {
    render(<Avatar src={null} name="Cher" />)
    expect(screen.getByText('CH')).toBeInTheDocument()
  })
})
