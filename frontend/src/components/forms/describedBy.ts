export function describedBy(hint: string | undefined, error: string | undefined, hintId: string, errorId: string) {
  if (error) return errorId
  if (hint) return hintId
  return undefined
}
