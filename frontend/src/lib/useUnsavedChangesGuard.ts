import { useEffect } from 'react'

/** Warns on tab close/refresh/external navigation while `isDirty` is
 * true, via the browser's native beforeunload prompt.
 *
 * Deliberately does NOT block in-app route changes (e.g. clicking a
 * sidebar link away from an unsaved form): react-router's `useBlocker`
 * needs a data router (`createBrowserRouter`), and this app currently
 * uses declarative `<BrowserRouter>` with no forms/routes built yet --
 * adopting a data router now, before any screen needs it, would be an
 * architecture change the spec doesn't ask for (see Engineering
 * Principle 5 -- no caller, no abstraction). Until then, a form's own
 * Cancel/Back handler can check the same `isDirty` flag and confirm via
 * ConfirmDialog before navigating -- reusing the existing component
 * instead of a new one. */
export function useUnsavedChangesGuard(isDirty: boolean) {
  useEffect(() => {
    if (!isDirty) return

    function handleBeforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault()
      event.returnValue = ''
    }

    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [isDirty])
}
