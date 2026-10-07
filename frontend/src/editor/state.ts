import type { Annotation } from '../api/types'

/** Box di editor. Koordinat ternormalisasi 0-1. `id` null = box baru yang belum disimpan. */
export interface EditBox {
  key: string
  id: number | null
  class_id: number
  x_min: number
  y_min: number
  x_max: number
  y_max: number
  source: string
  confidence: number | null
  is_approved: boolean
}

export type Rect = Pick<EditBox, 'x_min' | 'y_min' | 'x_max' | 'y_max'>

export interface EditorState {
  boxes: EditBox[]
  selected: string | null
  history: EditBox[][]
  dirty: boolean
}

export type Action =
  | { type: 'reset'; annotations: Annotation[]; select?: string | null }
  | { type: 'add'; box: Omit<EditBox, 'key' | 'id' | 'source' | 'confidence' | 'is_approved'> }
  | { type: 'update'; key: string; patch: Partial<Rect & { class_id: number }> }
  | { type: 'remove'; key: string }
  | { type: 'select'; key: string | null }
  | { type: 'approveAll' }
  | { type: 'undo' }

const HISTORY_LIMIT = 100
let newKeySeq = 0

export const keyFor = (a: Annotation) => `a${a.id}`

export function fromAnnotations(annotations: Annotation[]): EditBox[] {
  return annotations.map((a) => ({ ...a, key: keyFor(a) }))
}

export function initState(annotations: Annotation[]): EditorState {
  return { boxes: fromAnnotations(annotations), selected: null, history: [], dirty: false }
}

function commit(state: EditorState, boxes: EditBox[], selected = state.selected): EditorState {
  return {
    boxes,
    selected,
    history: [...state.history, state.boxes].slice(-HISTORY_LIMIT),
    dirty: true,
  }
}

export function reducer(state: EditorState, action: Action): EditorState {
  switch (action.type) {
    case 'reset':
      return { ...initState(action.annotations), selected: action.select ?? null }
    case 'add': {
      const key = `n${++newKeySeq}`
      const box: EditBox = { ...action.box, key, id: null, source: 'manual', confidence: null, is_approved: true }
      return commit(state, [...state.boxes, box], key)
    }
    case 'update':
      // Box yang diedit user dianggap sudah dikoreksi → approved.
      return commit(
        state,
        state.boxes.map((b) => (b.key === action.key ? { ...b, ...action.patch, is_approved: true } : b)),
      )
    case 'remove':
      return commit(
        state,
        state.boxes.filter((b) => b.key !== action.key),
        state.selected === action.key ? null : state.selected,
      )
    case 'select':
      return { ...state, selected: action.key }
    case 'approveAll':
      return commit(state, state.boxes.map((b) => ({ ...b, is_approved: true })))
    case 'undo': {
      const previous = state.history.at(-1)
      if (!previous) return state
      return {
        boxes: previous,
        selected: previous.some((b) => b.key === state.selected) ? state.selected : null,
        history: state.history.slice(0, -1),
        dirty: true,
      }
    }
  }
}

/** Payload PUT /images/{id}/annotations */
export function toPayload(boxes: EditBox[]) {
  return boxes.map(({ id, class_id, x_min, y_min, x_max, y_max, is_approved }) => ({
    id,
    class_id,
    x_min,
    y_min,
    x_max,
    y_max,
    is_approved,
  }))
}

/** Cari anotasi tersimpan yang sama dengan box lokal (untuk box baru yang belum punya id). */
export function matchSaved(box: EditBox, saved: Annotation[]): Annotation | undefined {
  if (box.id !== null) return saved.find((a) => a.id === box.id)
  const eps = 1e-6
  return saved.find(
    (a) =>
      a.class_id === box.class_id &&
      Math.abs(a.x_min - box.x_min) < eps &&
      Math.abs(a.y_min - box.y_min) < eps &&
      Math.abs(a.x_max - box.x_max) < eps &&
      Math.abs(a.y_max - box.y_max) < eps,
  )
}

export function clampRect(r: Rect): Rect {
  const c = (v: number) => Math.min(1, Math.max(0, v))
  return {
    x_min: c(Math.min(r.x_min, r.x_max)),
    y_min: c(Math.min(r.y_min, r.y_max)),
    x_max: c(Math.max(r.x_min, r.x_max)),
    y_max: c(Math.max(r.y_min, r.y_max)),
  }
}
