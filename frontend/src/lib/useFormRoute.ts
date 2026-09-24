import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ApiError, apiClient } from '@/lib/apiClient'

interface FormRouteHandlers<T> {
  /** Reset the form for a new record. */
  onCreate: () => void
  /** Fill the form from an existing record. */
  onEdit: (record: T) => void
}

/** Drives a master-data page's create/edit form from the URL:
 * `${basePath}/new` and `${basePath}/:id/edit` open the form (FormPage),
 * `${basePath}` shows the list. Opening Edit from the list passes the row
 * along; a direct visit or refresh fetches it from `${apiPath}/:id`. */
export function useFormRoute<T extends { id: number }>(basePath: string, apiPath: string, handlers: FormRouteHandlers<T>) {
  const location = useLocation()
  const navigate = useNavigate()
  const handlersRef = useRef(handlers)
  handlersRef.current = handlers

  const isNew = location.pathname === `${basePath}/new`
  const editMatch = location.pathname.startsWith(`${basePath}/`) ? /^\/(\d+)\/edit$/.exec(location.pathname.slice(basePath.length)) : null
  const recordId = editMatch ? editMatch[1] : null
  const passed = (location.state as { record?: T } | null)?.record

  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    setLoadError(null)
    if (isNew) {
      setLoading(false)
      handlersRef.current.onCreate()
      return
    }
    if (!recordId) return
    if (passed && String(passed.id) === recordId) {
      setLoading(false)
      handlersRef.current.onEdit(passed)
      return
    }
    let cancelled = false
    setLoading(true)
    apiClient
      .get<T>(`${apiPath}/${recordId}`)
      .then(({ data }) => {
        if (!cancelled) handlersRef.current.onEdit(data)
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err instanceof ApiError ? err.message : 'Failed to load this record.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [isNew, recordId, apiPath])

  return {
    formOpen: isNew || recordId !== null,
    loading,
    loadError,
    openCreate: () => navigate(`${basePath}/new`),
    openEdit: (record: T) => navigate(`${basePath}/${record.id}/edit`, { state: { record } }),
    closeForm: () => navigate(basePath),
  }
}
