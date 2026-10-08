import { useState } from 'react'

import {
  useAugmentPreview,
  useClasses,
  useCompareVersions,
  useCreateVersion,
  useDeleteVersion,
  useJobs,
  useUpdateVersion,
  useVersionPreview,
  useVersions,
  useVersionStats,
} from '../../api/hooks'
import type { AugmentationConfig, DatasetVersion, Preprocessing, VersionSettings, VersionSummary } from '../../api/types'
import { AugmentationSettings } from '../../components/AugmentationSettings'
import { DEFAULT_AUGMENTATION, describeAugmentation } from '../../lib/augmentation'
import { DatasetStats } from '../../components/DatasetStats'
import { Button, EmptyState, ErrorText, Field, inputClass, Spinner } from '../../components/ui'
import { downloadPost } from '../../lib/download'
import { useProjectId } from '../../lib/route'

const STATUS: Record<DatasetVersion['status'], [string, string]> = {
  building: ['Diproses', 'bg-brand-100 text-brand-800'],
  ready: ['Siap', 'bg-emerald-100 text-emerald-800'],
  failed: ['Gagal', 'bg-rose-100 text-rose-700'],
}

function StatusBadge({ status }: { status: DatasetVersion['status'] }) {
  const [label, cls] = STATUS[status]
  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${cls}`}>{label}</span>
}

function describePreprocessing(p: Preprocessing) {
  if (p.resize === 'none') return 'Ukuran asli'
  return `${p.resize === 'fit' ? 'Fit + padding' : 'Stretch'} ${p.width}×${p.height}`
}

function SplitBoxes({ splits }: { splits: VersionSummary['splits'] }) {
  return (
    <div className="grid grid-cols-3 gap-2">
      {(['train', 'val', 'test'] as const).map((s) => (
        <div key={s} className="rounded-md bg-slate-50 p-2 text-center ring-1 ring-slate-200">
          <p className="text-xs uppercase text-slate-500">{s}</p>
          <p className="text-lg font-semibold text-ink">{splits[s]}</p>
        </div>
      ))}
    </div>
  )
}

function ClassTable({ summary }: { summary: VersionSummary }) {
  const max = Math.max(1, ...summary.per_class.map((c) => c.boxes))
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs uppercase text-slate-500">
          <th className="py-1 font-medium">Class</th>
          <th className="py-1 text-right font-medium">Gambar</th>
          <th className="py-1 text-right font-medium">Box</th>
          <th className="w-1/3 py-1" />
        </tr>
      </thead>
      <tbody>
        {summary.per_class.map((c) => (
          <tr key={c.name} className="border-t border-slate-100">
            <td className="py-1">{c.name}</td>
            <td className="py-1 text-right tabular-nums">{c.images}</td>
            <td className={`py-1 text-right tabular-nums ${c.boxes === 0 ? 'text-amber-700' : ''}`}>{c.boxes}</td>
            <td className="py-1 pl-3">
              <div className="h-2 rounded bg-slate-100">
                <div className="h-2 rounded bg-brand-500" style={{ width: `${(c.boxes / max) * 100}%` }} />
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function CreateVersionForm({ onCreated, onCancel }: { onCreated: (v: DatasetVersion) => void; onCancel: () => void }) {
  const projectId = useProjectId()
  const create = useCreateVersion(projectId)
  const [name, setName] = useState('')
  const [notes, setNotes] = useState('')
  const [reviewedOnly, setReviewedOnly] = useState(true)
  const [split, setSplit] = useState({ train: 80, val: 20, test: 0 })
  const [seed, setSeed] = useState(42)
  const [prep, setPrep] = useState<Preprocessing>({ resize: 'none', width: 640, height: 640 })
  const [aug, setAug] = useState<AugmentationConfig>(DEFAULT_AUGMENTATION)
  const augPreview = useAugmentPreview(projectId)
  const { data: classes = [] } = useClasses(projectId)

  const validSplit = split.train > 0
  const settings: VersionSettings = {
    reviewed_only: reviewedOnly,
    split: { train: split.train / 100, val: split.val / 100, test: split.test / 100 },
    seed,
    preprocessing: prep.resize === 'none' ? { resize: 'none' } : prep,
    augmentation: aug,
  }
  const preview = useVersionPreview(projectId, settings, validSplit)

  return (
    <form
      className="space-y-5 rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200"
      onSubmit={(e) => {
        e.preventDefault()
        create.mutate({ ...settings, name, notes: notes.trim() || null }, { onSuccess: onCreated })
      }}
    >
      <h2 className="font-semibold">Buat versi dataset</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Nama versi">
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} placeholder="mis. v1-baseline" required />
        </Field>
        <Field label="Catatan (opsional)">
          <input className={inputClass} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
      </div>

      <fieldset className="space-y-1 text-sm">
        <legend className="mb-1 font-medium text-slate-700">Gambar</legend>
        <label className="flex items-center gap-2">
          <input type="radio" className="accent-brand-600" checked={reviewedOnly} onChange={() => setReviewedOnly(true)} />
          Hanya yang sudah reviewed
        </label>
        <label className="flex items-center gap-2">
          <input type="radio" className="accent-brand-600" checked={!reviewedOnly} onChange={() => setReviewedOnly(false)} />
          Reviewed + auto-label
        </label>
      </fieldset>

      <div className="grid gap-3 sm:grid-cols-4">
        {(['train', 'val', 'test'] as const).map((s) => (
          <Field key={s} label={`${s} (%)`}>
            <input
              type="number"
              min={0}
              max={100}
              className={inputClass}
              value={split[s]}
              onChange={(e) => setSplit({ ...split, [s]: Math.max(0, Number(e.target.value)) })}
            />
          </Field>
        ))}
        <Field label="Seed">
          <input type="number" className={inputClass} value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
        </Field>
      </div>
      {!validSplit && <p className="text-xs text-rose-600">Split train harus lebih dari 0.</p>}

      <fieldset className="space-y-2">
        <legend className="mb-1 text-sm font-medium text-slate-700">Preprocessing</legend>
        <div className="flex flex-wrap items-end gap-3">
          <select
            className={`${inputClass} w-auto`}
            value={prep.resize}
            onChange={(e) => setPrep({ ...prep, resize: e.target.value as Preprocessing['resize'] })}
          >
            <option value="none">Ukuran asli</option>
            <option value="fit">Resize fit + padding (letterbox)</option>
            <option value="stretch">Resize stretch</option>
          </select>
          {prep.resize !== 'none' && (
            <>
              <input type="number" min={32} className={`${inputClass} w-24`} value={prep.width ?? 640}
                onChange={(e) => setPrep({ ...prep, width: Number(e.target.value) })} aria-label="Lebar" />
              <span className="pb-1.5 text-slate-500">×</span>
              <input type="number" min={32} className={`${inputClass} w-24`} value={prep.height ?? 640}
                onChange={(e) => setPrep({ ...prep, height: Number(e.target.value) })} aria-label="Tinggi" />
              {[640, 1024].map((n) => (
                <Button key={n} variant="ghost" onClick={() => setPrep({ ...prep, width: n, height: n })}>
                  {n}
                </Button>
              ))}
            </>
          )}
        </div>
        {prep.resize !== 'none' && (
          <p className="text-xs text-slate-500">Gambar hasil resize dibuat oleh worker; versi siap setelah job selesai.</p>
        )}
      </fieldset>

      <AugmentationSettings
        value={aug}
        onChange={setAug}
        classes={classes}
        preview={augPreview.data}
        previewing={augPreview.isPending}
        previewError={augPreview.error}
        onPreview={() => augPreview.mutate({ ...settings, count: 6 })}
      />

      <section className="space-y-3 rounded-md bg-slate-50 p-3 ring-1 ring-slate-200">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          Pratinjau isi versi {preview.isFetching && <Spinner className="text-slate-400" />}
        </h3>
        {preview.data && preview.data.images === 0 && (
          <p className="text-sm text-amber-700">Belum ada gambar {reviewedOnly ? 'yang reviewed' : 'berlabel'}.</p>
        )}
        {preview.data && preview.data.images > 0 && (
          <>
            <SplitBoxes splits={preview.data.splits} />
            <p className="text-sm text-slate-600">
              {preview.data.images} gambar · {preview.data.annotations} box
              {preview.data.empty_images > 0 && ` · ${preview.data.empty_images} tanpa objek`}
              {preview.data.augmented > 0 && ` · +${preview.data.augmented} gambar augmentasi di train`}
            </p>
            <ClassTable summary={preview.data} />
          </>
        )}
        <ErrorText error={preview.error} />
      </section>

      <ErrorText error={create.error} />
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={create.isPending || !validSplit || !name.trim() || !preview.data?.images}>
          {create.isPending && <Spinner />} Buat versi
        </Button>
        <Button onClick={onCancel}>Batal</Button>
      </div>
    </form>
  )
}

function VersionDetail({ version, onDeleted }: { version: DatasetVersion; onDeleted: () => void }) {
  const projectId = useProjectId()
  const update = useUpdateVersion(projectId)
  const remove = useDeleteVersion(projectId)
  const { data: jobs = [] } = useJobs(projectId)
  const job = version.job_id ? jobs.find((j) => j.id === version.job_id) : undefined
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  const cfg = version.config

  const download = async (format: 'yolo' | 'coco') => {
    setBusy(format)
    setError(null)
    try {
      await downloadPost(`/versions/${version.id}/export`, { format })
    } catch (e) {
      setError(e)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-4 rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <div className="flex flex-wrap items-start gap-2">
        <div className="mr-auto">
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            {version.name} <StatusBadge status={version.status} />
          </h2>
          <p className="text-xs text-slate-500">Dibuat {new Date(version.created_at).toLocaleString('id-ID')}</p>
        </div>
        <Button
          variant="ghost"
          onClick={() => {
            const name = prompt('Nama versi', version.name)
            if (name?.trim()) update.mutate({ id: version.id, name })
          }}
        >
          Ganti nama
        </Button>
        <Button
          variant="ghost"
          className="text-rose-600"
          disabled={version.status === 'building'}
          onClick={() => confirm(`Hapus versi "${version.name}"? Gambar project tidak ikut terhapus.`) && remove.mutate(version.id, { onSuccess: onDeleted })}
        >
          Hapus
        </Button>
      </div>

      <textarea
        className={inputClass}
        rows={2}
        defaultValue={version.notes ?? ''}
        placeholder="Catatan versi"
        onBlur={(e) => e.target.value !== (version.notes ?? '') && update.mutate({ id: version.id, notes: e.target.value || null })}
      />

      {version.status === 'building' && job && (
        <div>
          <p className="mb-1 text-sm text-slate-600">
            Membuat file versi {job.processed}/{job.total}
          </p>
          <div className="h-2 rounded bg-slate-100">
            <div className="h-2 rounded bg-brand-500 transition-all" style={{ width: `${job.progress * 100}%` }} />
          </div>
        </div>
      )}
      {version.status === 'failed' && <p className="text-sm text-rose-600">{job?.error ?? 'Sebagian file versi gagal dibuat.'}</p>}

      {version.summary && (
        <>
          <SplitBoxes splits={version.summary.splits} />
          <ClassTable summary={version.summary} />
        </>
      )}

      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-slate-500">Gambar</dt>
        <dd>{cfg.reviewed_only ? 'Hanya reviewed' : 'Reviewed + auto-label'}</dd>
        <dt className="text-slate-500">Split</dt>
        <dd>
          {Math.round(cfg.split.train * 100)} / {Math.round(cfg.split.val * 100)} / {Math.round(cfg.split.test * 100)} (seed {cfg.seed})
        </dd>
        <dt className="text-slate-500">Preprocessing</dt>
        <dd>{describePreprocessing(cfg.preprocessing)}</dd>
        <dt className="text-slate-500">Augmentasi</dt>
        <dd>{describeAugmentation(cfg.augmentation)}</dd>
        <dt className="text-slate-500">Class</dt>
        <dd>{cfg.classes.map((c) => c.name).join(', ')}</dd>
      </dl>

      {version.status === 'ready' && <VersionStatsPanel versionId={version.id} />}

      <ErrorText error={error ?? update.error ?? remove.error} />
      <div className="flex gap-2 border-t border-slate-100 pt-3">
        {(['yolo', 'coco'] as const).map((f) => (
          <Button key={f} variant={f === 'yolo' ? 'primary' : 'secondary'} disabled={version.status !== 'ready' || busy !== null} onClick={() => download(f)}>
            {busy === f && <Spinner />} Download {f.toUpperCase()}
          </Button>
        ))}
      </div>
    </div>
  )
}

function VersionStatsPanel({ versionId }: { versionId: number }) {
  const [open, setOpen] = useState(false)
  const { data, isLoading, error } = useVersionStats(versionId, open)
  return (
    <details className="rounded-md ring-1 ring-slate-200" onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary className="cursor-pointer px-3 py-2 text-sm font-medium">Statistik versi</summary>
      <div className="border-t border-slate-100 bg-slate-50 p-3">
        {isLoading && <Spinner />}
        <ErrorText error={error} />
        {data && <DatasetStats stats={data} />}
      </div>
    </details>
  )
}

function CompareView({ a, b, onClose }: { a: number; b: number; onClose: () => void }) {
  const { data, error, isLoading } = useCompareVersions(a, b)
  return (
    <div className="space-y-4 rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <div className="flex items-center">
        <h2 className="mr-auto font-semibold">
          Perbandingan {data ? `${data.a.name} → ${data.b.name}` : ''}
        </h2>
        <Button variant="ghost" onClick={onClose}>
          Tutup
        </Button>
      </div>
      {isLoading && <Spinner />}
      <ErrorText error={error} />
      {data && (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            {[
              ['Hanya di ' + data.a.name, data.images_only_in_a],
              ['Hanya di ' + data.b.name, data.images_only_in_b],
              ['Ada di keduanya', data.images_in_both],
              ['Label berubah', data.labels_changed],
              ['Pindah split', data.split_changed],
            ].map(([label, value]) => (
              <div key={label} className="rounded-md bg-slate-50 p-2 ring-1 ring-slate-200">
                <p className="truncate text-xs text-slate-500">{label}</p>
                <p className="text-lg font-semibold text-ink">{value}</p>
              </div>
            ))}
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500">
                <th className="py-1 font-medium">Class</th>
                <th className="py-1 text-right font-medium">{data.a.name}</th>
                <th className="py-1 text-right font-medium">{data.b.name}</th>
                <th className="py-1 text-right font-medium">Selisih</th>
              </tr>
            </thead>
            <tbody>
              {data.per_class.map((c) => (
                <tr key={c.name} className="border-t border-slate-100">
                  <td className="py-1">{c.name}</td>
                  <td className="py-1 text-right tabular-nums">{c.a}</td>
                  <td className="py-1 text-right tabular-nums">{c.b}</td>
                  <td className={`py-1 text-right tabular-nums ${c.b - c.a > 0 ? 'text-emerald-700' : c.b - c.a < 0 ? 'text-rose-600' : 'text-slate-400'}`}>
                    {c.b - c.a > 0 ? '+' : ''}
                    {c.b - c.a}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {Object.keys(data.settings_changed).length > 0 && (
            <div className="text-sm">
              <h3 className="mb-1 font-medium">Pengaturan yang berbeda</h3>
              <ul className="space-y-0.5 font-mono text-xs text-slate-600">
                {Object.entries(data.settings_changed).map(([k, v]) => (
                  <li key={k}>
                    {k}: {JSON.stringify(v.a)} → {JSON.stringify(v.b)}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  )
}

export function VersionsTab() {
  const projectId = useProjectId()
  const { data: versions = [], isLoading } = useVersions(projectId)
  const [creating, setCreating] = useState(false)
  const [selected, setSelected] = useState<number | null>(null)
  const [compare, setCompare] = useState<number[]>([])
  const [showCompare, setShowCompare] = useState(false)

  const current = versions.find((v) => v.id === selected) ?? (!creating ? versions[0] : undefined)
  const toggleCompare = (id: number) =>
    setCompare((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id].slice(-2)))

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,20rem)_1fr]">
      <aside className="space-y-3">
        <Button variant="primary" className="w-full" onClick={() => (setCreating(true), setShowCompare(false))}>
          + Buat versi
        </Button>
        {compare.length === 2 && (
          <Button className="w-full" onClick={() => (setShowCompare(true), setCreating(false))}>
            Bandingkan 2 versi terpilih
          </Button>
        )}
        {isLoading && <Spinner />}
        {!isLoading && versions.length === 0 && !creating && (
          <EmptyState title="Belum ada versi">Versi menyimpan snapshot dataset yang tidak berubah untuk training.</EmptyState>
        )}
        <ul className="space-y-2">
          {versions.map((v) => (
            <li key={v.id}>
              <div
                className={`flex gap-2 rounded-lg bg-white p-3 shadow-sm ring-1 ${
                  current?.id === v.id && !creating && !showCompare ? 'ring-brand-500' : 'ring-slate-200'
                }`}
              >
                <input
                  type="checkbox"
                  className="mt-1 accent-brand-600"
                  checked={compare.includes(v.id)}
                  onChange={() => toggleCompare(v.id)}
                  aria-label={`Pilih ${v.name} untuk dibandingkan`}
                />
                <button
                  type="button"
                  className="min-w-0 flex-1 text-left"
                  onClick={() => (setSelected(v.id), setCreating(false), setShowCompare(false))}
                >
                  <span className="flex items-center gap-2">
                    <span className="truncate font-medium">{v.name}</span>
                    <StatusBadge status={v.status} />
                  </span>
                  <span className="block text-xs text-slate-500">
                    {v.image_count} gambar · {describePreprocessing(v.config.preprocessing)}
                    {v.config.augmentation?.enabled && ` · augmentasi ${v.config.augmentation.multiplier}×`}
                  </span>
                </button>
              </div>
            </li>
          ))}
        </ul>
      </aside>

      <div>
        {creating ? (
          <CreateVersionForm onCreated={(v) => (setCreating(false), setSelected(v.id))} onCancel={() => setCreating(false)} />
        ) : showCompare && compare.length === 2 ? (
          <CompareView a={compare[0]} b={compare[1]} onClose={() => setShowCompare(false)} />
        ) : current ? (
          <VersionDetail key={current.id} version={current} onDeleted={() => setSelected(null)} />
        ) : null}
      </div>
    </div>
  )
}
