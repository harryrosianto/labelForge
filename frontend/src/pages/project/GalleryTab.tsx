import { useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { useClasses, useDeleteImages, useImages } from '../../api/hooks'
import type { Audit } from '../../api/types'
import { ImageThumb } from '../../components/ImageThumb'
import { AuditBanner, AuditPanel, BulkStatusButtons } from '../../components/ReviewTools'
import { IMAGE_SOURCE_LABELS, IMAGE_STATUS_LABELS } from '../../lib/labels'
import { Button, EmptyState, ErrorText, inputClass, Spinner } from '../../components/ui'
import { filtersFromParams, useProjectId } from '../../lib/route'

const PAGE_SIZE = 60
const SOURCES: [string, string][] = [
  ['', 'Semua sumber anotasi'],
  ['manual', 'Manual'],
  ['ai', 'AI (semua)'],
  ['ai:owlv2_text', 'AI: OWLv2 teks'],
  ['ai:owlv2_image', 'AI: OWLv2 contoh visual'],
  ['ai:grounding_dino', 'AI: Grounding DINO'],
  ['import:yolo', 'Import YOLO'],
  ['import:coco', 'Import COCO'],
]

export function GalleryTab() {
  const id = useProjectId()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const filters = filtersFromParams(params)
  const page = Number(params.get('page') ?? 1)
  const { data, isLoading, isFetching, error } = useImages(id, filters, page, PAGE_SIZE)
  const { data: classes } = useClasses(id)
  const remove = useDeleteImages(id)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [auditOpen, setAuditOpen] = useState(false)

  const classMap = useMemo(() => new Map(classes?.map((c) => [c.id, c])), [classes])
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    if (key !== 'page') next.delete('page')
    setParams(next)
    setSelected(new Set())
  }

  const replaceParams = (values: Record<string, string | number | undefined>) => {
    const next = new URLSearchParams()
    for (const [k, v] of Object.entries(values)) if (v !== undefined && v !== '') next.set(k, String(v))
    setParams(next)
    setSelected(new Set())
  }

  const openEditor = (imageId: number) => {
    const q = new URLSearchParams(params)
    q.delete('page')
    navigate(`/projects/${id}/annotate/${imageId}${q.size ? `?${q}` : ''}`)
  }

  const openAudit = (audit: Audit) => {
    setAuditOpen(false)
    replaceParams({ audit_id: audit.id })
  }

  const toggle = (imageId: number) =>
    setSelected((s) => {
      const next = new Set(s)
      if (!next.delete(imageId)) next.add(imageId)
      return next
    })

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <select className={`${inputClass} w-auto`} value={filters.status ?? ''} onChange={(e) => setParam('status', e.target.value)}>
          <option value="">Semua status</option>
          {Object.entries(IMAGE_STATUS_LABELS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <select
          className={`${inputClass} w-auto`}
          value={filters.class_id ?? ''}
          onChange={(e) => setParam('class_id', e.target.value)}
        >
          <option value="">Semua class</option>
          {classes?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <select
          className={`${inputClass} w-auto`}
          value={filters.source_type ?? ''}
          onChange={(e) => setParam('source_type', e.target.value)}
          aria-label="Asal gambar"
        >
          <option value="">Semua asal gambar</option>
          {Object.entries(IMAGE_SOURCE_LABELS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <select className={`${inputClass} w-auto`} value={filters.source ?? ''} onChange={(e) => setParam('source', e.target.value)}>
          {SOURCES.map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input
            type="checkbox"
            checked={filters.max_conf !== undefined}
            onChange={(e) => setParam('max_conf', e.target.checked ? '0.3' : '')}
          />
          Confidence rendah &lt;
        </label>
        {filters.max_conf !== undefined && (
          <input
            type="number"
            min={0}
            max={1}
            step={0.05}
            className={`${inputClass} w-20`}
            value={filters.max_conf}
            onChange={(e) => setParam('max_conf', e.target.value)}
          />
        )}
        {isFetching && <Spinner className="text-slate-400" />}
        <span className="ml-auto text-sm text-slate-500">{data?.total ?? 0} gambar</span>
      </div>

      {filters.audit_id !== undefined && (
        <AuditBanner
          projectId={id}
          auditId={filters.audit_id}
          onReview={() => {
            const first = data?.items.find((i) => i.status !== 'reviewed') ?? data?.items[0]
            if (first) openEditor(first.id)
          }}
          onShowPopulation={(audit) => replaceParams({ ...audit.filters, status: 'auto_labeled' })}
          onExit={() => setParam('audit_id', '')}
        />
      )}
      {auditOpen && <AuditPanel projectId={id} filters={filters} onOpen={openAudit} />}

      {selected.size > 0 && (
        <div className="flex items-center gap-2 rounded-md bg-brand-50 px-3 py-2 text-sm">
          <span className="font-medium text-brand-800">{selected.size} dipilih</span>
          <Button
            variant="primary"
            onClick={() => navigate('../autolabel', { relative: 'path', state: { imageIds: [...selected] } })}
          >
            Auto-label terpilih
          </Button>
          <BulkStatusButtons projectId={id} filters={{}} imageIds={[...selected]} onDone={() => setSelected(new Set())} />
          <Button
            variant="danger"
            disabled={remove.isPending}
            onClick={() => {
              if (confirm(`Hapus ${selected.size} gambar beserta labelnya?`))
                remove.mutate([...selected], {
                  onSuccess: (r) => {
                    setSelected(new Set())
                    if (r.protected.length)
                      alert(`${r.protected.length} gambar tidak dihapus karena dipakai versi dataset. Hapus versinya dulu bila perlu.`)
                  },
                })
            }}
          >
            Hapus
          </Button>
          <Button variant="ghost" onClick={() => setSelected(new Set())}>
            Batal pilih
          </Button>
        </div>
      )}
      {data && data.items.length > 0 && selected.size === 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="ghost" onClick={() => setSelected(new Set(data.items.map((i) => i.id)))}>
            Pilih semua di halaman ini
          </Button>
          <span className="mx-1 h-5 w-px bg-slate-200" />
          <BulkStatusButtons projectId={id} filters={filters} />
          <Button variant="ghost" className="ml-auto" onClick={() => setAuditOpen((v) => !v)}>
            {auditOpen ? 'Tutup audit' : 'Audit sampel…'}
          </Button>
        </div>
      )}

      <ErrorText error={error ?? remove.error} />
      {isLoading && <Spinner />}
      {data?.items.length === 0 && (
        <EmptyState title="Tidak ada gambar">
          {params.toString() ? (
            'Tidak ada gambar yang cocok dengan filter.'
          ) : (
            <Link to="../upload" relative="path" className="text-brand-700">
              Upload gambar
            </Link>
          )}
        </EmptyState>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6">
        {data?.items.map((img) => (
          <ImageThumb
            key={img.id}
            image={img}
            classes={classMap}
            selected={selected.has(img.id)}
            onToggle={() => toggle(img.id)}
            onOpen={() => openEditor(img.id)}
          />
        ))}
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button disabled={page <= 1} onClick={() => setParam('page', String(page - 1))}>
            ← Sebelumnya
          </Button>
          <span className="text-sm text-slate-600">
            Halaman {page} / {pages}
          </span>
          <Button disabled={page >= pages} onClick={() => setParam('page', String(page + 1))}>
            Berikutnya →
          </Button>
        </div>
      )}
    </div>
  )
}
