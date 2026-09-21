import type { ReactNode } from 'react'

export interface NavLeaf {
  type: 'leaf'
  label: string
  to: string
  icon?: ReactNode
}

export interface NavGroup {
  type: 'group'
  label: string
  icon?: ReactNode
  items: { label: string; to: string }[]
}

/** The one declarative nav-tree shape TopNav and Sidebar both accept.
 * Neither component owns auth/permission state -- the app filters this
 * array and passes in only what the current user can see. */
export type NavEntry = NavLeaf | NavGroup
