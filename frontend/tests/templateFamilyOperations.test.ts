import { describe, expect, it } from 'vitest'
import type { CreationStateV3, VisualTemplate } from '../src/api/types'
import { createTemplateFamily, deleteUnusedTemplateFamily, familySynchronizationImpact, renameTemplateFamily, synchronizeTemplateFamily, ungroupTemplateFamily } from '../src/features/review/templateFamilyOperations'

const template = (id: string, aspect: '16:9' | '9:16', label = id): VisualTemplate => ({
  visual_template_id: id, label, canvas: { aspect_ratio: aspect }, background_image: null,
  geometry: { fit_mode: 'contain', focal_x: 0.5, focal_y: 0.5 }, camera: { mode: 'static', max_zoom: 1.04 },
  visualizer: { enabled: false, bar_count: 24, opacity: 0.65 }, progress: { enabled: false }, color_treatment: { mode: 'none' },
})

const state = (): CreationStateV3 => ({
  contract_version: 'wrld-creation-state/3.0', project_id: 'project-1', revision: 3, save_id: 'v3', preferred_short_duration_seconds: 45,
  visual_templates: [template('family-album', '16:9', 'Album member'), template('family-single', '16:9', 'Single member'), template('family-short', '9:16', 'Short member'), template('standalone-landscape', '16:9'), template('standalone-short', '9:16')],
  visual_template_families: [{ visual_template_family_id: 'family-existing', name: 'Existing', members: { album_visual_template_id: 'family-album', single_visual_template_id: 'family-single', short_visual_template_id: 'family-short' } }],
  albums: [{ album_plan_id: 'album-active', label: 'Album', status: 'active', assignments: [], visual_template_id: 'family-album' }],
  singles: [
    { single_id: 'single-active', asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), status: 'active', customized: false, approved: true, settings: {}, visual_template_id: 'family-single' },
    { single_id: 'single-archived', asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), status: 'archived', customized: false, approved: true, settings: {}, visual_template_id: 'family-single' },
  ],
  shorts: [{ short_id: 'short-active', asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), status: 'active', start_sample: 0, sample_count: 48_000, origin: 'manual', review_required: false, customized: false, approved: true, settings: {}, visual_template_id: 'family-short' }],
  state_digest: '3'.repeat(64), issues: [],
})

const uuids = (...values: string[]) => { let index = 0; return () => values[index++] }

describe('Creation v3 template family operations', () => {
  it('creates a scratch family atomically with neutral independent members and permits duplicate display names', () => {
    const source = state()
    const next = createTemplateFamily(source, { name: 'Existing', randomUuid: uuids('new-family', 'album', 'single', 'short') })
    expect(source.visual_template_families).toHaveLength(1)
    expect(next.visual_template_families).toHaveLength(2)
    const family = next.visual_template_families[1]
    expect(family).toEqual({ visual_template_family_id: 'visual-template-family-new-family', name: 'Existing', members: { album_visual_template_id: 'visual-template-album', single_visual_template_id: 'visual-template-single', short_visual_template_id: 'visual-template-short' } })
    const members = Object.values(family.members).map((id) => next.visual_templates.find((item) => item.visual_template_id === id)!)
    expect(new Set(members.map((item) => item.visual_template_id)).size).toBe(3)
    expect(members.map((item) => item.canvas.aspect_ratio)).toEqual(['16:9', '16:9', '9:16'])
    members.forEach((item) => expect(item).toMatchObject({ background_image: null, geometry: { fit_mode: 'contain', focal_x: 0.5, focal_y: 0.5 }, camera: { mode: 'static', max_zoom: 1.04 }, visualizer: { enabled: false }, progress: { enabled: false }, color_treatment: { mode: 'none' } }))
  })

  it.each([
    ['album', 'standalone-landscape', 'album_visual_template_id'],
    ['single', 'standalone-landscape', 'single_visual_template_id'],
    ['short', 'standalone-short', 'short_visual_template_id'],
  ] as const)('reuses a standalone %s identity and adapts independent copies', (role, sourceId, memberField) => {
    const source = state()
    const next = createTemplateFamily(source, { name: `From ${role}`, sourceTemplateId: sourceId, sourceRole: role, randomUuid: uuids(`${role}-family`, `${role}-copy-1`, `${role}-copy-2`) })
    const family = next.visual_template_families.at(-1)!
    expect(family.members[memberField]).toBe(sourceId)
    expect(next.visual_templates.filter((item) => Object.values(family.members).includes(item.visual_template_id)).map((item) => item.canvas.aspect_ratio).sort()).toEqual(['16:9', '16:9', '9:16'].sort())
    expect(next.albums).toEqual(source.albums)
    expect(next.singles).toEqual(source.singles)
    expect(next.shorts).toEqual(source.shorts)
  })

  it('rejects grouped sources, cross-role consumers, and generated identity collisions without mutating input', () => {
    const source = state()
    const snapshot = structuredClone(source)
    expect(() => createTemplateFamily(source, { name: 'Bad', sourceTemplateId: 'family-album', sourceRole: 'album', randomUuid: uuids('x') })).toThrow('already belongs')
    source.singles.push({ ...source.singles[0], single_id: 'single-cross-role', visual_template_id: 'standalone-landscape' })
    expect(() => createTemplateFamily(source, { name: 'Bad', sourceTemplateId: 'standalone-landscape', sourceRole: 'album', randomUuid: uuids('y') })).toThrow('Single consumers')
    const collision = structuredClone(snapshot)
    collision.visual_templates.push(template('visual-template-family-collision', '16:9'))
    const collisionSnapshot = structuredClone(collision)
    expect(() => createTemplateFamily(collision, { name: 'Bad', randomUuid: uuids('collision') })).toThrow('collides')
    expect(collision).toEqual(collisionSnapshot)
    expect(snapshot).toEqual(state())
  })

  it('synchronizes the complete approved configuration while preserving identities, labels, roles, and aspects', () => {
    const source = state()
    const edited = { ...structuredClone(source.visual_templates[2]), background_image: { asset_id: 'image-a', expected_sha256: 'b'.repeat(64) }, geometry: { fit_mode: 'cover' as const, focal_x: 0.2, focal_y: 0.8 }, camera: { mode: 'bounded' as const, max_zoom: 1.05 }, visualizer: { enabled: true, bar_count: 32, opacity: 0.7 }, progress: { enabled: true }, color_treatment: { mode: 'custom' as const, hex: '#123456', intensity: 0.2 } }
    const impact = familySynchronizationImpact(source, edited)
    expect(impact.changedTemplateIds).toEqual(['family-album', 'family-single', 'family-short'])
    expect(impact.consumers.map((item) => `${item.kind}:${item.status}`)).toEqual(['album:active', 'single:active', 'single:archived', 'short:active'])
    const next = synchronizeTemplateFamily(source, edited)
    expect(next.visual_templates.slice(0, 3).map((item) => item.visual_template_id)).toEqual(['family-album', 'family-single', 'family-short'])
    expect(next.visual_templates.slice(0, 3).map((item) => item.label)).toEqual(['Album member', 'Single member', 'Short member'])
    expect(next.visual_templates.slice(0, 3).map((item) => item.canvas.aspect_ratio)).toEqual(['16:9', '16:9', '9:16'])
    next.visual_templates.slice(0, 3).forEach((item) => expect(item).toMatchObject({ background_image: edited.background_image, geometry: edited.geometry, camera: edited.camera, visualizer: edited.visualizer, progress: edited.progress, color_treatment: edited.color_treatment }))
    expect(next.singles.map((item) => ({ status: item.status, approved: item.approved, customized: item.customized }))).toEqual([{ status: 'active', approved: false, customized: true }, { status: 'archived', approved: false, customized: true }])
    expect(next.shorts[0]).toMatchObject({ approved: false, customized: true })
  })

  it('rejects unknown future pixel fields instead of dropping them during synchronization', () => {
    const source = state()
    const edited = { ...source.visual_templates[2], future_effect: { enabled: true } } as VisualTemplate
    expect(() => synchronizeTemplateFamily(source, edited)).toThrow('cannot synchronize safely')
    expect(source.visual_templates[0]).not.toHaveProperty('future_effect')
  })

  it('renames and ungroups without changing member identities, consumers, or approvals', () => {
    const source = state()
    const renamed = renameTemplateFamily(source, 'family-existing', 'Duplicate allowed')
    expect(renamed.visual_template_families[0]).toMatchObject({ visual_template_family_id: 'family-existing', name: 'Duplicate allowed', members: source.visual_template_families[0].members })
    expect(renamed.singles).toEqual(source.singles)
    const ungrouped = ungroupTemplateFamily(renamed, 'family-existing')
    expect(ungrouped.visual_template_families).toEqual([])
    expect(ungrouped.visual_templates).toEqual(source.visual_templates)
    expect(ungrouped.albums).toEqual(source.albums)
    expect(ungrouped.singles).toEqual(source.singles)
    expect(ungrouped.shorts).toEqual(source.shorts)
  })

  it('deletes all three members only when active and archived consumers are absent', () => {
    const source = state()
    expect(() => deleteUnusedTemplateFamily(source, 'family-existing')).toThrow('4 active or archived compositions')
    const unused = { ...source, albums: source.albums.map((item) => ({ ...item, visual_template_id: null })), singles: source.singles.map((item) => ({ ...item, visual_template_id: null })), shorts: source.shorts.map((item) => ({ ...item, visual_template_id: null })) }
    const deleted = deleteUnusedTemplateFamily(unused, 'family-existing')
    expect(deleted.visual_template_families).toEqual([])
    expect(deleted.visual_templates.map((item) => item.visual_template_id)).toEqual(['standalone-landscape', 'standalone-short'])
    expect(deleted.albums).toEqual(unused.albums)
  })
})
