import { Link } from 'react-router-dom'

import { useJobs, useProjectStats } from '../../api/hooks'
import type { ImageStatus } from '../../api/types'
import { JobStatusBadge } from '../../components/StatusBadge'
import { IMAGE_STATUS_LABELS } from '../../lib/labels'
import { EmptyState, ErrorText, Spinner } from '../../components/ui'
import { useProjectId } from '../../lib/route'

function Stat({ label, value, to }: { label: string; value: number; to?: string }) {
  const body = (
    <>
      <p className="text-sm text-slate-500">{label}</p>
      <p className="text-2xl font-semibold">{value}</p>
    </>
  )
  const cls = 'block rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200'
  return to ? (
    <Link to={to} className={`${cls} hover:ring-indigo-300`}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  )
}

export function OverviewTab() {
  const id = useProjectId()
  const { data: stats, isLoading, error } = useProjectStats(id)
  const { data: jobs } = useJobs(id)

  if (isLoading) return <Spinner />
  if (!stats) return <ErrorText error={error} />
  if (stats.total_images === 0)
    return (
      <EmptyState title="Project masih kosong">
        Tambahkan <Link to="classes" className="text-indigo-600">class</Link> lalu{' '}
        <Link to="upload" className="text-indigo-600">upload gambar</Link>.
      </EmptyState>
    )

  const maxClass = Math.max(1, ...stats.annotations_by_class.map((c) => c.annotations))
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="Total gambar" value={stats.total_images} to="gallery" />
        {(Object.keys(IMAGE_STATUS_LABELS) as ImageStatus[]).map((s) => (
          <Stat key={s} label={IMAGE_STATUS_LABELS[s]} value={stats.images_by_status[s]} to={`gallery?status=${s}`} />
        ))}
        <Stat label="Box belum di-approve" value={stats.unapproved_annotations} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
          <h2 className="mb-3 font-semibold">Anotasi per class</h2>
          {stats.annotations_by_class.map((c) => (
            <div key={c.class_id} className="mb-2 flex items-center gap-3 text-sm">
              <span className="w-28 truncate">{c.name}</span>
              <div className="h-3 flex-1 rounded bg-slate-100">
                <div
                  className="h-3 rounded"
                  style={{ width: `${(c.annotations / maxClass) * 100}%`, background: c.color }}
                />
              </div>
              <span className="w-12 text-right tabular-nums">{c.annotations}</span>
            </div>
          ))}
          <h3 className="mt-4 mb-2 text-sm font-semibold text-slate-600">Per sumber</h3>
          <ul className="text-sm text-slate-600">
            {Object.entries(stats.annotations_by_source).map(([src, n]) => (
              <li key={src} className="flex justify-between">
                <code>{src}</code>
                <span className="tabular-nums">{n}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
          <h2 className="mb-3 font-semibold">Job terakhir</h2>
          {!jobs?.length && <p className="text-sm text-slate-500">Belum ada job auto-label.</p>}
          <ul className="space-y-2 text-sm">
            {jobs?.slice(0, 5).map((j) => (
              <li key={j.id} className="flex items-center gap-2">
                <JobStatusBadge status={j.status} />
                <span>
                  #{j.id} {j.provider}/{j.mode}
                </span>
                <span className="ml-auto tabular-nums text-slate-500">
                  {j.processed}/{j.total}
                </span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  )
}
