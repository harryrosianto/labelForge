import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useReducer, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { api, imageFileUrl, queryString } from '../api/client'
import { useClasses, useCreateExemplar, useImageDetail, useSaveAnnotations } from '../api/hooks'
import type { ImageDetail, ImageFilters, LabelClass } from '../api/types'
import { ImageStatusBadge } from '../components/StatusBadge'
import { Brand } from '../components/AppHeader'
import { Button, ErrorText, inputClass, Spinner } from '../components/ui'
import { AnnotationCanvas } from '../editor/AnnotationCanvas'
import { initState, matchSaved, reducer, toPayload, keyFor, type EditBox } from '../editor/state'
import { filtersFromParams } from '../lib/route'

const SHORTCUTS: [string, string][] = [
  ['← / →', 'Gambar sebelumnya / berikutnya (otomatis simpan)'],
  ['Drag', 'Gambar box baru dengan class aktif'],
  ['1-9', 'Pilih class (atau ganti class box terpilih)'],
  ['Del', 'Hapus box terpilih'],
  ['Enter', 'Approve semua box & lanjut'],
  ['Ctrl+Z', 'Undo'],
  ['Ctrl+S', 'Simpan'],
  ['Spasi + drag', 'Geser gambar; scroll = zoom'],
  ['Esc', 'Batal pilih'],
]

const isTyping = (t: EventTarget | null) =>
  t instanceof HTMLElement && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName))

function sourceLabel(b: EditBox) {
  if (b.source === 'manual') return 'manual'
  return b.source.replace(/^ai:/, '') + (b.confidence !== null ? ` · ${b.confidence.toFixed(2)}` : '')
}

function Editor({
  detail,
  classes,
  filters,
  projectId,
}: {
  detail: ImageDetail
  classes: LabelClass[]
  filters: ImageFilters
  projectId: number
}) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const save = useSaveAnnotations(projectId)
  const createExemplar = useCreateExemplar(projectId)
  const [state, dispatch] = useReducer(reducer, detail.annotations, initState)
  const [activeClassId, setActiveClassId] = useState<number | null>(classes[0]?.id ?? null)
  const [panMode, setPanMode] = useState(false)
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null)
  const [busy, setBusy] = useState(false)

  const classMap = useMemo(() => new Map(classes.map((c) => [c.id, c])), [classes])
  const selectedBox = state.boxes.find((b) => b.key === state.selected) ?? null
  const qs = queryString(filters)

  // Prefetch gambar berikutnya supaya navigasi terasa instan.
  useEffect(() => {
    if (!detail.next_id) return
    const nextId = detail.next_id
    qc.prefetchQuery({
      queryKey: ['image', nextId, filters],
      queryFn: () => api<ImageDetail>(`/images/${nextId}${qs}`),
    })
    new window.Image().src = imageFileUrl(nextId)
  }, [detail.next_id, filters, qs, qc])

  // Peringatan sebelum menutup tab jika ada perubahan belum tersimpan.
  useEffect(() => {
    if (!state.dirty) return
    const handler = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [state.dirty])

  const persist = useCallback(
    async (approve: boolean) => {
      const saved = await save.mutateAsync({ imageId: detail.id, annotations: toPayload(state.boxes), approve })
      const sel = state.boxes.find((b) => b.key === state.selected)
      const match = sel ? matchSaved(sel, saved.annotations) : undefined
      dispatch({ type: 'reset', annotations: saved.annotations, select: match ? keyFor(match) : null })
      return { saved, match }
    },
    [save, detail.id, state.boxes, state.selected],
  )

  const run = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true)
    setMessage(null)
    try {
      await fn()
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : String(e), error: true })
    } finally {
      setBusy(false)
    }
  }, [])

  const goTo = useCallback(
    (imageId: number | null) =>
      imageId &&
      run(async () => {
        if (state.dirty) await persist(false)
        navigate(`/projects/${projectId}/annotate/${imageId}${qs}`)
      }),
    [run, state.dirty, persist, navigate, projectId, qs],
  )

  const approveAndNext = useCallback(
    () =>
      run(async () => {
        await persist(true)
        if (detail.next_id) navigate(`/projects/${projectId}/annotate/${detail.next_id}${qs}`)
        else setMessage({ text: 'Approved. Ini gambar terakhir dalam filter.' })
      }),
    [run, persist, detail.next_id, navigate, projectId, qs],
  )

  const saveOnly = useCallback(
    () => run(async () => (await persist(false), setMessage({ text: 'Tersimpan' }))),
    [run, persist],
  )

  const makeExemplar = () =>
    run(async () => {
      if (!selectedBox) return
      let annotationId = selectedBox.id
      if (state.dirty || annotationId === null) {
        const { match } = await persist(false)
        annotationId = match?.id ?? null
      }
      if (annotationId === null) throw new Error('Box belum tersimpan')
      await createExemplar.mutateAsync(annotationId)
      setMessage({ text: `Contoh visual ditambahkan ke class "${classMap.get(selectedBox.class_id)?.name}"` })
    })

  const chooseClass = useCallback(
    (classId: number) => {
      setActiveClassId(classId)
      if (state.selected) dispatch({ type: 'update', key: state.selected, patch: { class_id: classId } })
    },
    [state.selected],
  )

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (isTyping(e.target)) return
      const ctrl = e.ctrlKey || e.metaKey
      if (e.key === ' ') {
        e.preventDefault()
        setPanMode(true)
      } else if (ctrl && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        dispatch({ type: 'undo' })
      } else if (ctrl && e.key.toLowerCase() === 's') {
        e.preventDefault()
        saveOnly()
      } else if (busy) {
        return
      } else if (e.key === 'ArrowRight') {
        goTo(detail.next_id)
      } else if (e.key === 'ArrowLeft') {
        goTo(detail.prev_id)
      } else if (e.key === 'Enter') {
        e.preventDefault()
        approveAndNext()
      } else if ((e.key === 'Delete' || e.key === 'Backspace') && state.selected) {
        dispatch({ type: 'remove', key: state.selected })
      } else if (e.key === 'Escape') {
        dispatch({ type: 'select', key: null })
      } else if (/^[1-9]$/.test(e.key) && !ctrl) {
        const cls = classes[Number(e.key) - 1]
        if (cls) chooseClass(cls.id)
      }
    }
    const up = (e: KeyboardEvent) => e.key === ' ' && setPanMode(false)
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
    }
  }, [busy, goTo, approveAndNext, saveOnly, chooseClass, detail.next_id, detail.prev_id, state.selected, classes])

  const unapproved = state.boxes.filter((b) => !b.is_approved).length

  return (
    <div className="flex h-screen flex-col bg-white text-ink">
      <header className="flex h-14 items-center gap-3 border-b border-slate-200 bg-white px-4 text-sm">
        <Brand compact />
        <span className="h-5 w-px bg-slate-200" />
        <Link to={`/projects/${projectId}/gallery${qs}`} className="font-medium text-brand-700 hover:text-brand-800">
          ← Galeri
        </Link>
        <span className="truncate font-medium">{detail.original_filename}</span>
        <ImageStatusBadge status={detail.status} />
        <span className="text-slate-500">
          {detail.width}×{detail.height}
        </span>
        {detail.position !== null && (
          <span className="text-slate-500">
            {detail.position} / {detail.filtered_total}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {busy && <Spinner />}
          {message && (
            <span className={message.error ? 'text-rose-600' : 'text-brand-700'}>{message.text}</span>
          )}
          {state.dirty && !busy && <span className="text-amber-600">Belum disimpan</span>}
          <Button disabled={!detail.prev_id || busy} onClick={() => goTo(detail.prev_id)}>
            ←
          </Button>
          <Button disabled={!detail.next_id || busy} onClick={() => goTo(detail.next_id)}>
            →
          </Button>
          <Button disabled={busy || !state.dirty} onClick={saveOnly}>
            Simpan
          </Button>
          <Button variant="primary" disabled={busy} onClick={approveAndNext}>
            Approve & lanjut ⏎
          </Button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1 bg-slate-100">
          <AnnotationCanvas
            imageUrl={imageFileUrl(detail.id)}
            width={detail.width}
            height={detail.height}
            boxes={state.boxes}
            classes={classMap}
            selected={state.selected}
            activeClassId={activeClassId}
            panMode={panMode}
            onSelect={(key) => dispatch({ type: 'select', key })}
            onAdd={(rect) => activeClassId !== null && dispatch({ type: 'add', box: { ...rect, class_id: activeClassId } })}
            onChange={(key, rect) => dispatch({ type: 'update', key, patch: rect })}
          />
        </div>

        <aside className="w-72 shrink-0 space-y-5 overflow-y-auto border-l border-slate-200 bg-white p-4 text-sm">
          <section>
            <h2 className="mb-2 font-semibold text-ink">Class</h2>
            {classes.length === 0 && (
              <p className="text-amber-600">
                Belum ada class. <Link to={`/projects/${projectId}/classes`} className="underline">Tambah class</Link>
              </p>
            )}
            <ul className="space-y-1">
              {classes.map((c, i) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => chooseClass(c.id)}
                    className={`flex w-full items-center gap-2 rounded px-2 py-1 text-left ${
                      activeClassId === c.id ? 'bg-brand-50 font-medium ring-1 ring-brand-300' : 'hover:bg-slate-50'
                    }`}
                  >
                    <span className="w-4 text-slate-500">{i < 9 ? i + 1 : ''}</span>
                    <span className="h-3 w-3 rounded-sm" style={{ background: c.color }} />
                    <span className="truncate">{c.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>

          {selectedBox && (
            <section className="space-y-2 rounded-md bg-slate-50 p-3 ring-1 ring-slate-200">
              <h2 className="font-semibold text-ink">Box terpilih</h2>
              <select
                className={inputClass}
                value={selectedBox.class_id}
                onChange={(e) => chooseClass(Number(e.target.value))}
              >
                {classes.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
              <p className="text-xs text-slate-500">Sumber: {sourceLabel(selectedBox)}</p>
              <div className="flex flex-wrap gap-2">
                <Button onClick={makeExemplar} disabled={busy}>
                  Jadikan contoh visual
                </Button>
                <Button variant="danger" onClick={() => dispatch({ type: 'remove', key: selectedBox.key })}>
                  Hapus
                </Button>
              </div>
            </section>
          )}

          <section>
            <h2 className="mb-2 font-semibold text-ink">
              Box ({state.boxes.length}
              {unapproved > 0 && <span className="text-amber-600"> · {unapproved} belum di-approve</span>})
            </h2>
            <ul className="space-y-0.5">
              {state.boxes.map((b) => (
                <li key={b.key}>
                  <button
                    type="button"
                    onClick={() => dispatch({ type: 'select', key: b.key })}
                    className={`flex w-full items-center gap-2 rounded px-2 py-1 text-left ${
                      b.key === state.selected ? 'bg-brand-50 ring-1 ring-brand-300' : 'hover:bg-slate-50'
                    }`}
                  >
                    <span
                      className={`h-3 w-3 rounded-sm ${b.is_approved ? '' : 'border border-dashed border-slate-600'}`}
                      style={{ background: classMap.get(b.class_id)?.color }}
                    />
                    <span className="truncate">{classMap.get(b.class_id)?.name}</span>
                    <span className="ml-auto text-xs text-slate-500">{sourceLabel(b)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <ErrorText error={save.error && !message ? save.error : null} />

          <section>
            <h2 className="mb-2 font-semibold text-ink">Shortcut</h2>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs text-slate-500">
              {SHORTCUTS.map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="font-mono text-ink">{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
          </section>
        </aside>
      </div>
    </div>
  )
}

export function EditorPage() {
  const params = useParams()
  const projectId = Number(params.projectId)
  const imageId = Number(params.imageId)
  const [search] = useSearchParams()
  const filters = useMemo(() => filtersFromParams(search), [search])
  const { data: detail, error } = useImageDetail(imageId, filters)
  const { data: classes } = useClasses(projectId)

  if (error)
    return (
      <div className="p-10 text-center">
        <ErrorText error={error} />
        <Link to={`/projects/${projectId}/gallery`} className="text-brand-700">
          Kembali ke galeri
        </Link>
      </div>
    )
  if (!detail || detail.id !== imageId || !classes)
    return (
      <div className="flex h-screen items-center justify-center bg-white text-brand-600">
        <Spinner />
      </div>
    )
  // key: state editor dibuat ulang dari data server setiap kali gambar berganti.
  return <Editor key={detail.id} detail={detail} classes={classes} filters={filters} projectId={projectId} />
}
