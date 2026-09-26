/**
 * Purely decorative ambient glow behind the glass panels. Fixed + inert so
 * it never intercepts clicks or gets announced to screen readers, and never
 * affects layout/scroll height of the page it sits behind.
 */
export function AmbientBackground() {
  return (
    <div aria-hidden="true" className="fixed inset-0 -z-10 overflow-hidden bg-ink-950">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--color-ink-800),_var(--color-ink-950)_65%)]" />

      <div className="absolute -top-40 -left-32 h-[36rem] w-[36rem] rounded-full bg-gold-600/20 blur-[120px]" />
      <div className="absolute top-1/3 -right-40 h-[30rem] w-[30rem] rounded-full bg-violet-600/25 blur-[130px]" />
      <div className="absolute bottom-[-10rem] left-1/4 h-[28rem] w-[28rem] rounded-full bg-gold-500/10 blur-[110px]" />

      {/* Faint grain/texture so large flat glass panels don't look sterile. */}
      <div
        className="absolute inset-0 opacity-[0.03] mix-blend-overlay"
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")",
        }}
      />
    </div>
  )
}
