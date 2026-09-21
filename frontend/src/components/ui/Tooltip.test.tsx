import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { Tooltip } from './Tooltip'

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

describe('Tooltip', () => {
  it('is not shown until hovered, then appears after the delay', async () => {
    const user = userEvent.setup()
    render(
      <Tooltip label="Edit this row">
        <button type="button">Edit</button>
      </Tooltip>,
    )
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()

    await user.hover(screen.getByRole('button', { name: 'Edit' }))
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()

    await wait(350)
    expect(screen.getByRole('tooltip')).toHaveTextContent('Edit this row')
  }, 10000)

  it('hides on unhover', async () => {
    const user = userEvent.setup()
    render(
      <Tooltip label="Edit this row">
        <button type="button">Edit</button>
      </Tooltip>,
    )
    await user.hover(screen.getByRole('button', { name: 'Edit' }))
    await wait(350)
    expect(screen.getByRole('tooltip')).toBeInTheDocument()

    await user.unhover(screen.getByRole('button', { name: 'Edit' }))
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  }, 10000)

  it('associates the tooltip via aria-describedby once visible', async () => {
    const user = userEvent.setup()
    render(
      <Tooltip label="Edit this row">
        <button type="button">Edit</button>
      </Tooltip>,
    )
    await user.hover(screen.getByRole('button', { name: 'Edit' }))
    await wait(350)

    const button = screen.getByRole('button', { name: 'Edit' })
    const tooltip = screen.getByRole('tooltip')
    expect(button).toHaveAttribute('aria-describedby', tooltip.id)
  }, 10000)
})
