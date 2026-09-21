import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { UserChip } from './UserChip'

describe('UserChip', () => {
  it('renders name and subtitle alongside the avatar', () => {
    render(<UserChip src={null} name="Ada Lovelace" subtitle="Admin" />)
    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument()
    expect(screen.getByText('Admin')).toBeInTheDocument()
    expect(screen.getByText('AL')).toBeInTheDocument()
  })

  it('renders without a subtitle', () => {
    render(<UserChip src={null} name="Ada Lovelace" />)
    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument()
  })
})
