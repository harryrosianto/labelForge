import type Konva from 'konva'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Group, Image as KImage, Label, Layer, Rect, Stage, Tag, Text, Transformer } from 'react-konva'

import type { LabelClass } from '../api/types'
import { clampRect, type EditBox, type Rect as NormRect } from './state'

interface Props {
  imageUrl: string
  width: number // ukuran asli gambar (px)
  height: number
  boxes: EditBox[]
  classes: Map<number, LabelClass>
  selected: string | null
  activeClassId: number | null
  panMode: boolean
  onSelect: (key: string | null) => void
  onAdd: (rect: NormRect) => void
  onChange: (key: string, rect: NormRect) => void
}

const MIN_BOX_PX = 4

function useHtmlImage(url: string) {
  const [img, setImg] = useState<HTMLImageElement | null>(null)
  useEffect(() => {
    const el = new window.Image()
    el.onload = () => setImg(el)
    el.src = url
    return () => {
      el.onload = null
    }
  }, [url])
  return img?.src.endsWith(url) ? img : null
}

function useContainerSize() {
  const ref = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  useLayoutEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(([entry]) =>
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height }),
    )
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return [ref, size] as const
}

export function AnnotationCanvas({
  imageUrl,
  width,
  height,
  boxes,
  classes,
  selected,
  activeClassId,
  panMode,
  onSelect,
  onAdd,
  onChange,
}: Props) {
  const image = useHtmlImage(imageUrl)
  const [containerRef, size] = useContainerSize()
  const layerRef = useRef<Konva.Layer>(null)
  const trRef = useRef<Konva.Transformer>(null)
  const rectRefs = useRef(new Map<string, Konva.Rect>())
  // view: zoom relatif terhadap skala "fit", dan offset layer dalam pixel layar
  const [view, setView] = useState({ zoom: 1, x: 0, y: 0 })
  const [draft, setDraft] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null)

  const fit = size.width && size.height ? Math.min(size.width / width, size.height / height) * 0.96 : 1
  const scale = fit * view.zoom
  const baseX = (size.width - width * fit) / 2
  const baseY = (size.height - height * fit) / 2

  // Reset zoom saat berganti gambar.
  const [viewFor, setViewFor] = useState(imageUrl)
  if (viewFor !== imageUrl) {
    setViewFor(imageUrl)
    setView({ zoom: 1, x: 0, y: 0 })
  }

  useEffect(() => {
    const node = selected ? rectRefs.current.get(selected) : undefined
    trRef.current?.nodes(node ? [node] : [])
    trRef.current?.getLayer()?.batchDraw()
  }, [selected, boxes])

  /** Posisi pointer dalam koordinat pixel gambar. */
  const pointer = () => {
    const p = layerRef.current?.getRelativePointerPosition()
    return p ? { x: Math.min(width, Math.max(0, p.x)), y: Math.min(height, Math.max(0, p.y)) } : null
  }

  const toNorm = (x0: number, y0: number, x1: number, y1: number): NormRect =>
    clampRect({ x_min: x0 / width, y_min: y0 / height, x_max: x1 / width, y_max: y1 / height })

  const onWheel = (e: Konva.KonvaEventObject<WheelEvent>) => {
    e.evt.preventDefault()
    const stage = e.target.getStage()
    const p = stage?.getPointerPosition()
    if (!p) return
    const factor = e.evt.deltaY < 0 ? 1.15 : 1 / 1.15
    const zoom = Math.min(20, Math.max(0.5, view.zoom * factor))
    const newScale = fit * zoom
    // pertahankan titik gambar di bawah pointer
    const ix = (p.x - baseX - view.x) / scale
    const iy = (p.y - baseY - view.y) / scale
    setView({ zoom, x: p.x - baseX - ix * newScale, y: p.y - baseY - iy * newScale })
  }

  const isBackground = (t: Konva.Node) => t === t.getStage() || t.name() === 'background'

  return (
    <div ref={containerRef} className={`h-full w-full ${panMode ? 'cursor-grab' : 'cursor-crosshair'}`}>
      {size.width > 0 && (
        <Stage
          width={size.width}
          height={size.height}
          onWheel={onWheel}
          onMouseDown={(e) => {
            if (panMode || e.evt.button !== 0) return
            if (!isBackground(e.target)) return
            onSelect(null)
            if (activeClassId === null) return
            const p = pointer()
            if (p) setDraft({ x0: p.x, y0: p.y, x1: p.x, y1: p.y })
          }}
          onMouseMove={() => {
            if (!draft) return
            const p = pointer()
            if (p) setDraft({ ...draft, x1: p.x, y1: p.y })
          }}
          onMouseUp={() => {
            if (!draft) return
            const w = Math.abs(draft.x1 - draft.x0)
            const h = Math.abs(draft.y1 - draft.y0)
            if (w * scale >= MIN_BOX_PX && h * scale >= MIN_BOX_PX)
              onAdd(toNorm(draft.x0, draft.y0, draft.x1, draft.y1))
            setDraft(null)
          }}
        >
          <Layer
            ref={layerRef}
            x={baseX + view.x}
            y={baseY + view.y}
            scaleX={scale}
            scaleY={scale}
            draggable={panMode}
            onDragEnd={(e) => {
              if ((e.target as Konva.Node) === layerRef.current)
                setView((v) => ({ ...v, x: e.target.x() - baseX, y: e.target.y() - baseY }))
            }}
          >
            {image && <KImage image={image} width={width} height={height} name="background" />}
            {boxes.map((b) => {
              const cls = classes.get(b.class_id)
              const color = cls?.color ?? '#ffffff'
              const x = b.x_min * width
              const y = b.y_min * height
              const w = (b.x_max - b.x_min) * width
              const h = (b.y_max - b.y_min) * height
              const isSel = b.key === selected
              const label = `${cls?.name ?? '?'}${!b.is_approved && b.confidence !== null ? ` ${b.confidence.toFixed(2)}` : ''}`
              return (
                <Group key={b.key}>
                  <Rect
                    ref={(node) => {
                      if (node) rectRefs.current.set(b.key, node)
                      else rectRefs.current.delete(b.key)
                    }}
                    x={x}
                    y={y}
                    width={w}
                    height={h}
                    stroke={color}
                    strokeWidth={isSel ? 3 : 2}
                    strokeScaleEnabled={false}
                    dash={b.is_approved ? undefined : [8, 5]}
                    fill={isSel ? `${color}33` : 'transparent'}
                    draggable={!panMode}
                    onMouseDown={(e) => {
                      if (panMode) return
                      e.cancelBubble = true
                      onSelect(b.key)
                    }}
                    onDragEnd={(e) => {
                      const nx = Math.min(Math.max(0, e.target.x()), width - w)
                      const ny = Math.min(Math.max(0, e.target.y()), height - h)
                      e.target.position({ x: nx, y: ny })
                      onChange(b.key, toNorm(nx, ny, nx + w, ny + h))
                    }}
                    onTransformEnd={(e) => {
                      const node = e.target
                      const nw = node.width() * node.scaleX()
                      const nh = node.height() * node.scaleY()
                      node.scale({ x: 1, y: 1 })
                      onChange(b.key, toNorm(node.x(), node.y(), node.x() + nw, node.y() + nh))
                    }}
                  />
                  <Label x={x} y={y} offsetY={18} scaleX={1 / scale} scaleY={1 / scale} listening={false}>
                    <Tag fill={color} opacity={b.is_approved ? 0.95 : 0.75} />
                    <Text text={label} fontSize={12} padding={3} fill="#000" />
                  </Label>
                </Group>
              )
            })}
            {draft && (
              <Rect
                x={Math.min(draft.x0, draft.x1)}
                y={Math.min(draft.y0, draft.y1)}
                width={Math.abs(draft.x1 - draft.x0)}
                height={Math.abs(draft.y1 - draft.y0)}
                stroke={(activeClassId !== null && classes.get(activeClassId)?.color) || '#fff'}
                strokeWidth={2}
                strokeScaleEnabled={false}
                listening={false}
              />
            )}
            <Transformer
              ref={trRef}
              rotateEnabled={false}
              keepRatio={false}
              ignoreStroke
              flipEnabled={false}
              anchorSize={8}
              anchorStroke="#007d7a"
              anchorFill="#ffffff"
              borderStroke="#00b0ad"
              boundBoxFunc={(oldBox, newBox) => (newBox.width < MIN_BOX_PX || newBox.height < MIN_BOX_PX ? oldBox : newBox)}
            />
          </Layer>
        </Stage>
      )}
    </div>
  )
}
