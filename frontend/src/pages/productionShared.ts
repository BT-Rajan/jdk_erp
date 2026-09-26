/** Labels shared by the Production pages. Mirrors
 * backend/app/models/production_order.py; the status itself always comes
 * from the server. */

import type { BadgeTone } from '@/components/ui/Badge'

export const PRODUCTION_ORDER_STATUS_LABELS: Record<string, string> = {
  draft: 'Draft',
  issued: 'Issued',
  in_progress: 'In progress',
  partially_completed: 'Partially completed',
  completed: 'Completed',
  cancelled: 'Cancelled',
}
export const PRODUCTION_ORDER_STATUS_TONES: Record<string, BadgeTone> = {
  draft: 'warning',
  issued: 'info',
  in_progress: 'info',
  partially_completed: 'warning',
  completed: 'success',
  cancelled: 'neutral',
}
