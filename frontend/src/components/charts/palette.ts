/** Default series palette -- reads the same theme tokens as everything
 * else (src/index.css), not a separate colour list, so a chart's colours
 * always match the rest of the UI. Recharts renders inline SVG in the
 * DOM, so CSS custom properties resolve normally here. */
export const CHART_COLORS = [
  'var(--color-gold-400)',
  'var(--color-violet-500)',
  'var(--color-info-500)',
  'var(--color-success-500)',
  'var(--color-warning-500)',
  'var(--color-danger-500)',
]
