import { describe, expect, it } from 'vitest'
import type { VisualConfiguration } from '../src/api/generated/creation-state-v4'
import type { CreationStateV2, CreationStateV3, CreationStateV4, VisualTemplate } from '../src/api/types'
import {
  analyzeLegacyTemplates,
  applyLegacyCleanup,
  applyTemplateToComposition,
  configurationFromTemplate,
  createTemplateFamilyV4,
  deleteStandaloneTemplate,
  duplicateStandaloneTemplate,
  migrateCreationStateV3ToV4,
  migrateCreationStateV2ToV3,
  preflightV3Upgrade,
  saveCompositionAsTemplate,
  updateCompositionConfiguration,
  updateTemplateFromComposition,
} from '../src/features/review/creationV4'

const config = (aspect: '16:9' | '9:16', focalX = 0.5): VisualConfiguration => ({
  canvas: { aspect_ratio: aspect }, background_image: null,
  geometry: { fit_mode: 'contain', focal_x: focalX, focal_y: 0.5 }, camera: { mode: 'static', max_zoom: 1.04 },
  visualizer: { enabled: false, bar_count: 24, opacity: 0.65 }, progress: { enabled: false }, color_treatment: { mode: 'none' },
})
const template = (id: string, label: string, aspect: '16:9' | '9:16', focalX = 0.5): VisualTemplate => ({ visual_template_id: id, label, ...config(aspect, focalX) })
const v4 = (): CreationStateV4 => ({
  contract_version: 'wrld-creation-state/4.0', project_id: 'project-a', revision: 4, save_id: 'save-a', preferred_short_duration_seconds: 45,
  visual_templates: [template('family-album', 'Family album', '16:9'), template('family-single', 'Family single', '16:9'), template('family-short', 'Family short', '9:16'), template('standalone-short', 'Standalone short', '9:16', 0.2)],
  visual_template_families: [{ visual_template_family_id: 'family-a', name: 'Family A', members: { album_visual_template_id: 'family-album', single_visual_template_id: 'family-single', short_visual_template_id: 'family-short' } }],
  albums: [{ album_plan_id: 'album-a', label: 'Album', status: 'active', assignments: [], visual_configuration: config('16:9'), source_visual_template_id: 'family-album' }],
  singles: [{ single_id: 'single-a', asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), status: 'active', customized: false, approved: true, settings: { preserve: true }, visual_configuration: config('16:9'), source_visual_template_id: 'family-single' }],
  shorts: [
    { short_id: 'short-a', asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), status: 'active', start_sample: 0, sample_count: 2_160_000, origin: 'manual', review_required: false, customized: false, approved: true, settings: { preserve: 'a' }, visual_configuration: config('9:16'), source_visual_template_id: 'family-short' },
    { short_id: 'short-b', asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), status: 'archived', start_sample: 0, sample_count: 2_160_000, origin: 'manual', review_required: false, customized: false, approved: true, settings: { preserve: 'b' }, visual_configuration: config('9:16'), source_visual_template_id: 'family-short' },
  ], state_digest: '0'.repeat(64), issues: [],
})
const v3 = (): CreationStateV3 => {
  const source = v4()
  const legacy = (item: object, templateId: string | null) => { const value = structuredClone(item) as Record<string, unknown>; delete value.visual_configuration; delete value.source_visual_template_id; value.visual_template_id = templateId; return value }
  return {
    contract_version: 'wrld-creation-state/3.0', project_id: source.project_id, revision: source.revision, save_id: source.save_id, preferred_short_duration_seconds: 45,
    visual_templates: source.visual_templates, visual_template_families: source.visual_template_families,
    albums: source.albums.map((item) => legacy(item, item.source_visual_template_id)) as unknown as CreationStateV3['albums'],
    singles: source.singles.map((item) => legacy(item, item.source_visual_template_id)) as unknown as CreationStateV3['singles'],
    shorts: source.shorts.map((item) => legacy(item, item.source_visual_template_id)) as unknown as CreationStateV3['shorts'],
    state_digest: source.state_digest, issues: [],
  }
}

describe('Creation v4 composition-owned operations', () => {
  it('edits one Short without changing another Short, its source template, identities, settings, or unrelated approvals', () => {
    const state = v4(); const snapshot = structuredClone(state)
    const next = updateCompositionConfiguration(state, { kind: 'short', id: 'short-a' }, config('9:16', 0.8))
    expect(next.shorts[0]).toMatchObject({ approved: false, customized: true, settings: { preserve: 'a' }, visual_configuration: { geometry: { focal_x: 0.8 } } })
    expect(next.shorts[1]).toEqual(snapshot.shorts[1])
    expect(next.visual_templates).toEqual(snapshot.visual_templates)
    expect(next.singles).toEqual(snapshot.singles)
    expect(next.albums).toEqual(snapshot.albums)
  })

  it('preserves approval and object identity for a pixel-equivalent no-op', () => {
    const state = v4()
    expect(updateCompositionConfiguration(state, { kind: 'short', id: 'short-a' }, structuredClone(state.shorts[0].visual_configuration))).toBe(state)
  })

  it('isolates Album and Single edits and invalidates only the edited Single approval', () => {
    const state = v4()
    const album = updateCompositionConfiguration(state, { kind: 'album', id: 'album-a' }, config('16:9', 0.6))
    expect(album.albums[0].visual_configuration.geometry.focal_x).toBe(0.6)
    expect(album.singles).toEqual(state.singles)
    const single = updateCompositionConfiguration(state, { kind: 'single', id: 'single-a' }, config('16:9', 0.7))
    expect(single.singles[0]).toMatchObject({ approved: false, customized: true, visual_configuration: { geometry: { focal_x: 0.7 } } })
    expect(single.albums).toEqual(state.albums)
    expect(single.shorts).toEqual(state.shorts)
  })

  it('applies only the exact family role or a compatible standalone and updates provenance without a live dependency', () => {
    const state = v4()
    expect(() => applyTemplateToComposition(state, { kind: 'single', id: 'single-a' }, 'family-album')).toThrow(/not compatible/i)
    const applied = applyTemplateToComposition(state, { kind: 'short', id: 'short-a' }, 'standalone-short')
    expect(applied.shorts[0]).toMatchObject({ source_visual_template_id: 'standalone-short', approved: false, visual_configuration: { geometry: { focal_x: 0.2 } } })
    expect(applied.shorts[1]).toEqual(state.shorts[1])
    expect(applied.visual_templates).toEqual(state.visual_templates)
    const edited = updateCompositionConfiguration(applied, { kind: 'short', id: 'short-a' }, config('9:16', 0.9))
    expect(edited.visual_templates.find((item) => item.visual_template_id === 'standalone-short')?.geometry.focal_x).toBe(0.2)
  })

  it('preserves approval for a pixel-equivalent Apply while updating historical provenance', () => {
    const state = v4()
    const equivalent = { ...structuredClone(state.visual_templates.find((item) => item.visual_template_id === 'family-short')!), visual_template_id: 'equivalent-short', label: 'Equivalent' }
    state.visual_templates.push(equivalent)
    const applied = applyTemplateToComposition(state, { kind: 'short', id: 'short-a' }, equivalent.visual_template_id)
    expect(applied.shorts[0]).toMatchObject({ approved: true, customized: false, source_visual_template_id: 'equivalent-short' })
  })

  it('updates a current family member or all three templates without retroactively changing compositions', () => {
    const state = v4(); state.shorts[0].visual_configuration = config('9:16', 0.7)
    const current = updateTemplateFromComposition(state, { kind: 'short', id: 'short-a' }, 'family-short', 'current')
    expect(current.visual_templates.find((item) => item.visual_template_id === 'family-short')?.geometry.focal_x).toBe(0.7)
    expect(current.visual_templates.find((item) => item.visual_template_id === 'family-album')?.geometry.focal_x).toBe(0.5)
    expect(current.shorts).toEqual(state.shorts)
    const all = updateTemplateFromComposition(state, { kind: 'short', id: 'short-a' }, 'family-short', 'all')
    expect(all.visual_templates.filter((item) => item.visual_template_id.startsWith('family-')).map((item) => item.geometry.focal_x)).toEqual([0.7, 0.7, 0.7])
    expect(all.visual_templates.find((item) => item.visual_template_id === 'family-short')?.canvas.aspect_ratio).toBe('9:16')
    expect(all.visual_templates.find((item) => item.visual_template_id === 'family-album')?.canvas.aspect_ratio).toBe('16:9')
    expect(all.shorts).toEqual(state.shorts)
  })

  it('rejects unsupported future pixel fields instead of dropping them during template update', () => {
    const state = v4()
    state.shorts[0].visual_configuration = { ...state.shorts[0].visual_configuration, future_pixel_field: true } as unknown as VisualConfiguration
    expect(() => updateTemplateFromComposition(state, { kind: 'short', id: 'short-a' }, 'family-short', 'current')).toThrow(/unsupported visual fields/i)
  })

  it('creates, duplicates, and deletes standalone templates without assigning or changing compositions', () => {
    const state = v4(); state.shorts[0].source_visual_template_id = null
    const created = saveCompositionAsTemplate(state, { kind: 'short', id: 'short-a' }, 'New preset', () => 'new-id')
    expect(created.visual_templates.at(-1)).toEqual({ visual_template_id: 'visual-template-new-id', label: 'New preset', ...state.shorts[0].visual_configuration })
    expect(created.shorts).toEqual(state.shorts)
    const duplicate = duplicateStandaloneTemplate(created, 'visual-template-new-id', 'Copy', () => 'copy-id')
    expect(duplicate.visual_templates.at(-1)?.visual_template_id).toBe('visual-template-copy-id')
    expect(deleteStandaloneTemplate(duplicate, 'visual-template-copy-id').shorts).toEqual(state.shorts)
    expect(() => deleteStandaloneTemplate(state, 'family-short')).toThrow(/family members/i)
  })

  it('creates a complete three-role family with stable, unique identities', () => {
    const ids = ['album-id', 'single-id', 'short-id', 'family-id']; let index = 0
    const next = createTemplateFamilyV4(v4(), 'New family', undefined, undefined, () => ids[index++])
    const family = next.visual_template_families.at(-1)!
    expect(family).toMatchObject({ visual_template_family_id: 'visual-template-family-family-id', name: 'New family' })
    expect(Object.values(family.members)).toEqual(['visual-template-album-id', 'visual-template-single-id', 'visual-template-short-id'])
    expect(next.visual_templates.slice(-3).map((item) => item.canvas.aspect_ratio)).toEqual(['16:9', '16:9', '9:16'])
  })

  it('creates a family from an explicitly typed standalone without reassigning compositions', () => {
    const state = v4(); const ids = ['album-id', 'single-id', 'family-id']; let index = 0
    const next = createTemplateFamilyV4(state, 'Portrait family', 'standalone-short', 'short', () => ids[index++])
    const family = next.visual_template_families.at(-1)!
    expect(family.members.short_visual_template_id).toBe('standalone-short')
    expect(next.shorts).toEqual(state.shorts)
    expect(next.visual_templates.find((item) => item.visual_template_id === 'standalone-short')).toEqual(state.visual_templates.find((item) => item.visual_template_id === 'standalone-short'))
  })
})

describe('Creation v3 upgrade and v4 cleanup', () => {
  it('performs the deterministic v2-to-v3 intermediate transition without changing original identities or approvals', async () => {
    const sourceV3 = v3()
    const source = structuredClone(sourceV3) as unknown as CreationStateV2
    source.contract_version = 'wrld-creation-state/2.0'
    delete (source as CreationStateV2 & { visual_template_families?: unknown }).visual_template_families
    const before = structuredClone(source)
    const first = await migrateCreationStateV2ToV3(source)
    const second = await migrateCreationStateV2ToV3(source)
    expect(first).toEqual(second)
    expect(first.visual_template_families).toHaveLength(source.visual_templates.length)
    expect(first.shorts.map((item) => [item.short_id, item.approved])).toEqual(source.shorts.map((item) => [item.short_id, item.approved]))
    expect(source).toEqual(before)
  })

  it('preflights and migrates every target deterministically while preserving stable data', () => {
    const source = v3(); const before = structuredClone(source)
    expect(preflightV3Upgrade(source)).toMatchObject({ canUpgrade: true, albums: 1, singles: 1, shorts: 2, resolvable: 4 })
    const result = migrateCreationStateV3ToV4(source)
    expect(result.contract_version).toBe('wrld-creation-state/4.0')
    expect(result.shorts[0]).toMatchObject({ short_id: 'short-a', approved: true, settings: { preserve: 'a' }, source_visual_template_id: 'family-short', visual_configuration: configurationFromTemplate(source.visual_templates[2]) })
    expect(source).toEqual(before)
    expect(migrateCreationStateV3ToV4(source)).toEqual(result)
  })

  it('diagnoses null and dangling target references and rejects the upgrade atomically', () => {
    const source = v3(); source.shorts[0].visual_template_id = null; source.singles[0].visual_template_id = 'missing-template'
    const before = structuredClone(source); const preflight = preflightV3Upgrade(source)
    expect(preflight).toMatchObject({ canUpgrade: false, nullReferences: [{ kind: 'short', id: 'short-a', reason: 'null' }], danglingReferences: [{ kind: 'single', id: 'single-a', reason: 'dangling' }] })
    expect(() => migrateCreationStateV3ToV4(source)).toThrow(/cannot be migrated losslessly/i)
    expect(source).toEqual(before)
  })

  it('protects family members, rejects unauthorized or stale cleanup, and removes only proven generated artifacts', async () => {
    const state = v4(); const short = state.shorts[0]
    const bytes = new TextEncoder().encode(`${state.project_id}\0${short.short_id}\0wrld-creation-state/2.0`)
    const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))).map((item) => item.toString(16).padStart(2, '0')).join('')
    const generatedId = `visual-template-${digest.slice(0, 32)}`
    state.visual_templates.push({ visual_template_id: generatedId, label: `Short visual ${short.short_id}`, ...structuredClone(short.visual_configuration) })
    state.shorts[0].source_visual_template_id = generatedId
    const plan = await analyzeLegacyTemplates(state)
    expect(plan.candidates.find((item) => item.templateId === generatedId)?.classification).toBe('PROVEN_DISPOSABLE')
    expect(plan.candidates.find((item) => item.templateId === 'family-short')?.classification).toBe('RETAIN')
    await expect(applyLegacyCleanup(state, plan, false)).rejects.toThrow(/explicit authorization/i)
    await expect(applyLegacyCleanup({ ...state, revision: 5 }, plan, true)).rejects.toThrow(/stale/i)
    const cleaned = await applyLegacyCleanup(state, plan, true)
    expect(cleaned.visual_templates.some((item) => item.visual_template_id === generatedId)).toBe(false)
    expect(cleaned.shorts).toEqual(state.shorts)
    expect(cleaned.visual_templates.some((item) => item.visual_template_id === 'family-short')).toBe(true)
  })
})
