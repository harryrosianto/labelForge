import { useCancelJob } from '../api/hooks'
import type { Job } from '../api/types'
import { JobStatusBadge } from './StatusBadge'
import { Button } from './ui'

const RESULT_LABELS: Record<string, string> = {
  frames_added: 'frame masuk',
  skipped_similar: 'mirip dilewati',
  duplicates: 'duplikat',
  reconnects: 'sambung ulang',
}

/** Baris status job: badge, progress, ringkasan hasil, peringatan, error, tombol batal. */
export function JobProgress({ job, title }: { job: Job; title?: string }) {
  const cancel = useCancelJob(job.project_id)
  const active = job.status === 'queued' || job.status === 'running'
  const result = (job.result ?? {}) as Record<string, number>
  const summary = Object.entries(RESULT_LABELS)
    .filter(([k]) => typeof result[k] === 'number' && (result[k] > 0 || k === 'frames_added'))
    .map(([k, label]) => `${result[k]} ${label}`)

  return (
    <div className="rounded-md bg-white p-3 text-sm ring-1 ring-slate-200">
      <div className="flex flex-wrap items-center gap-2">
        <JobStatusBadge status={job.status} />
        <span className="font-medium">{title ?? `#${job.id}`}</span>
        <span className="text-xs text-slate-500">{new Date(job.created_at).toLocaleString('id-ID')}</span>
        <span className="ml-auto tabular-nums text-slate-600">
          {job.processed}
          {job.total ? `/${job.total}` : ''}
        </span>
        {active && (
          <Button variant="ghost" disabled={job.cancel_requested || cancel.isPending} onClick={() => cancel.mutate(job.id)}>
            {job.cancel_requested ? 'Menghentikan…' : 'Hentikan'}
          </Button>
        )}
      </div>
      {active && (
        <div className="mt-2 h-2 rounded bg-slate-100">
          <div className="h-2 rounded bg-brand-500 transition-all" style={{ width: `${job.progress * 100}%` }} />
        </div>
      )}
      {summary.length > 0 && <p className="mt-1 text-slate-600">{summary.join(' · ')}</p>}
      {job.warnings.slice(-3).map((w, i) => (
        <p key={i} className="mt-1 text-xs text-amber-700">
          ⚠ {w}
        </p>
      ))}
      {job.error && <p className="mt-1 text-rose-600">{job.error}</p>}
    </div>
  )
}
