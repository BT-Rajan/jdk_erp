import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { FileUploadField } from './FileUploadField'

function Fixture({ multiple = false }: { multiple?: boolean }) {
  const [files, setFiles] = useState<File[]>([])
  return <FileUploadField label="Attachments" multiple={multiple} value={files} onChange={setFiles} />
}

describe('FileUploadField', () => {
  it('adds a file selected via the hidden input and lists it', async () => {
    render(<Fixture />)
    const file = new File(['content'], 'invoice.pdf', { type: 'application/pdf' })
    const hiddenInput = document.querySelector('input[type="file"]') as HTMLInputElement
    await userEvent.upload(hiddenInput, file)

    expect(screen.getByText('invoice.pdf')).toBeInTheDocument()
  })

  it('replaces the file when multiple is false and a new one is chosen', async () => {
    render(<Fixture multiple={false} />)
    const hiddenInput = document.querySelector('input[type="file"]') as HTMLInputElement
    await userEvent.upload(hiddenInput, new File(['a'], 'a.pdf'))
    await userEvent.upload(hiddenInput, new File(['b'], 'b.pdf'))

    expect(screen.queryByText('a.pdf')).not.toBeInTheDocument()
    expect(screen.getByText('b.pdf')).toBeInTheDocument()
  })

  it('accumulates files when multiple is true', async () => {
    render(<Fixture multiple />)
    const hiddenInput = document.querySelector('input[type="file"]') as HTMLInputElement
    await userEvent.upload(hiddenInput, new File(['a'], 'a.pdf'))
    await userEvent.upload(hiddenInput, new File(['b'], 'b.pdf'))

    expect(screen.getByText('a.pdf')).toBeInTheDocument()
    expect(screen.getByText('b.pdf')).toBeInTheDocument()
  })

  it('removes a file via its remove button', async () => {
    render(<Fixture multiple />)
    const hiddenInput = document.querySelector('input[type="file"]') as HTMLInputElement
    await userEvent.upload(hiddenInput, new File(['a'], 'a.pdf'))

    await userEvent.click(screen.getByRole('button', { name: 'Remove a.pdf' }))
    expect(screen.queryByText('a.pdf')).not.toBeInTheDocument()
  })
})
