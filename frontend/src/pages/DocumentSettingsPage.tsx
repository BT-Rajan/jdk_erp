import { useEffect, useState } from 'react'
import { AccessDeniedState } from '@/components/ui/AccessDeniedState'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { FormSectionHeading } from '@/components/ui/FormSectionHeading'
import { PageHeader } from '@/components/ui/PageHeader'
import { Spinner } from '@/components/ui/Spinner'
import { FileUploadField } from '@/components/forms/FileUploadField'
import { NumberField } from '@/components/forms/NumberField'
import { TextareaField } from '@/components/forms/TextareaField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { useAuth } from '@/lib/auth/AuthContext'
import { isAdminRole } from '@/lib/auth/roles'

/** Mirrors backend/app/schemas/document_template.py's DocumentTemplateOut. */
interface DocumentTemplate {
  document_type: string
  letterhead_file_id: number | null
  letterhead_file: { id: number; original_filename: string } | null
  margin_top_mm: number
  margin_bottom_mm: number
  intro_text: string | null
  terms_text: string | null
  signature_text: string | null
}

/** Admin Setup -> Documents: the letterhead and wording printed on every
 * RFQ PDF generated from now on (backend/app/api/document_templates.py).
 * The letterhead is a full A4 page image; the margins keep the RFQ
 * content clear of its printed header and footer. */
export function DocumentSettingsPage() {
  const { user } = useAuth()
  const isAdmin = isAdminRole(user?.role)

  const [template, setTemplate] = useState<DocumentTemplate | null>(null)
  const [letterheadPreview, setLetterheadPreview] = useState<string | null>(null)
  const [newLetterhead, setNewLetterhead] = useState<File[]>([])
  const [removeLetterhead, setRemoveLetterhead] = useState(false)
  const [marginTop, setMarginTop] = useState('40')
  const [marginBottom, setMarginBottom] = useState('25')
  const [introText, setIntroText] = useState('')
  const [termsText, setTermsText] = useState('')
  const [signatureText, setSignatureText] = useState('')
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  function apply(data: DocumentTemplate) {
    setTemplate(data)
    setMarginTop(String(data.margin_top_mm))
    setMarginBottom(String(data.margin_bottom_mm))
    setIntroText(data.intro_text ?? '')
    setTermsText(data.terms_text ?? '')
    setSignatureText(data.signature_text ?? '')
    setNewLetterhead([])
    setRemoveLetterhead(false)
  }

  useEffect(() => {
    if (!isAdmin) return
    apiClient
      .get<DocumentTemplate>('/api/document-templates/rfq')
      .then(({ data }) => apply(data))
      .catch((err) => setLoadError(err instanceof ApiError ? err.message : 'Failed to load the document template.'))
  }, [isAdmin])

  useEffect(() => {
    const fileId = template?.letterhead_file_id
    if (!fileId) {
      setLetterheadPreview(null)
      return
    }
    let url: string | null = null
    apiClient
      .get(`/api/files/${fileId}`, { responseType: 'blob' })
      .then((response) => {
        url = window.URL.createObjectURL(response.data as Blob)
        setLetterheadPreview(url)
      })
      .catch(() => setLetterheadPreview(null))
    return () => {
      if (url) window.URL.revokeObjectURL(url)
    }
  }, [template?.letterhead_file_id])

  async function save() {
    const top = Number(marginTop)
    const bottom = Number(marginBottom)
    if (!Number.isInteger(top) || !Number.isInteger(bottom) || top < 5 || top > 120 || bottom < 5 || bottom > 120) {
      setSaveError('Margins must be whole numbers between 5 and 120 mm.')
      return
    }
    setSaving(true)
    setSaveError(null)
    setSaved(null)
    try {
      let letterheadFileId = removeLetterhead ? null : template?.letterhead_file_id ?? null
      if (newLetterhead.length > 0) {
        const form = new FormData()
        form.append('upload', newLetterhead[0])
        const { data } = await apiClient.post<{ id: number }>('/api/files', form)
        letterheadFileId = data.id
      }
      const { data } = await apiClient.put<DocumentTemplate>('/api/document-templates/rfq', {
        letterhead_file_id: letterheadFileId,
        margin_top_mm: top,
        margin_bottom_mm: bottom,
        intro_text: introText,
        terms_text: termsText,
        signature_text: signatureText,
      })
      apply(data)
      setSaved('Saved. New RFQ PDFs will use this template.')
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : 'Failed to save the document template.')
    } finally {
      setSaving(false)
    }
  }

  if (!isAdmin) return <AccessDeniedState />

  return (
    <div className="space-y-6">
      <PageHeader title="Documents" subtitle="Letterhead and wording for generated RFQ PDFs." />
      <Alert variant="danger">{loadError}</Alert>

      {!template && !loadError ? (
        <Spinner />
      ) : (
        <Card>
          <div className="flex flex-col gap-4">
            <Alert variant="danger">{saveError}</Alert>
            <Alert variant="success">{saved}</Alert>

            <FormSectionHeading>Letterhead</FormSectionHeading>
            <p className="text-sm text-gold-100/60">A full A4 page image (PNG or JPEG) printed behind every page of the RFQ.</p>
            {letterheadPreview && !removeLetterhead && (
              <div className="flex items-start gap-4">
                <img src={letterheadPreview} alt="Current letterhead" className="w-40 rounded border border-ink-700 bg-white" />
                <Button variant="secondary" onClick={() => setRemoveLetterhead(true)}>Remove letterhead</Button>
              </div>
            )}
            {!template?.letterhead_file_id && (
              <p className="text-sm text-gold-100/60">No letterhead set -- PDFs print the organisation name and address at the top.</p>
            )}
            <FileUploadField label="Upload new letterhead" accept=".png,.jpg,.jpeg" value={newLetterhead} onChange={setNewLetterhead} />
            <div className="grid gap-4 sm:grid-cols-2">
              <NumberField label="Top margin (mm)" hint="Space kept clear for the letterhead header." value={marginTop} onChange={(e) => setMarginTop(e.target.value)} />
              <NumberField label="Bottom margin (mm)" hint="Space kept clear for the letterhead footer." value={marginBottom} onChange={(e) => setMarginBottom(e.target.value)} />
            </div>

            <FormSectionHeading>RFQ Content</FormSectionHeading>
            <TextareaField label="Opening text" hint="Printed above the items, e.g. 'Dear Sir, please quote for the following...'" value={introText} onChange={(e) => setIntroText(e.target.value)} />
            <TextareaField label="Terms" hint="Printed below the items, e.g. quotation validity, delivery location." value={termsText} onChange={(e) => setTermsText(e.target.value)} />
            <TextareaField label="Signature block" hint="e.g. name, title, company." value={signatureText} onChange={(e) => setSignatureText(e.target.value)} />

            <div>
              <Button onClick={save} isLoading={saving}>Save</Button>
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}
