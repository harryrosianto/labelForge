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

function WorkerStatus() {
  const { data } = useHealth()
  if (!data) return null
  const ok = data.workers.length > 0
  return (
    <span className={`flex items-center gap-1.5 text-xs ${ok ? 'text-emerald-700' : 'text-amber-700'}`}>
      <span className={`h-2 w-2 rounded-full ${ok ? 'bg-emerald-500' : 'bg-amber-500'}`} />
      {ok ? 'Worker aktif' : 'Worker tidak aktif, job auto-label akan menunggu'}
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
