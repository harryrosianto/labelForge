import { useState } from 'react'
import { Link } from 'react-router-dom'

import {
  useClasses,
  useCreateClass,
  useDeleteClass,
  useDeleteExemplar,
  useExemplars,
  useReorderClasses,
  useUpdateClass,
} from '../../api/hooks'
import type { LabelClass } from '../../api/types'
import { Button, ErrorText, inputClass, Spinner } from '../../components/ui'
import { useProjectId } from '../../lib/route'

const PROMPT_HINT =
  'Frasa benda singkat dalam bahasa Inggris (maks. ~8 kata), bukan kalimat penjelasan. Pisahkan sinonim dengan koma, mis. "wooden pallet, plastic pallet" atau "cardboard box, carton".'

function ExemplarStrip({ cls }: { cls: LabelClass }) {
  const { data: exemplars, isLoading } = useExemplars(cls.id)
  const remove = useDeleteExemplar(cls.project_id)
  return (
    <tr>
      <td colSpan={7} className="bg-slate-50 px-4 py-3">
        {isLoading && <Spinner />}
        <div className="flex flex-wrap gap-3">
          {exemplars?.map((ex) => (
            <figure key={ex.id} className="group relative">
              <img
                src={`/api/exemplars/${ex.id}/image`}
                alt={`Contoh ${cls.name}`}
                className="h-20 w-auto rounded border border-slate-200 bg-white object-contain"
              />
              <figcaption className="mt-0.5 text-center text-xs text-slate-500">
                {ex.source_image_id ? (
                  <Link className="hover:text-brand-700" to={`/projects/${cls.project_id}/annotate/${ex.source_image_id}`}>
                    {ex.width}×{ex.height}
                  </Link>
                ) : (
                  `${ex.width}×${ex.height}`
                )}
              </figcaption>
              <button
                type="button"
                onClick={() => remove.mutate(ex)}
                className="absolute -right-2 -top-2 hidden h-5 w-5 rounded-full bg-rose-600 text-xs text-white group-hover:block"
                aria-label="Hapus contoh visual"
              >
                ×
              </button>
            </figure>
          ))}
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Dipakai mode “contoh visual” OWLv2. Pilih box yang pas di objek (tanpa objek lain menempel) agar hasilnya bagus.
        </p>
        <ErrorText error={remove.error} />
      </td>
    </tr>
  )
}

function ClassRow({
  cls,
  index,
  total,
  onMove,
}: {
  cls: LabelClass
  index: number
  total: number
  onMove: (from: number, to: number) => void
}) {
  const id = cls.project_id
  const update = useUpdateClass(id)
  const remove = useDeleteClass(id)
  const [name, setName] = useState(cls.name)
  const [prompt, setPrompt] = useState(cls.text_prompt ?? '')
  const [showExemplars, setShowExemplars] = useState(false)

  const commitName = () => name.trim() && name !== cls.name && update.mutate({ id: cls.id, name })
  const commitPrompt = () =>
    prompt !== (cls.text_prompt ?? '') && update.mutate({ id: cls.id, text_prompt: prompt.trim() || null })

  return (
    <>
    <tr className="border-t border-slate-100 align-top">
      <td className="py-2 pr-2 text-sm text-slate-400 tabular-nums" title="Index class di YOLO / shortcut">
        {index + 1}
      </td>
      <td className="py-2 pr-2">
        <input
          type="color"
          value={cls.color}
          onChange={(e) => update.mutate({ id: cls.id, color: e.target.value })}
          className="h-8 w-10 cursor-pointer rounded border border-slate-300"
          aria-label="Warna"
        />
      </td>
      <td className="py-2 pr-2">
        <input
          className={inputClass}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onBlur={commitName}
          onKeyDown={(e) => e.key === 'Enter' && commitName()}
        />
      </td>
      <td className="py-2 pr-2">
        <input
          className={inputClass}
          value={prompt}
          placeholder={cls.name}
          onChange={(e) => setPrompt(e.target.value)}
          onBlur={commitPrompt}
          onKeyDown={(e) => e.key === 'Enter' && commitPrompt()}
        />
        <ErrorText error={update.error ?? remove.error} />
      </td>
      <td className="py-2 pr-2 text-right text-sm tabular-nums text-slate-600">{cls.annotation_count}</td>
      <td className="py-2 pr-2 text-right text-sm tabular-nums text-slate-600">
        {cls.exemplar_count > 0 ? (
          <button type="button" className="text-brand-700 hover:underline" onClick={() => setShowExemplars(!showExemplars)}>
            {cls.exemplar_count} {showExemplars ? '▴' : '▾'}
          </button>
        ) : (
          0
        )}
      </td>
      <td className="whitespace-nowrap py-2 text-right">
        <Button variant="ghost" disabled={index === 0} onClick={() => onMove(index, index - 1)} aria-label="Naik">
          ↑
        </Button>
        <Button
          variant="ghost"
          disabled={index === total - 1}
          onClick={() => onMove(index, index + 1)}
          aria-label="Turun"
        >
          ↓
        </Button>
        <Button
          variant="ghost"
          className="text-rose-600"
          onClick={() => {
            const msg = cls.annotation_count
              ? `Hapus class "${cls.name}"? ${cls.annotation_count} anotasi dan ${cls.exemplar_count} contoh visual ikut terhapus.`
              : `Hapus class "${cls.name}"?`
            if (confirm(msg)) remove.mutate(cls.id)
          }}
        >
          Hapus
        </Button>
      </td>
    </tr>
    {showExemplars && cls.exemplar_count > 0 && <ExemplarStrip cls={cls} />}
    </>
  )
}

export function ClassesTab() {
  const id = useProjectId()
  const { data: classes, isLoading } = useClasses(id)
  const create = useCreateClass(id)
  const reorder = useReorderClasses(id)
  const [name, setName] = useState('')
  const [prompt, setPrompt] = useState('')

  const move = (from: number, to: number) => {
    if (!classes) return
    const ids = classes.map((c) => c.id)
    ids.splice(to, 0, ids.splice(from, 1)[0])
    reorder.mutate(ids)
  }

  return (
    <div className="space-y-6">
      <form
        className="flex flex-wrap items-end gap-2 rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200"
        onSubmit={(e) => {
          e.preventDefault()
          create.mutate(
            { name, text_prompt: prompt.trim() || null },
            { onSuccess: () => (setName(''), setPrompt('')) },
          )
        }}
      >
        <div className="w-48">
          <label className="text-sm font-medium text-slate-700">Nama class</label>
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} placeholder="pallet" />
        </div>
        <div className="min-w-64 flex-1">
          <label className="text-sm font-medium text-slate-700">Text prompt (opsional)</label>
          <input
            className={inputClass}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="wooden pallet, plastic pallet"
          />
        </div>
        <Button type="submit" variant="primary" disabled={!name.trim() || create.isPending}>
          {create.isPending && <Spinner />} Tambah class
        </Button>
        <div className="w-full">
          <p className="text-xs text-slate-500">{PROMPT_HINT}</p>
          <ErrorText error={create.error} />
        </div>
      </form>

      {isLoading && <Spinner />}
      {classes && classes.length > 0 && (
        <table className="w-full rounded-lg bg-white shadow-sm ring-1 ring-slate-200">
          <thead>
            <tr className="text-left text-xs uppercase text-slate-500">
              <th className="p-2 font-medium">#</th>
              <th className="p-2 font-medium">Warna</th>
              <th className="p-2 font-medium">Nama</th>
              <th className="p-2 font-medium">Text prompt</th>
              <th className="p-2 text-right font-medium">Anotasi</th>
              <th className="p-2 text-right font-medium" title="Dibuat dari editor anotasi">
                Contoh visual
              </th>
              <th />
            </tr>
          </thead>
          <tbody className="[&_td]:px-2">
            {classes.map((c, i) => (
              <ClassRow key={`${c.id}-${c.name}-${c.text_prompt}`} cls={c} index={i} total={classes.length} onMove={move} />
            ))}
          </tbody>
        </table>
      )}
      <ErrorText error={reorder.error} />
    </div>
  )
}
