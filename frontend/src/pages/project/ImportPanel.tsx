import { useQueryClient } from '@tanstack/react-query'
import { useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { keys, uploadImportZip, useClasses, useDiscardImport, useImports, useJobs, useStartImport } from '../../api/hooks'
import type { ClassMapping, DatasetImport, LabelClass } from '../../api/types'
import { JobStatusBadge } from '../../components/StatusBadge'
import { Button, ErrorText, inputClass, Spinner } from '../../components/ui'
import { useProjectId } from '../../lib/route'

const STATUS_LABEL: Record<DatasetImport['status'], string> = {
  analyzed: 'Siap diimpor',
  importing: 'Sedang diimpor',
  completed: 'Selesai',
  failed: 'Gagal',
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md bg-slate-50 p-3 ring-1 ring-slate-200">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="text-lg font-semibold text-ink">{value}</p>
    </div>
  )
}

function MappingRow({
  name,
  boxes,
  value,
  classes,
  onChange,
}: {
  name: string
  boxes: number
  value: ClassMapping
  classes: LabelClass[]
  onChange: (m: ClassMapping) => void
}) {
  const selectValue = value.action === 'map' ? `map:${value.class_id}` : value.action
  return (
    <tr className="border-t border-slate-100">
      <td className="py-2 pr-3 font-medium">{name}</td>
      <td className="py-2 pr-3 text-right tabular-nums text-slate-600">{boxes}</td>
      <td className="py-2 pr-3">
        <select
          className={inputClass}
          value={selectValue}
          onChange={(e) => {
            const v = e.target.value
            if (v.startsWith('map:')) onChange({ action: 'map', class_id: Number(v.slice(4)) })
            else if (v === 'create') onChange({ action: 'create', name })
            else onChange({ action: 'ignore' })
          }}
        >
          <option value="create">Buat class baru</option>
          {classes.map((c) => (
            <option key={c.id} value={`map:${c.id}`}>
              Gabungkan ke "{c.name}"
            </option>
          ))}
          <option value="ignore">Abaikan (box tidak diimpor)</option>
        </select>
      </td>
      <td className="py-2">
        {value.action === 'create' && (
          <input
            className={inputClass}
            value={value.name ?? ''}
            onChange={(e) => onChange({ action: 'create', name: e.target.value })}
            aria-label={`Nama class baru untuk ${name}`}
          />
        )}
      </td>
    </tr>
  )
}

function AnalysisView({ imp, onDone }: { imp: DatasetImport; onDone: () => void }) {
  const projectId = useProjectId()
  const { data: classes = [] } = useClasses(projectId)
  const start = useStartImport(projectId)
  const discard = useDiscardImport(projectId)
  const a = imp.analysis!
  const [mapping, setMapping] = useState<Record<string, ClassMapping>>(a.suggested_mapping)
  const [markForReview, setMarkForReview] = useState(false)
  const problems = Object.entries(a.problem_counts)
  const invalidCreate = Object.values(mapping).some((m) => m.action === 'create' && !m.name?.trim())

  return (
    <div className="space-y-5 rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-semibold">{imp.original_filename}</h3>
        <span className="rounded bg-brand-100 px-1.5 py-0.5 text-xs font-medium uppercase text-brand-800">{a.format}</span>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Gambar" value={a.images} />
        <Stat label="Gambar berobjek" value={a.images_with_boxes} />
        <Stat label="Box" value={a.boxes} />
        <Stat label="Split" value={Object.entries(a.splits).map(([k, v]) => `${k} ${v}`).join(' · ')} />
      </div>

      {problems.length > 0 && (
        <details className="rounded-md bg-amber-50 p-3 text-sm ring-1 ring-amber-200">
          <summary className="cursor-pointer font-medium text-amber-800">
            {problems.reduce((n, [, v]) => n + v.count, 0)} catatan pada dataset
          </summary>
          <ul className="mt-2 space-y-0.5 text-amber-900">
            {problems.map(([kind, v]) => (
              <li key={kind}>
                {v.label}: <b>{v.count}</b>
              </li>
            ))}
          </ul>
          <ul className="mt-2 max-h-40 overflow-auto font-mono text-xs text-slate-600">
            {a.problems.map((p, i) => (
              <li key={i}>
                {p.path}
                {p.detail && `: ${p.detail}`}
              </li>
            ))}
          </ul>
        </details>
      )}

      <div>
        <h4 className="mb-1 text-sm font-semibold">Pemetaan class</h4>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase text-slate-500">
              <th className="py-1 font-medium">Class di dataset</th>
              <th className="py-1 text-right font-medium">Box</th>
              <th className="py-1 font-medium">Tujuan</th>
              <th className="py-1 font-medium">Nama class baru</th>
            </tr>
          </thead>
          <tbody>
            {a.classes.map((c) => (
              <MappingRow
                key={c.name}
                name={c.name}
                boxes={c.boxes}
                value={mapping[c.name]}
                classes={classes}
                onChange={(m) => setMapping({ ...mapping, [c.name]: m })}
              />
            ))}
          </tbody>
        </table>
      </div>

      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-0.5 accent-brand-600" checked={markForReview} onChange={(e) => setMarkForReview(e.target.checked)} />
        <span>
          Tandai untuk direview
          <span className="block text-xs text-slate-500">
            Gambar masuk sebagai auto-label dengan box belum di-approve. Tanpa opsi ini, label dataset dianggap sudah benar
            (reviewed).
          </span>
        </span>
      </label>

      <ErrorText error={start.error ?? discard.error} />
      <div className="flex gap-2">
        <Button
          variant="primary"
          disabled={start.isPending || invalidCreate}
          onClick={() => start.mutate({ id: imp.id, mapping, markForReview }, { onSuccess: onDone })}
        >
          {start.isPending && <Spinner />} Mulai import
        </Button>
        <Button disabled={discard.isPending} onClick={() => discard.mutate(imp.id, { onSuccess: onDone })}>
          Buang
        </Button>
      </div>
    </div>
  )
}

export function ImportPanel() {
  const projectId = useProjectId()
  const qc = useQueryClient()
  const { data: imports = [] } = useImports(projectId)
  const { data: jobs = [] } = useJobs(projectId)
  const input = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState<number | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [dragging, setDragging] = useState(false)

  const jobById = useMemo(() => new Map(jobs.map((j) => [j.id, j])), [jobs])
  const pending = imports.find((i) => i.status === 'analyzed')
  const refresh = () => qc.invalidateQueries({ queryKey: keys.project(projectId) })

  async function upload(file: File | undefined) {
    if (!file) return
    setError(null)
    setUploading(0)
    try {
      await uploadImportZip(projectId, file, setUploading)
      refresh()
    } catch (e) {
      setError(e)
    } finally {
      setUploading(null)
    }
  }

  return (
    <div className="space-y-4">
      {!pending && (
        <div
          onDragOver={(e) => (e.preventDefault(), setDragging(true))}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            upload(e.dataTransfer.files[0])
          }}
          className={`flex flex-col items-center rounded-lg border-2 border-dashed p-10 text-center ${
            dragging ? 'border-brand-500 bg-brand-50' : 'border-slate-300 bg-white'
          }`}
        >
          <p className="text-lg font-medium">Import dataset YOLO atau COCO</p>
          <p className="mt-1 text-sm text-slate-500">
            ZIP berisi gambar + label (labels/*.txt dan data.yaml, atau JSON COCO). Isinya dianalisis dulu sebelum masuk ke project.
          </p>
          {uploading !== null ? (
            <div className="mt-4 w-64">
              <div className="mb-1 flex items-center justify-center gap-2 text-sm">
                <Spinner /> {uploading < 1 ? `Mengunggah ${Math.round(uploading * 100)}%` : 'Menganalisis…'}
              </div>
              <div className="h-2 rounded bg-slate-100">
                <div className="h-2 rounded bg-brand-500" style={{ width: `${uploading * 100}%` }} />
              </div>
            </div>
          ) : (
            <Button variant="primary" className="mt-4" onClick={() => input.current?.click()}>
              Pilih ZIP
            </Button>
          )}
          <input
            ref={input}
            type="file"
            accept=".zip"
            hidden
            onChange={(e) => {
              upload(e.target.files?.[0])
              e.target.value = ''
            }}
          />
        </div>
      )}
      <ErrorText error={error} />

      {pending && <AnalysisView key={pending.id} imp={pending} onDone={refresh} />}

      {imports.some((i) => i.status !== 'analyzed') && (
        <section>
          <h3 className="mb-2 text-sm font-semibold">Riwayat import</h3>
          <ul className="space-y-2">
            {imports
              .filter((i) => i.status !== 'analyzed')
              .map((i) => {
                const job = i.job_id ? jobById.get(i.job_id) : undefined
                const result = job?.result as Record<string, number> | null | undefined
                return (
                  <li key={i.id} className="rounded-lg bg-white p-3 text-sm shadow-sm ring-1 ring-slate-200">
                    <div className="flex flex-wrap items-center gap-2">
                      {job ? <JobStatusBadge status={job.status} /> : <span className="text-xs">{STATUS_LABEL[i.status]}</span>}
                      <span className="font-medium">{i.original_filename}</span>
                      <span className="text-slate-500 uppercase">{i.format}</span>
                      {job && (
                        <span className="ml-auto tabular-nums text-slate-600">
                          {job.processed}/{job.total}
                        </span>
                      )}
                    </div>
                    {job && (job.status === 'queued' || job.status === 'running') && (
                      <div className="mt-2 h-2 rounded bg-slate-100">
                        <div className="h-2 rounded bg-brand-500 transition-all" style={{ width: `${job.progress * 100}%` }} />
                      </div>
                    )}
                    {result && (
                      <p className="mt-1 text-slate-600">
                        {result.imported} gambar masuk · {result.boxes} box
                        {result.duplicates > 0 && ` · ${result.duplicates} duplikat dilewati`}
                        {result.boxes_ignored > 0 && ` · ${result.boxes_ignored} box diabaikan`}
                        {result.failed > 0 && ` · ${result.failed} gagal`}
                      </p>
                    )}
                    {(i.error || job?.error) && <p className="mt-1 text-rose-600">{i.error ?? job?.error}</p>}
                    {i.status === 'completed' && (
                      <Link to={`../gallery?source_type=import`} relative="path" className="mt-1 inline-block text-brand-700">
                        Lihat di galeri →
                      </Link>
                    )}
                  </li>
                )
              })}
          </ul>
        </section>
      )}
    </div>
  )
}
