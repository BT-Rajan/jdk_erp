/** Mirrors backend/app/core/roles.py -- the fixed four-role set, kept as
 * one shared constant instead of a literal string repeated at every
 * call site that checks or offers a role. The backend remains the real
 * authority (Principle 3): this only drives what the UI shows/offers. */
export const SUPER_ADMIN = 'super_admin'
export const ADMIN = 'admin'
export const MANAGER = 'manager'
export const TEAM_MEMBER = 'team_member'

export const VALID_ROLES = [SUPER_ADMIN, ADMIN, MANAGER, TEAM_MEMBER] as const

export type Role = (typeof VALID_ROLES)[number]

const ADMIN_ROLES: readonly string[] = [SUPER_ADMIN, ADMIN]

export function isAdminRole(role: string | undefined): boolean {
  return !!role && ADMIN_ROLES.includes(role)
}

export const ROLE_LABELS: Record<string, string> = {
  [SUPER_ADMIN]: 'Super Admin',
  [ADMIN]: 'Admin',
  [MANAGER]: 'Manager',
  [TEAM_MEMBER]: 'Team Member',
}
