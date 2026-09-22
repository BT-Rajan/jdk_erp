import { useCallback, useEffect, useRef, useState } from 'react'
import { Bell, CheckCheck } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { cn } from '@/lib/cn'
import { formatDateTime } from '@/lib/format'
import { useDismissableOverlay } from '@/lib/useDismissableOverlay'
import { apiClient } from '@/lib/apiClient'
import { IconButton } from './IconButton'
import { Spinner } from './Spinner'

/** Mirrors backend/app/schemas/notification.py's NotificationOut. */
interface Notification {
  id: number
  type: 'INFO' | 'ACTION_REQUIRED' | 'SUCCESS' | 'WARNING' | 'ERROR'
  title: string
  message: string
  entity_type: string | null
  entity_id: number | null
  target_url: string | null
  is_read: boolean
  created_at: string
  read_at: string | null
}

const TYPE_DOT_CLASSES: Record<Notification['type'], string> = {
  INFO: 'bg-info-500',
  ACTION_REQUIRED: 'bg-gold-400',
  SUCCESS: 'bg-success-500',
  WARNING: 'bg-warning-500',
  ERROR: 'bg-danger-500',
}

const POLL_INTERVAL_MS = 30_000

/** The one standard notification UI every module's `notify()` call
 * eventually surfaces through (docs/modules/notifications.md #3) -- no
 * module builds its own. Polls the unread count rather than holding a
 * push connection open (that document's own "don't build
 * push-notification infrastructure"). Server-side is the real boundary
 * (Principle 3): this only ever renders what GET /api/notifications
 * already scoped to the current user. */
export function NotificationBell() {
  const [open, setOpen] = useState(false)
  const [unreadCount, setUnreadCount] = useState(0)
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [loading, setLoading] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()

  useDismissableOverlay(containerRef, { open, onDismiss: () => setOpen(false) })

  const refreshUnreadCount = useCallback(async () => {
    try {
      const { data } = await apiClient.get<{ count: number }>('/api/notifications/unread-count')
      setUnreadCount(data.count)
    } catch {
      // Best-effort -- a failed poll just tries again next interval.
    }
  }, [])

  useEffect(() => {
    void refreshUnreadCount()
    const timer = setInterval(() => void refreshUnreadCount(), POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [refreshUnreadCount])

  async function loadList() {
    setLoading(true)
    try {
      const { data } = await apiClient.get<Notification[]>('/api/notifications', { params: { limit: 20 } })
      setNotifications(data)
    } catch {
      // Leave whatever was last loaded -- the panel still opens.
    } finally {
      setLoading(false)
    }
  }

  function toggleOpen() {
    setOpen((value) => {
      const next = !value
      if (next) void loadList()
      return next
    })
  }

  function handleSelect(notification: Notification) {
    setOpen(false)
    if (!notification.is_read) {
      setNotifications((current) => current.map((n) => (n.id === notification.id ? { ...n, is_read: true } : n)))
      setUnreadCount((count) => Math.max(0, count - 1))
      apiClient.patch(`/api/notifications/${notification.id}/read`).catch(() => {})
    }
    if (notification.target_url) navigate(notification.target_url)
  }

  async function handleMarkAllRead() {
    const previous = notifications
    const previousCount = unreadCount
    setNotifications((current) => current.map((n) => ({ ...n, is_read: true })))
    setUnreadCount(0)
    try {
      await apiClient.post('/api/notifications/mark-all-read')
    } catch {
      setNotifications(previous)
      setUnreadCount(previousCount)
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <IconButton
        icon={
          <span className="relative">
            <Bell size={18} aria-hidden="true" />
            {unreadCount > 0 && (
              <span className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger-500 px-1 text-[10px] font-semibold text-white">
                {unreadCount > 99 ? '99+' : unreadCount}
              </span>
            )}
          </span>
        }
        aria-label={unreadCount > 0 ? `Notifications, ${unreadCount} unread` : 'Notifications'}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={toggleOpen}
      />
      {open && (
        <div
          role="menu"
          aria-label="Notifications"
          className="absolute right-0 z-10 mt-2 w-80 rounded-md border border-ink-600 bg-ink-800 shadow-lg"
        >
          <div className="flex items-center justify-between border-b border-ink-700 px-3 py-2">
            <span className="text-sm font-semibold text-gold-100">Notifications</span>
            {unreadCount > 0 && (
              <button
                type="button"
                onClick={() => void handleMarkAllRead()}
                className="flex items-center gap-1 text-xs text-gold-300 transition-colors hover:text-gold-100"
              >
                <CheckCheck size={14} aria-hidden="true" />
                Mark all read
              </button>
            )}
          </div>
          <div className="max-h-96 overflow-y-auto">
            {loading ? (
              <div className="flex justify-center py-8">
                <Spinner />
              </div>
            ) : notifications.length === 0 ? (
              <p className="px-3 py-8 text-center text-sm text-gold-100/50">No notifications yet.</p>
            ) : (
              notifications.map((notification) => (
                <button
                  key={notification.id}
                  type="button"
                  role="menuitem"
                  onClick={() => handleSelect(notification)}
                  className={cn(
                    'flex w-full items-start gap-2 border-b border-ink-700/60 px-3 py-2.5 text-left transition-colors last:border-0 hover:bg-ink-700',
                    !notification.is_read && 'bg-ink-700/30',
                  )}
                >
                  <span
                    aria-hidden="true"
                    className={cn(
                      'mt-1.5 h-2 w-2 shrink-0 rounded-full',
                      notification.is_read ? 'bg-transparent' : TYPE_DOT_CLASSES[notification.type],
                    )}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-gold-100">{notification.title}</span>
                    <span className="block truncate text-xs text-gold-100/60">{notification.message}</span>
                    <span className="block text-[11px] text-gold-100/40">{formatDateTime(notification.created_at)}</span>
                  </span>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
