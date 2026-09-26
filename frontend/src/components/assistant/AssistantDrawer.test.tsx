import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AssistantDrawer } from './AssistantDrawer'

const { postMock } = vi.hoisted(() => ({ postMock: vi.fn() }))
vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { post: postMock } }
})

beforeEach(() => {
  postMock.mockReset()
})

describe('AssistantDrawer', () => {
  it('sends the question with earlier turns (not the greeting) and renders the reply', async () => {
    postMock
      .mockResolvedValueOnce({ data: { reply: 'Open **Sales > Quotations**\n- Click **New Quotation**' } })
      .mockResolvedValueOnce({ data: { reply: 'It is a draft.' } })
    render(<AssistantDrawer open onClose={() => undefined} />)

    await userEvent.type(screen.getByLabelText('Ask the assistant'), 'How do I create a quotation?{Enter}')
    expect(await screen.findByText('Sales > Quotations')).toHaveProperty('tagName', 'STRONG')
    expect(postMock).toHaveBeenCalledWith('/api/assistant/chat', { message: 'How do I create a quotation?', history: [] })

    await userEvent.type(screen.getByLabelText('Ask the assistant'), 'Status of 2640001?')
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByText('It is a draft.')).toBeInTheDocument()
    expect(postMock.mock.calls[1][1].history).toEqual([
      { role: 'user', content: 'How do I create a quotation?' },
      { role: 'assistant', content: 'Open **Sales > Quotations**\n- Click **New Quotation**' },
    ])
  })

  it('shows an error and keeps the question when the assistant cannot be reached', async () => {
    postMock.mockRejectedValueOnce(new Error('offline'))
    render(<AssistantDrawer open onClose={() => undefined} />)
    await userEvent.type(screen.getByLabelText('Ask the assistant'), 'Hello{Enter}')
    await waitFor(() => expect(screen.getByText(/could not be reached/i)).toBeInTheDocument())
    expect(screen.getByText('Hello')).toBeInTheDocument()
  })
})
