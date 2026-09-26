import type { ReactNode } from 'react'
import { motion } from 'framer-motion'
import { AmbientBackground } from './AmbientBackground'

interface AuthLayoutProps {
  title: string
  subtitle?: string
  children: ReactNode
}

/** Shared shell for every unauthenticated screen (login today; reset/
 * invite flows later) -- the split hero + glass-card treatment lives
 * here once rather than being copy-pasted per page, per
 * docs/DESIGN_SYSTEM.md's Elevation & surfaces note. */
export function AuthLayout({ title, subtitle, children }: AuthLayoutProps) {
  return (
    <div className="relative flex min-h-screen w-full items-center justify-center px-4 py-10 sm:px-6 lg:px-10">
      <AmbientBackground />

      <div className="grid w-full max-w-5xl grid-cols-1 items-center gap-10 lg:grid-cols-2 lg:gap-16">
        {/* Brand panel -- hidden on small screens to keep the auth flow
            focused there; the card alone carries the wordmark. */}
        <motion.div
          initial={{ opacity: 0, x: -16 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
          className="hidden flex-col lg:flex"
        >
          <span className="mb-10 font-display text-lg font-medium tracking-wide text-white">
            JDK <span className="text-gradient-gold">ERP</span>
          </span>
          <h1 className="font-display text-4xl leading-[1.15] font-medium text-white sm:text-5xl">
            One workspace for <span className="text-gradient-gold">sales</span>, orders
            <br />
            and <span className="text-gradient-gold">inventory</span>
          </h1>
          <p className="mt-6 max-w-md text-[15px] leading-relaxed text-gold-100/50">
            Quotations, bills of material, goods receiving and stock -- all tightly
            connected, built for the people who keep the floor running.
          </p>

          <div className="mt-14 flex items-center gap-6 text-xs tracking-[0.2em] text-gold-100/30 uppercase">
            <span>Secure Access</span>
            <span className="h-1 w-1 rounded-full bg-gold-100/20" />
            <span>Role-based Control</span>
          </div>
        </motion.div>

        {/* Form panel */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: 'easeOut', delay: 0.1 }}
          className="mx-auto w-full max-w-md"
        >
          <div className="mb-8 flex flex-col items-center gap-2 lg:hidden">
            <span className="font-display text-lg font-medium tracking-wide text-white">
              JDK <span className="text-gradient-gold">ERP</span>
            </span>
          </div>

          <div className="glass-panel-strong rounded-3xl p-8 sm:p-10">
            <div className="mb-8">
              <h2 className="font-display text-2xl font-medium text-white">{title}</h2>
              {subtitle && <p className="mt-2 text-sm text-gold-100/50">{subtitle}</p>}
            </div>
            {children}
          </div>
        </motion.div>
      </div>
    </div>
  )
}
