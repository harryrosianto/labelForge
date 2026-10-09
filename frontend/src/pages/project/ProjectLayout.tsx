import { Link, NavLink, Outlet } from 'react-router-dom'

import { useHealth, useProject } from '../../api/hooks'
import { Brand } from '../../components/AppHeader'
import { ErrorText, Spinner } from '../../components/ui'
import { useProjectId } from '../../lib/route'

const tabs = [
  ['', 'Overview'],
  ['classes', 'Classes'],
  ['upload', 'Upload'],
  ['cameras', 'Kamera'],
  ['gallery', 'Galeri'],
  ['autolabel', 'Auto-label'],
  ['versions', 'Versi'],
  ['export', 'Export'],
] as const

const QUEUE_LABELS: Record<string, string> = { inference: 'auto-label', io: 'import, versi, video & kamera' }

function WorkerStatus() {
  const { data } = useHealth()
  if (!data) return null
  const loading = data.worker_details.some((w) => w.state !== 'ready')
  const missing = data.queues_without_worker
  let tone = 'emerald'
  let text = 'Worker aktif'
  if (data.workers.length === 0) {
    tone = 'amber'
    text = 'Worker tidak aktif, job akan menunggu'
  } else if (loading && missing.length) {
    tone = 'sky'
    text = 'Worker sedang memuat model…'
  } else if (missing.length) {
    tone = 'amber'
    text = `Tidak ada worker untuk ${missing.map((q) => QUEUE_LABELS[q] ?? q).join(' dan ')}`
  }
  const colors: Record<string, [string, string]> = {
    emerald: ['text-emerald-700', 'bg-emerald-500'],
    amber: ['text-amber-700', 'bg-amber-500'],
    sky: ['text-sky-700', 'bg-sky-500'],
  }
  const [textCls, dotCls] = colors[tone]
  const tooltip = data.worker_details.map((w) => `${w.name}: ${w.queues.join(', ')} (${w.state})`).join('\n')
  return (
    <span className={`flex items-center gap-1.5 text-xs ${textCls}`} title={tooltip}>
      <span className={`h-2 w-2 rounded-full ${dotCls}`} />
      {text}
    </span>
  )
}

export function ProjectLayout() {
  const id = useProjectId()
  const { data: project, isLoading, error } = useProject(id)

  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-6">
          <Brand />
          <span className="ml-3 text-slate-300">/</span>
          <Link to="/" className="text-sm text-slate-500 hover:text-brand-700">
            Projects
          </Link>
          <span className="text-slate-300">/</span>
          <h1 className="text-lg font-semibold text-ink">{isLoading ? <Spinner /> : project?.name}</h1>
          <div className="ml-auto">
            <WorkerStatus />
          </div>
        </div>
        <nav className="mx-auto flex max-w-7xl gap-1 px-6">
          {tabs.map(([path, label]) => (
            <NavLink
              key={path}
              to={path}
              end
              className={({ isActive }) =>
                `border-b-2 px-3 py-2.5 text-sm font-medium ${
                  isActive
                    ? 'border-brand-500 text-brand-700'
                    : 'border-transparent text-slate-500 hover:text-ink'
                }`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 p-6">
        <ErrorText error={error} />
        {project && <Outlet />}
      </main>
    </div>
  )
}
