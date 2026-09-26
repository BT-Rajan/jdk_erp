import { useEffect, useState } from 'react'
import { AccessDeniedState } from '@/components/ui/AccessDeniedState'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { FormSectionHeading } from '@/components/ui/FormSectionHeading'
import { PageHeader } from '@/components/ui/PageHeader'
import { Spinner } from '@/components/ui/Spinner'
import { TextField } from '@/components/forms/TextField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { useAuth } from '@/lib/auth/AuthContext'
import { isAdminRole } from '@/lib/auth/roles'

/** Mirrors backend/app/schemas/assistant.py's AssistantSettingsOut. */
interface AssistantSettings {
  configured: boolean
  provider: string | null
  key_hint: string | null
}

const PROVIDER_LABELS: Record<string, string> = { claude: 'Claude (Anthropic)', deepseek: 'DeepSeek' }

/** Settings -> AI Assistant (Admin): the API key the JDK Assistant uses.
 * An Anthropic key ("sk-ant-...") selects Claude; any other key DeepSeek.
 * The key is stored encrypted and never shown again -- only its last four
 * characters. Server-side require_admin is the real boundary. */
export function AssistantSettingsPage() {
  const { user } = useAuth()
  const isAdmin = isAdminRole(user?.role)
  const [settings, setSettings] = useState<AssistantSettings | null>(null)
  const [apiKey, setApiKey] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!isAdmin) return
    apiClient
      .get<AssistantSettings>('/api/assistant/settings')
      .then(({ data }) => setSettings(data))
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Failed to load the assistant settings.'))
  }, [isAdmin])

  async function save(key: string | null) {
    setBusy(true)
    setError(null)
    setSaved(null)
    try {
      const { data } = await apiClient.put<AssistantSettings>('/api/assistant/settings', { api_key: key })
      setSettings(data)
      setApiKey('')
      setSaved(data.configured ? 'API key saved.' : 'API key removed -- the assistant is off.')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save the API key.')
    } finally {
      setBusy(false)
    }
  }

  if (!isAdmin) return <AccessDeniedState />
  if (!settings && !error) return <Spinner />

  return (
    <div className="space-y-6">
      <PageHeader title="AI Assistant" subtitle="The JDK Assistant answers how-to and status questions. It never changes data." />
      <Alert variant="danger">{error}</Alert>
      <Alert variant="success">{saved}</Alert>
      {settings && (
        <Card className="space-y-4 p-6">
          <FormSectionHeading>API key</FormSectionHeading>
          <p className="text-sm text-gold-100/70">
            {settings.configured
              ? `Active: ${PROVIDER_LABELS[settings.provider ?? ''] ?? settings.provider}, key ending ${settings.key_hint}.`
              : 'Not set -- the assistant is off.'}
          </p>
          <TextField
            label={settings.configured ? 'Replace API key' : 'API key'}
            type="password"
            autoComplete="off"
            hint='An Anthropic key (starts with "sk-ant-") uses Claude; any other key uses DeepSeek.'
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void save(apiKey.trim())} isLoading={busy} disabled={busy || !apiKey.trim()}>
              Save Key
            </Button>
            {settings.configured && (
              <Button variant="danger" onClick={() => void save(null)} disabled={busy}>
                Remove Key
              </Button>
            )}
          </div>
        </Card>
      )}
    </div>
  )
}
