import { useMemo, useState } from 'react'
import { useLocation } from 'react-router-dom'

import {
  useCancelJob,
  useClasses,
  useJobItems,
  useJobs,
  useProviders,
  useStartAutolabel,
} from '../../api/hooks'
import type { Job, JobTarget, ParamSpec, ProviderInfo } from '../../api/types'
import { JobStatusBadge } from '../../components/StatusBadge'
import { Button, ErrorText, Field, inputClass, Spinner } from '../../components/ui'
import { useProjectId } from '../../lib/route'

const MODE_LABELS: Record<string, string> = {
  text: 'Teks (text prompt)',
  image_guided: 'Contoh visual (exemplar)',
  'grounding_dino:text': 'Grounding DINO (teks)',
  'owlv2:text': 'OWLv2 (teks)',
  'owlv2:image_guided': 'OWLv2 (contoh visual)',
}

type Params = Record<string, number | boolean>

function defaults(specs: ParamSpec[]): Params {
  return Object.fromEntries(specs.map((s) => [s.name, s.default]))
}

function ParamInput({ spec, value, onChange }: { spec: ParamSpec; value: number | boolean; onChange: (v: number | boolean) => void }) {
  if (spec.type === 'bool')
    return (
      <label className="flex items-center gap-2 text-sm" title={spec.description}>
        <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        {spec.label || spec.name}
      </label>
    )
  const isSlider = spec.type === 'float' && spec.min !== null && spec.max !== null && spec.max <= 1
  return (
    <Field label={spec.label || spec.name} hint={spec.description || undefined}>
      <div className="flex items-center gap-2">
        {isSlider && (
          <input
            type="range"
            className="flex-1 accent-brand-600"
            min={spec.min ?? 0}
            max={spec.max ?? 1}
            step={spec.step ?? 0.01}
            value={Number(value)}
            onChange={(e) => onChange(Number(e.target.value))}
          />
        )}
        <input
          type="number"
          className={`${inputClass} ${isSlider ? 'w-20' : ''}`}
          min={spec.min ?? undefined}
          max={spec.max ?? undefined}
          step={spec.step ?? (spec.type === 'int' ? 1 : 0.01)}
          value={Number(value)}
          onChange={(e) => onChange(Number(e.target.value))}
        />
      </div>
    </Field>
  )
}

function JobRow({ job }: { job: Job }) {
  const cancel = useCancelJob(job.project_id)
  const [open, setOpen] = useState(false)
  const { data: errors } = useJobItems(job.id, open && job.failed_count > 0)
  const active = job.status === 'queued' || job.status === 'running'
  const pct = Math.round(job.progress * 100)

  return (
    <li className="rounded-lg bg-white p-3 shadow-sm ring-1 ring-slate-200">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <JobStatusBadge status={job.status} />
        <span className="font-medium">#{job.id}</span>
        <span className="text-slate-600">
          {job.provider} / {MODE_LABELS[job.mode ?? ''] ?? job.mode}
        </span>
        <span className="text-slate-400">· target {job.target}</span>
        <span className="ml-auto tabular-nums text-slate-600">
          {job.processed}/{job.total}
          {job.failed_count > 0 && <span className="text-rose-600"> · {job.failed_count} gagal</span>}
        </span>
        {active && (
          <Button variant="ghost" disabled={job.cancel_requested || cancel.isPending} onClick={() => cancel.mutate(job.id)}>
            {job.cancel_requested ? 'Membatalkan…' : 'Batalkan'}
          </Button>
        )}
      </div>
      {(active || job.status === 'cancelled') && (
        <div className="mt-2 h-2 rounded bg-slate-100">
          <div className="h-2 rounded bg-brand-500 transition-all" style={{ width: `${pct}%` }} />
        </div>
      )}
      {job.status === 'queued' && (
        <p className="mt-1 text-xs text-slate-500">Menunggu worker…</p>
      )}
      {job.error && <p className="mt-1 text-sm text-rose-600">{job.error}</p>}
      {job.warnings.map((w) => (
        <p key={w} className="mt-1 text-xs text-amber-700">
          ⚠ {w}
        </p>
      ))}
      {job.failed_count > 0 && (
        <button type="button" className="mt-1 text-xs text-rose-600 underline" onClick={() => setOpen(!open)}>
          {open ? 'Sembunyikan' : 'Lihat'} error per gambar
        </button>
      )}
      {open && (
        <ul className="mt-1 max-h-40 overflow-auto text-xs text-slate-600">
          {errors?.map((e) => (
            <li key={e.id}>
              {e.image_id ? `Gambar #${e.image_id}` : e.label}: {e.error}
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

export function AutolabelTab() {
  const id = useProjectId()
  const location = useLocation()
  const preselected = (location.state as { imageIds?: number[] } | null)?.imageIds ?? []
  const { data: providers } = useProviders()
  const { data: classes } = useClasses(id)
  const { data: jobs } = useJobs(id)
  const start = useStartAutolabel(id)

  const [providerName, setProviderName] = useState<string>()
  const [mode, setMode] = useState<string>()
  // Hanya nilai yang diubah user; sisanya default dari ParamSpec provider/mode aktif.
  const [overrides, setOverrides] = useState<Params>({})
  const [target, setTarget] = useState<JobTarget>(preselected.length ? 'selected' : 'unlabeled')
  const [includeReviewed, setIncludeReviewed] = useState(false)

  const provider: ProviderInfo | undefined = useMemo(
    () => providers?.find((p) => p.name === providerName) ?? providers?.find((p) => p.is_default) ?? providers?.[0],
    [providers, providerName],
  )
  const activeMode = mode && provider?.modes.includes(mode) ? mode : provider?.default_mode
  const specs = useMemo(() => (provider && activeMode ? provider.params[activeMode] ?? [] : []), [provider, activeMode])

  const params: Params = { ...defaults(specs), ...overrides }

  const autolabelJobs = (jobs ?? []).filter((j) => j.job_type === 'autolabel')
  const imageGuided = activeMode?.endsWith('image_guided')
  const withoutExemplar = imageGuided ? (classes ?? []).filter((c) => c.exemplar_count === 0) : []
  const noClasses = classes?.length === 0

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,26rem)_1fr]">
      <form
        className="space-y-4 rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200"
        onSubmit={(e) => {
          e.preventDefault()
          if (!provider || !activeMode) return
          start.mutate({
            provider: provider.name,
            mode: activeMode,
            params,
            target,
            image_ids: target === 'selected' ? preselected : undefined,
            include_reviewed: includeReviewed,
          })
        }}
      >
        <h2 className="font-semibold">Jalankan auto-label</h2>
        <Field label="Model">
          <select
            className={inputClass}
            value={provider?.name ?? ''}
            onChange={(e) => (setProviderName(e.target.value), setMode(undefined), setOverrides({}))}
          >
            {providers?.map((p) => (
              <option key={p.name} value={p.name} disabled={!p.available}>
                {p.label}
                {p.is_default ? ' (default)' : ''}
                {!p.available ? ` (${p.unavailable_reason})` : ''}
              </option>
            ))}
          </select>
        </Field>
        {provider && provider.modes.length > 1 && (
          <Field label="Mode">
            <select className={inputClass} value={activeMode} onChange={(e) => (setMode(e.target.value), setOverrides({}))}>
              {provider.modes.map((m) => (
                <option key={m} value={m}>
                  {MODE_LABELS[m] ?? m}
                </option>
              ))}
            </select>
          </Field>
        )}
        {withoutExemplar.length > 0 && (
          <p className="rounded bg-amber-50 p-2 text-xs text-amber-800">
            Class tanpa contoh visual akan dilewati: {withoutExemplar.map((c) => c.name).join(', ')}. Buat contoh
            visual dari editor anotasi.
          </p>
        )}

        <div className="space-y-3 border-t border-slate-100 pt-3">
          {specs.map((s) => (
            <ParamInput
              key={s.name}
              spec={s}
              value={params[s.name]}
              onChange={(v) => setOverrides((o) => ({ ...o, [s.name]: v }))}
            />
          ))}
        </div>

        <fieldset className="space-y-1 border-t border-slate-100 pt-3 text-sm">
          <legend className="mb-1 font-medium text-slate-700">Gambar yang diproses</legend>
          {(
            [
              ['unlabeled', 'Yang belum berlabel'],
              ['all', 'Semua gambar'],
              ['selected', `Terpilih dari galeri (${preselected.length})`],
            ] as [JobTarget, string][]
          ).map(([value, label]) => (
            <label key={value} className="flex items-center gap-2">
              <input
                type="radio"
                name="target"
                checked={target === value}
                disabled={value === 'selected' && !preselected.length}
                onChange={() => setTarget(value)}
              />
              {label}
            </label>
          ))}
          {target === 'all' && (
            <label className="ml-6 flex items-center gap-2 text-slate-600">
              <input type="checkbox" checked={includeReviewed} onChange={(e) => setIncludeReviewed(e.target.checked)} />
              Termasuk gambar yang sudah reviewed
            </label>
          )}
          <p className="pt-1 text-xs text-slate-500">
            Box AI yang belum di-approve akan diganti; box manual & yang sudah di-approve tidak disentuh.
          </p>
        </fieldset>

        <ErrorText error={start.error} />
        {noClasses && <p className="text-sm text-amber-700">Tambahkan class terlebih dahulu.</p>}
        <Button type="submit" variant="primary" className="w-full" disabled={start.isPending || !provider || noClasses}>
          {start.isPending && <Spinner />} Mulai auto-label
        </Button>
      </form>

      <section>
        <h2 className="mb-3 font-semibold">Riwayat job</h2>
        {!autolabelJobs.length && <p className="text-sm text-slate-500">Belum ada job.</p>}
        <ul className="space-y-2">
          {autolabelJobs.map((j) => (
            <JobRow key={j.id} job={j} />
          ))}
        </ul>
      </section>
    </div>
  )
}
