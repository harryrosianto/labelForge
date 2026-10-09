import type { AugmentationConfig } from '../api/types'

// Sama dengan default AugmentationConfig di backend.
export const DEFAULT_AUGMENTATION: AugmentationConfig = {
  enabled: false,
  multiplier: 2,
  hflip: 0.5,
  rotate_deg: 0,
  scale_min: 1,
  scale_max: 1,
  translate: 0,
  mosaic: 0,
  brightness: 0.2,
  contrast: 0.2,
  hue_deg: 0,
  saturation: 0,
  blur: 0,
  blur_max_kernel: 5,
  noise: 0,
  noise_std: 8,
  min_visibility: 0.3,
}

export function describeAugmentation(a: AugmentationConfig | undefined): string {
  if (!a?.enabled) return 'Tanpa augmentasi'
  const parts = [`${a.multiplier}× per gambar train`]
  if (a.hflip) parts.push(`flip ${Math.round(a.hflip * 100)}%`)
  if (a.rotate_deg) parts.push(`rotasi ±${a.rotate_deg}°`)
  if (a.scale_min !== 1 || a.scale_max !== 1) parts.push(`skala ${a.scale_min}-${a.scale_max}×`)
  if (a.translate) parts.push(`geser ±${Math.round(a.translate * 100)}%`)
  if (a.mosaic) parts.push(`mosaic ${Math.round(a.mosaic * 100)}%`)
  if (a.brightness || a.contrast) parts.push('brightness/contrast')
  if (a.hue_deg || a.saturation) parts.push('hue/saturation')
  if (a.blur) parts.push('blur')
  if (a.noise) parts.push('noise')
  return parts.join(', ')
}
