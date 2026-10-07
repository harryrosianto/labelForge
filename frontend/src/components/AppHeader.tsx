import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

/** Brand bar: logo Syspex + nama aplikasi. `children` = konten kanan (breadcrumb, aksi). */
export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link to="/" className="flex shrink-0 items-center gap-3" title="LabelForge: semua project">
      <img src="/syspex-logo.png" alt="Syspex" className={compact ? 'h-4' : 'h-6'} />
      <span className="h-5 w-px bg-slate-300" />
      <span className={`font-semibold tracking-tight text-ink ${compact ? 'text-sm' : 'text-base'}`}>
        Label<span className="text-brand-600">Forge</span>
      </span>
    </Link>
  )
}

export function AppHeader({ children }: { children?: ReactNode }) {
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-4 px-6">
        <Brand />
        {children}
      </div>
    </header>
  )
}
