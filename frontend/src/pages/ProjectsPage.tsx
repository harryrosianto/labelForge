import { useState } from 'react'
import { Link } from 'react-router-dom'

import { useDeleteProject, useProjects, useSaveProject } from '../api/hooks'
import type { Project } from '../api/types'
import { AppHeader } from '../components/AppHeader'
import { Button, EmptyState, ErrorText, Field, inputClass, Modal, Spinner } from '../components/ui'

function ProjectForm({ project, onClose }: { project?: Project; onClose: () => void }) {
  const save = useSaveProject()
  const [name, setName] = useState(project?.name ?? '')
  const [description, setDescription] = useState(project?.description ?? '')

  return (
    <Modal title={project ? 'Edit project' : 'Project baru'} onClose={onClose}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate({ id: project?.id, name, description: description || null }, { onSuccess: onClose })
        }}
      >
        <Field label="Nama">
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} autoFocus required />
        </Field>
        <Field label="Deskripsi">
          <textarea
            className={inputClass}
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
        <p className="text-xs text-slate-500">Tipe task: object detection</p>
        <ErrorText error={save.error} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Batal</Button>
          <Button type="submit" variant="primary" disabled={save.isPending || !name.trim()}>
            {save.isPending && <Spinner />} Simpan
          </Button>
        </div>
      </form>
    </Modal>
  )
}

export function ProjectsPage() {
  const { data: projects, isLoading, error } = useProjects()
  const remove = useDeleteProject()
  const [editing, setEditing] = useState<Project | 'new' | null>(null)

  return (
    <>
    <AppHeader />
    <div className="mx-auto max-w-5xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-ink">Projects</h1>
          <p className="text-sm text-slate-500">Dataset object detection dengan auto-labeling AI</p>
        </div>
        <Button variant="primary" onClick={() => setEditing('new')}>
          + Project baru
        </Button>
      </div>

      {isLoading && <Spinner />}
      <ErrorText error={error ?? remove.error} />
      {projects?.length === 0 && (
        <EmptyState title="Belum ada project">Buat project untuk mulai mengumpulkan dataset.</EmptyState>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {projects?.map((p) => (
          <div key={p.id} className="flex flex-col rounded-lg border-t-4 border-brand-500 bg-white p-4 shadow-sm ring-1 ring-slate-200">
            <Link to={`/projects/${p.id}`} className="text-lg font-semibold text-ink hover:text-brand-700">
              {p.name}
            </Link>
            <p className="mt-1 line-clamp-2 min-h-10 text-sm text-slate-500">{p.description || 'Tanpa deskripsi'}</p>
            <p className="mt-3 text-sm text-slate-600">
              {p.image_count} gambar · {p.class_count} class
            </p>
            <div className="mt-3 flex gap-1 border-t border-slate-100 pt-3">
              <Link to={`/projects/${p.id}`} className="mr-auto text-sm font-medium text-brand-700">
                Buka →
              </Link>
              <Button variant="ghost" onClick={() => setEditing(p)}>
                Edit
              </Button>
              <Button
                variant="ghost"
                className="text-rose-600"
                onClick={() => {
                  if (confirm(`Hapus project "${p.name}" beserta ${p.image_count} gambar dan semua labelnya?`))
                    remove.mutate(p.id)
                }}
              >
                Hapus
              </Button>
            </div>
          </div>
        ))}
      </div>

      {editing && (
        <ProjectForm project={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} />
      )}
    </div>
    </>
  )
}
