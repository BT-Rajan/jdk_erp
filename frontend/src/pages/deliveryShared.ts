/** Types and labels shared by the Delivery pages. They mirror
 * backend/app/schemas/delivery_instruction.py; every rule (eligibility,
 * limits, stock, transitions) is the server's -- nothing here decides one. */

import type { BadgeTone } from '@/components/ui/Badge'

export interface DeliveryLine {
  id: number
  sales_order_line_id: number
  product_id: number
  unit_of_measure_id: number
  ordered_quantity: string
  quantity: string
  quantity_override_reason: string | null
  pallet_count_default: number | null
  pallet_count: number | null
  pallet_count_manual: boolean
}

export interface DeliveryInstruction {
  id: number
  delivery_number: string
  sales_order_id: number
  sales_order_number: string | null
  customer_id: number
  customer_name: string | null
  status: string
  scrap_allowance_percent: string
  fulfilled_at: string | null
  fulfilled_by_user_id: number | null
  not_fulfilled_reason: string | null
  not_fulfilled_at: string | null
  created_by_user_id: number | null
  created_at: string
  lines: DeliveryLine[]
}

export interface DeliveryLinePosition {
  sales_order_line_id: number
  product_id: number
  unit_of_measure_id: number
  ordered_quantity: string
  fulfilled_quantity: string
  remaining_quantity: string
  ceiling_quantity: string
  remaining_permitted_quantity: string
}

export interface DeliveryPosition {
  sales_order_id: number
  sales_order_number: string
  sales_order_status: string
  customer_name: string | null
  requested_delivery_date: string | null
  can_create: boolean
  scrap_allowance_percent: string
  allowance_locked: boolean
  lines: DeliveryLinePosition[]
}

export interface DeliverableOrder {
  id: number
  order_number: string
  customer_name: string | null
  requested_delivery_date: string | null
  status: string
}

export const DELIVERY_STATUS_LABELS: Record<string, string> = {
  pending: 'Pending',
  fulfilled: 'Fulfilled',
  not_fulfilled: 'Not fulfilled',
}

export const DELIVERY_STATUS_TONES: Record<string, BadgeTone> = {
  pending: 'warning',
  fulfilled: 'success',
  not_fulfilled: 'danger',
}
