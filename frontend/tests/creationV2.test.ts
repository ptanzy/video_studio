import { describe, expect, it } from 'vitest'
import type { CreationStateV1 } from '../src/api/types'
import { migrateCreationState, newVisualTemplate } from '../src/features/review/creationV2'

const short = (id: string, settings: Record<string, unknown>) => ({
  short_id: id, asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), status: 'active' as const,
  start_sample: 0, sample_count: 20 * 48_000, origin: 'manual' as const, review_required: false,
  customized: true, approved: true, settings,
})
const state = (): CreationStateV1 => ({
  contract_version: 'wrld-creation-state/1.0', project_id: 'project-1', revision: 4, save_id: 'saved', preferred_short_duration_seconds: 45,
  albums: [{ album_plan_id: 'album-1', label: 'Album', status: 'active', assignments: [] }],
  singles: [{ single_id: 'single-1', asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), status: 'archived', customized: true, approved: true, settings: { keep: true } }],
  shorts: [
    short('short-default', { caption: 'keep' }),
    short('short-flat', { effects: { camera: false, zoom: 1.03, positionX: 25, tintIntensity: 30 }, unknownGeneric: { keep: true } }),
    short('short-historical', { effects: { camera: { enabled: false } }, legacy: 'keep' }),
  ],
  state_digest: '0'.repeat(64), issues: [],
})

describe('Creation v2 migration', () => {
  it('is deterministic and preserves generic and historical settings', async () => {
    const original = state(); const first = await migrateCreationState(original); const second = await migrateCreationState(original)
    expect(first).toEqual(second)
    expect(original.contract_version).toBe('wrld-creation-state/1.0')
    expect(first.albums[0].visual_template_id).toBeNull()
    expect(first.singles[0]).toMatchObject({ single_id: 'single-1', status: 'archived', approved: true, settings: { keep: true }, visual_template_id: null })
    expect(first.shorts[2]).toMatchObject({ short_id: 'short-historical', approved: true, settings: original.shorts[2].settings, visual_template_id: null })
    expect(first.visual_templates).toHaveLength(2)
    expect(first.visual_templates[0]).toMatchObject({ camera: { mode: 'bounded', max_zoom: 1.04 }, visualizer: { enabled: true, bar_count: 24, opacity: 0.65 }, progress: { enabled: true }, color_treatment: { mode: 'custom', hex: '#416E9D', intensity: 0.18 } })
    expect(first.visual_templates[1]).toMatchObject({ geometry: { fit_mode: 'contain', focal_x: 0.25, focal_y: 0.5 }, camera: { mode: 'static', max_zoom: 1.03 }, color_treatment: { mode: 'custom', hex: '#416E9D', intensity: 0.3 } })
  })

  it('rejects clearly flat invalid values and approves neutral new-template defaults', async () => {
    const invalid = state(); invalid.shorts = [short('short-invalid', { effects: { zoom: Number.POSITIVE_INFINITY } })]
    await expect(migrateCreationState(invalid)).rejects.toThrow(/short-invalid: zoom is outside its approved range/i)
    expect(newVisualTemplate('16:9', 'New')).toMatchObject({
      background_image: null, geometry: { fit_mode: 'contain', focal_x: 0.5, focal_y: 0.5 },
      camera: { mode: 'static', max_zoom: 1.04 }, visualizer: { enabled: false }, progress: { enabled: false }, color_treatment: { mode: 'none' },
    })
  })
})
