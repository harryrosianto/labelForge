import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useClasses, useDeleteModel, useModels, useUpdateModel, useUploadModel, useVersions } from '../../api/hooks'
import type { LabelClass, MLModelInfo } from '../../api/types'
import { Button, EmptyState, ErrorText, Field, inputClass, Spinner } from '../../components/ui'
import { useProjectId } from '../../lib/route'

const pct = (v?: number) => (v === undefined ? '-' : v.toFixed(3))
const mb = (bytes: number | null) => (bytes ? `${(bytes / 1e6).toFixed(1)} MB` : '')

function UploadForm({ projectId }: { projectId: number }) {
  const upload = useUploadModel(projectId)
  const { data: versions = [] } = useVersions(projectId)
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState('')
  const [versionId, setVersionId] = useState('')
  const [map50, setMap50] = useState('')
  const [map5095, setMap5095] = useState('')
  const [notes, setNotes] = useState('')

  return (
    <form
      className="space-y-4 rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200"
      onSubmit={(e) => {
        e.preventDefault()
        if (!file) return
        const form = new FormData()
        form.append('file', file)
        const fields: [string, string][] = [
          ['name', name.trim()],
          ['dataset_version_id', versionId],
          ['map50', map50],
          ['map50_95', map5095],
          ['notes', notes.trim()],
        ]
        for (const [k, v] of fields) if (v) form.append(k, v)
        upload.mutate(form, {
          onSuccess: () => {
            setFile(null)
            setName('')
            setMap50('')
            setMap5095('')
            setNotes('')
            ;(e.target as HTMLFormElement).reset()
          },
        })
      }}
    >
      <div>
        <h2 className="font-semibold">Upload model</h2>
        <p className="text-sm text-slate-600">
          File <code>best.onnx</code> dari folder <code>runs/…/weights/</code> hasil notebook Colab. Model dijalankan
          di CPU untuk auto-label; class model dipetakan otomatis ke class project dengan nama yang sama.
        </p>
      </div>
      <Field label="File model (.onnx)">
        <input type="file" accept=".onnx" className="text-sm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required />
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Nama">
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} placeholder="mis. yolo11n-v2" />
        </Field>
        <Field label="Dilatih dari versi">
          <select className={inputClass} value={versionId} onChange={(e) => setVersionId(e.target.value)}>
            <option value="">-</option>
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="mAP50 (dari Colab)">
          <input type="number" min={0} max={1} step={0.001} className={inputClass} value={map50} onChange={(e) => setMap50(e.target.value)} />
        </Field>
        <Field label="mAP50-95 (dari Colab)">
          <input type="number" min={0} max={1} step={0.001} className={inputClass} value={map5095} onChange={(e) => setMap5095(e.target.value)} />
        </Field>
      </div>
      <Field label="Catatan">
        <input className={inputClass} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="mis. 100 epoch, imgsz 640" />
      </Field>
      <ErrorText error={upload.error} />
      <Button type="submit" variant="primary" disabled={!file || upload.isPending}>
        {upload.isPending && <Spinner />} Upload
      </Button>
    </form>
  )
}

function ClassMapping({ model, classes, onChange }: { model: MLModelInfo; classes: LabelClass[]; onChange: (map: Record<string, number | null>) => void }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs uppercase text-slate-500">
          <th className="py-1 font-medium">Class model</th>
          <th className="py-1 font-medium">→ Class project</th>
        </tr>
      </thead>
      <tbody>
        {model.names.map((name, i) => {
          const value = model.class_map[String(i)] ?? null
          return (
            <tr key={i} className="border-t border-slate-100">
              <td className="py-1">
                <span className="text-slate-400">{i}</span> {name}
              </td>
              <td className="py-1">
                <select
                  className={`${inputClass} py-1`}
                  value={value ?? ''}
                  onChange={(e) => onChange({ ...model.class_map, [String(i)]: e.target.value ? Number(e.target.value) : null })}
                >
                  <option value="">(abaikan)</option>
                  {classes.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function ModelCard({ model, classes }: { model: MLModelInfo; classes: LabelClass[] }) {
  const projectId = useProjectId()
  const navigate = useNavigate()
  const update = useUpdateModel(projectId)
  const remove = useDeleteModel(projectId)
  const mapped = Object.values(model.class_map).some((v) => v !== null)

  return (
    <div className="space-y-3 rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <div className="flex flex-wrap items-start gap-2">
        <div className="mr-auto">
          <h3 className="font-semibold">{model.name}</h3>
          <p className="text-xs text-slate-500">
            {model.framework.toUpperCase()} · input {model.input_size.join('×')} · {mb(model.size_bytes)} · diupload{' '}
            {new Date(model.created_at).toLocaleDateString('id-ID')}
          </p>
        </div>
        <Button
          variant="primary"
          disabled={!mapped}
          title={mapped ? undefined : 'Petakan minimal satu class dulu'}
          onClick={() => navigate('../autolabel', { relative: 'path', state: { provider: model.provider } })}
        >
          Auto-label dengan model ini
        </Button>
        <Button
          variant="ghost"
          className="text-rose-600"
          onClick={() => confirm(`Hapus model "${model.name}"? Box yang sudah dibuat model ini tetap ada.`) && remove.mutate(model.id)}
        >
          Hapus
        </Button>
      </div>

      <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        {[
          ['mAP50', pct(model.metrics.map50)],
          ['mAP50-95', pct(model.metrics.map50_95)],
          ['Versi dataset', model.dataset_version_name ?? '-'],
          ['Box dibuat', model.annotations.toLocaleString('id-ID')],
        ].map(([k, v]) => (
          <div key={k} className="rounded-md bg-slate-50 p-2 ring-1 ring-slate-200">
            <dt className="text-xs text-slate-500">{k}</dt>
            <dd className="font-semibold text-ink">{v}</dd>
          </div>
        ))}
      </dl>

      <ClassMapping model={model} classes={classes} onChange={(class_map) => update.mutate({ id: model.id, class_map })} />
      {!mapped && <p className="text-xs text-amber-700">Belum ada class model yang dipetakan; model belum bisa dipakai.</p>}

      <input
        className={inputClass}
        defaultValue={model.notes ?? ''}
        placeholder="Catatan"
        onBlur={(e) => e.target.value !== (model.notes ?? '') && update.mutate({ id: model.id, notes: e.target.value || null })}
      />
      <ErrorText error={update.error ?? remove.error} />
    </div>
  )
}

export function ModelsTab() {
  const projectId = useProjectId()
  const { data: models, isLoading, error } = useModels(projectId)
  const { data: classes = [] } = useClasses(projectId)

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,26rem)_1fr]">
      <UploadForm projectId={projectId} />
      <section className="space-y-4">
        {isLoading && <Spinner />}
        <ErrorText error={error} />
        {models?.length === 0 && (
          <EmptyState title="Belum ada model">
            Training di Colab memakai notebook dari detail versi, lalu upload <code>best.onnx</code> di sini.
          </EmptyState>
        )}
        {models?.map((m) => (
          <ModelCard key={m.id} model={m} classes={classes} />
        ))}
      </section>
    </div>
  )
}
