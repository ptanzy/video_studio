import type { CreationStateV1, CreationStateV2, VisualTemplate } from '../../api/types'

export const EFFECT_DEFAULTS = {
  camera: true,
  zoom: 1.04,
  bars: true,
  barCount: 24,
  barOpacity: 0.65,
  progress: true,
  tint: '#416E9D',
  tintIntensity: 18,
  positionX: 50,
  positionY: 50,
} as const

const EFFECT_KEYS = new Set(Object.keys(EFFECT_DEFAULTS))
const HEX = /^#[0-9A-Fa-f]{6}$/

type FlatEffects = { [K in keyof typeof EFFECT_DEFAULTS]: boolean | number | string }

const flatEffects = (settings: Record<string, unknown>, shortId: string): FlatEffects | null => {
  if (!Object.prototype.hasOwnProperty.call(settings, 'effects')) return { ...EFFECT_DEFAULTS }
  const value = settings.effects
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${shortId}: settings.effects must be a JSON object.`)
  const effects = value as Record<string, unknown>
  if (Object.keys(effects).some((key) => !EFFECT_KEYS.has(key))) return null
  if (Object.values(effects).some((item) => item !== null && typeof item === 'object')) return null
  const merged = { ...EFFECT_DEFAULTS, ...effects } as Record<string, unknown>
  const invalid = (message: string): never => { throw new Error(`${shortId}: ${message}`) }
  for (const key of ['camera', 'bars', 'progress']) if (typeof merged[key] !== 'boolean') invalid(`${key} must be boolean.`)
  for (const [key, minimum, maximum] of [
    ['zoom', 1, 1.05], ['barOpacity', 0.1, 1], ['tintIntensity', 0, 60], ['positionX', 0, 100], ['positionY', 0, 100],
  ] as const) {
    const item = merged[key]
    if (typeof item !== 'number' || !Number.isFinite(item) || item < minimum || item > maximum) invalid(`${key} is outside its approved range.`)
  }
  if (!Number.isInteger(merged.barCount) || (merged.barCount as number) < 8 || (merged.barCount as number) > 64) invalid('barCount must be an integer from 8 through 64.')
  if (typeof merged.tint !== 'string' || !HEX.test(merged.tint)) invalid('tint must be a six-digit HEX color.')
  return merged as FlatEffects
}

const sha256 = async (value: string) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)))).map((item) => item.toString(16).padStart(2, '0')).join('')

const migratedTemplate = async (projectId: string, shortId: string, effects: FlatEffects): Promise<VisualTemplate> => ({
  visual_template_id: `visual-template-${(await sha256(`${projectId}\0${shortId}\0wrld-creation-state/2.0`)).slice(0, 32)}`,
  label: `Short visual ${shortId}`.slice(0, 128),
  canvas: { aspect_ratio: '9:16' },
  background_image: null,
  geometry: { fit_mode: 'contain', focal_x: (effects.positionX as number) / 100, focal_y: (effects.positionY as number) / 100 },
  camera: { mode: effects.camera ? 'bounded' : 'static', max_zoom: effects.zoom as number },
  visualizer: { enabled: effects.bars as boolean, bar_count: effects.barCount as number, opacity: effects.barOpacity as number },
  progress: { enabled: effects.progress as boolean },
  color_treatment: { mode: 'custom', hex: effects.tint as string, intensity: (effects.tintIntensity as number) / 100 },
})

export const migrateCreationState = async (state: CreationStateV1): Promise<CreationStateV2> => {
  const source = structuredClone(state)
  delete source.issues
  const identifiers = new Set<string>()
  source.albums.forEach((album) => { identifiers.add(album.album_plan_id); album.assignments.forEach((item) => identifiers.add(item.assignment_id)) })
  source.singles.forEach((single) => identifiers.add(single.single_id))
  source.shorts.forEach((short) => identifiers.add(short.short_id))
  const visualTemplates: VisualTemplate[] = []
  const shorts = [] as CreationStateV2['shorts']
  for (const short of source.shorts) {
    const effects = flatEffects(short.settings as Record<string, unknown>, short.short_id)
    let visualTemplateId: string | null = null
    if (effects) {
      const template = await migratedTemplate(source.project_id, short.short_id, effects)
      if (identifiers.has(template.visual_template_id)) throw new Error(`${short.short_id}: deterministic visual-template identity collision.`)
      identifiers.add(template.visual_template_id)
      visualTemplates.push(template)
      visualTemplateId = template.visual_template_id
    }
    shorts.push({ ...short, visual_template_id: visualTemplateId })
  }
  return {
    ...source,
    contract_version: 'wrld-creation-state/2.0',
    visual_templates: visualTemplates,
    albums: source.albums.map((album) => ({ ...album, visual_template_id: null })),
    singles: source.singles.map((single) => ({ ...single, visual_template_id: null })),
    shorts,
  }
}

export const newVisualTemplate = (aspectRatio: '16:9' | '9:16', label: string): VisualTemplate => ({
  visual_template_id: `visual-template-${crypto.randomUUID()}`,
  label: label.slice(0, 128),
  canvas: { aspect_ratio: aspectRatio },
  background_image: null,
  geometry: { fit_mode: 'contain', focal_x: 0.5, focal_y: 0.5 },
  camera: { mode: 'static', max_zoom: 1.04 },
  visualizer: { enabled: false, bar_count: 24, opacity: 0.65 },
  progress: { enabled: false },
  color_treatment: { mode: 'none' },
})
