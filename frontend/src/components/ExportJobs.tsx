import type { Job } from '../api/types'
import { JobProgress } from './JobProgress'

interface ExportResult {
  filename?: string
  size_bytes?: number
  images?: number
  expired?: boolean
}

const fmtSize = (bytes: number) =>
  bytes >= 1e9 ? `${(bytes / 1e9).toFixed(2)} GB` : bytes >= 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.ceil(bytes / 1e3)} KB`

/** Daftar job export dengan link unduh. File disimpan 7 hari sejak selesai. */
export function ExportJobs({ jobs, limit = 5 }: { jobs: Job[]; limit?: number }) {
  if (jobs.length === 0) return null
  return (
    <div className="space-y-2">
      {jobs.slice(0, limit).map((job) => {
        const r = (job.result ?? {}) as ExportResult
        const format = String(job.payload?.format ?? '').toUpperCase()
        return (
          <JobProgress key={job.id} job={job} title={`Export ${format}`}>
            {job.status === 'completed' && r.filename && (
              <p className="mt-1 flex flex-wrap items-center gap-2">
                {r.expired ? (
                  <span className="text-slate-500">File sudah dihapus (lebih dari 7 hari)</span>
                ) : (
                  <a href={`/api/exports/${job.id}/download`} download={r.filename} className="font-medium text-brand-700 hover:underline">
                    ⬇ {r.filename}
                  </a>
                )}
                <span className="text-xs text-slate-500">
                  {r.images} gambar{r.size_bytes ? ` · ${fmtSize(r.size_bytes)}` : ''}
                </span>
              </p>
            )}
          </JobProgress>
        )
      })}
    </div>
  )
}
