import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ActionMenu } from './ActionMenu'

function setup(overrides?: Partial<Parameters<typeof ActionMenu>[0]>) {
  const onSelectEdit = vi.fn()
  const onSelectDelete = vi.fn()
  render(
    <ActionMenu
      label="Row actions"
      options={[
        { key: 'edit', label: 'Edit', onSelect: onSelectEdit },
        { key: 'delete', label: 'Delete', onSelect: onSelectDelete, danger: true },
      ]}
      {...overrides}
    />,
  )
  return { onSelectEdit, onSelectDelete }
}

describe('ActionMenu', () => {
  it('is closed until the trigger is clicked', () => {
    setup()
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Row actions' })).toHaveAttribute('aria-expanded', 'false')
  })

  it('opens the menu, focuses the first item, and calls onSelect', async () => {
    const { onSelectEdit } = setup()
    await userEvent.click(screen.getByRole('button', { name: 'Row actions' }))

    expect(screen.getByRole('menu')).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Edit' })).toHaveFocus()

    await userEvent.click(screen.getByRole('menuitem', { name: 'Edit' }))
    expect(onSelectEdit).toHaveBeenCalledOnce()
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('closes on Escape', async () => {
    setup()
    await userEvent.click(screen.getByRole('button', { name: 'Row actions' }))
    expect(screen.getByRole('menu')).toBeInTheDocument()

    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('closes when clicking outside', async () => {
    render(
      <div>
        <button type="button">Outside</button>
        <ActionMenu label="Row actions" options={[{ key: 'edit', label: 'Edit', onSelect: vi.fn() }]} />
      </div>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Row actions' }))
    expect(screen.getByRole('menu')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Outside' }))
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('moves focus between items with ArrowDown/ArrowUp', async () => {
    setup()
    await userEvent.click(screen.getByRole('button', { name: 'Row actions' }))
    expect(screen.getByRole('menuitem', { name: 'Edit' })).toHaveFocus()

    await userEvent.keyboard('{ArrowDown}')
    expect(screen.getByRole('menuitem', { name: 'Delete' })).toHaveFocus()

    await userEvent.keyboard('{ArrowUp}')
    expect(screen.getByRole('menuitem', { name: 'Edit' })).toHaveFocus()
  })

  it('skips disabled options when navigating and never fires their onSelect', async () => {
    const onSelect = vi.fn()
    render(
      <ActionMenu
        label="Row actions"
        options={[
          { key: 'edit', label: 'Edit', onSelect: vi.fn(), disabled: true },
          { key: 'delete', label: 'Delete', onSelect },
        ]}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Row actions' }))
    expect(screen.getByRole('menuitem', { name: 'Delete' })).toHaveFocus()
    expect(screen.getByRole('menuitem', { name: 'Edit' })).toBeDisabled()
  })
})
