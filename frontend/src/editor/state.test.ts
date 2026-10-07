import { describe, expect, it } from 'vitest'

import type { Annotation } from '../api/types'
import { clampRect, initState, matchSaved, reducer, toPayload } from './state'

const ai: Annotation = {
  id: 7, class_id: 1, x_min: 0.1, y_min: 0.1, x_max: 0.5, y_max: 0.5,
  source: 'ai:owlv2_text', confidence: 0.4, is_approved: false,
}

describe('editor reducer', () => {
  it('memuat anotasi tanpa status dirty', () => {
    const s = initState([ai])
    expect(s.boxes).toHaveLength(1)
    expect(s.boxes[0].key).toBe('a7')
    expect(s.dirty).toBe(false)
  })

  it('box baru: manual, approved, terpilih', () => {
    const s = reducer(initState([]), { type: 'add', box: { class_id: 2, x_min: 0, y_min: 0, x_max: 0.2, y_max: 0.2 } })
    expect(s.boxes[0]).toMatchObject({ id: null, source: 'manual', is_approved: true, class_id: 2 })
    expect(s.selected).toBe(s.boxes[0].key)
    expect(s.dirty).toBe(true)
  })

  it('mengedit box AI membuatnya approved tapi sumber tetap', () => {
    const s = reducer(initState([ai]), { type: 'update', key: 'a7', patch: { class_id: 3 } })
    expect(s.boxes[0]).toMatchObject({ class_id: 3, is_approved: true, source: 'ai:owlv2_text', confidence: 0.4 })
  })

  it('undo mengembalikan langkah sebelumnya', () => {
    let s = initState([ai])
    s = reducer(s, { type: 'select', key: 'a7' })
    s = reducer(s, { type: 'remove', key: 'a7' })
    expect(s.boxes).toHaveLength(0)
    expect(s.selected).toBeNull()
    s = reducer(s, { type: 'undo' })
    expect(s.boxes).toHaveLength(1)
    expect(reducer(initState([]), { type: 'undo' }).dirty).toBe(false)
  })

  it('approveAll', () => {
    const s = reducer(initState([ai, { ...ai, id: 8 }]), { type: 'approveAll' })
    expect(s.boxes.every((b) => b.is_approved)).toBe(true)
  })

  it('payload hanya berisi field yang diterima API', () => {
    expect(toPayload(initState([ai]).boxes)).toEqual([
      { id: 7, class_id: 1, x_min: 0.1, y_min: 0.1, x_max: 0.5, y_max: 0.5, is_approved: false },
    ])
  })
})

describe('helpers', () => {
  it('clampRect mengurutkan sudut dan memotong ke 0..1', () => {
    expect(clampRect({ x_min: 1.2, y_min: 0.5, x_max: -0.1, y_max: 0.2 })).toEqual({
      x_min: 0, y_min: 0.2, x_max: 1, y_max: 0.5,
    })
  })

  it('matchSaved menemukan box baru berdasarkan class & koordinat', () => {
    let s = reducer(initState([]), { type: 'add', box: { class_id: 1, x_min: 0.1, y_min: 0.1, x_max: 0.5, y_max: 0.5 } })
    expect(matchSaved(s.boxes[0], [{ ...ai, id: 99, is_approved: true, source: 'manual' }])?.id).toBe(99)
    s = reducer(s, { type: 'update', key: s.boxes[0].key, patch: { x_max: 0.6 } })
    expect(matchSaved(s.boxes[0], [ai])).toBeUndefined()
  })
})
