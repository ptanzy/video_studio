import type { CreationStateV3, VisualTemplate, VisualTemplateFamily } from '../../api/types'
import { familyMemberships, familyVersions, ROLE_LABEL, type TemplateRole } from './templateFamilies'

const ROLES: TemplateRole[] = ['album', 'single', 'short']
const ROLE_ASPECT: Record<TemplateRole, '16:9' | '9:16'> = { album: '16:9', single: '16:9', short: '9:16' }
const MEMBER_FIELD: Record<TemplateRole, keyof VisualTemplateFamily['members']> = {
  album: 'album_visual_template_id', single: 'single_visual_template_id', short: 'short_visual_template_id',
}
const ROOT_FIELDS = ['background_image', 'camera', 'canvas', 'color_treatment', 'geometry', 'label', 'progress', 'visual_template_id', 'visualizer']

export interface FamilyConsumer {
  kind: TemplateRole
  id: string
  status: 'active' | 'archived'
  templateId: string
  approved?: boolean
}

export interface FamilySyncImpact {
  changedTemplateIds: string[]
  consumers: FamilyConsumer[]
}

const exactKeys = (value: object, expected: string[]) => {
  const actual = Object.keys(value).sort()
  const wanted = [...expected].sort()
  return actual.length === wanted.length && actual.every((key, index) => key === wanted[index])
}

export const hasApprovedVisualTemplateShape = (template: VisualTemplate): boolean => {
  if (!exactKeys(template, ROOT_FIELDS)) return false
  if (!exactKeys(template.canvas, ['aspect_ratio'])) return false
  if (template.background_image !== null && !exactKeys(template.background_image, ['asset_id', 'expected_sha256'])) return false
  if (!exactKeys(template.geometry, ['fit_mode', 'focal_x', 'focal_y'])) return false
  if (!exactKeys(template.camera, ['max_zoom', 'mode'])) return false
  if (!exactKeys(template.visualizer, ['bar_count', 'enabled', 'opacity'])) return false
  if (!exactKeys(template.progress, ['enabled'])) return false
  return template.color_treatment.mode === 'none'
    ? exactKeys(template.color_treatment, ['mode'])
    : exactKeys(template.color_treatment, ['hex', 'intensity', 'mode'])
}

export const visualConfiguration = (template: VisualTemplate) => ({
  background_image: structuredClone(template.background_image),
  geometry: structuredClone(template.geometry),
  camera: structuredClone(template.camera),
  visualizer: structuredClone(template.visualizer),
  progress: structuredClone(template.progress),
  color_treatment: structuredClone(template.color_treatment),
})

const withVisualConfiguration = (destination: VisualTemplate, source: VisualTemplate): VisualTemplate => ({
  ...destination,
  ...visualConfiguration(source),
})

const documentIdentities = (state: CreationStateV3) => {
  const identities = new Set<string>()
  state.visual_templates.forEach((item) => identities.add(item.visual_template_id))
  state.visual_template_families.forEach((item) => identities.add(item.visual_template_family_id))
  state.albums.forEach((album) => { identities.add(album.album_plan_id); album.assignments.forEach((item) => identities.add(item.assignment_id)) })
  state.singles.forEach((item) => identities.add(item.single_id))
  state.shorts.forEach((item) => identities.add(item.short_id))
  return identities
}

const allocateIdentity = (prefix: string, identities: Set<string>, randomUuid: () => string) => {
  const identity = `${prefix}-${randomUuid()}`
  if (identities.has(identity)) throw new Error(`Generated identity ${identity} collides with existing Creation work.`)
  identities.add(identity)
  return identity
}

const neutralTemplate = (templateId: string, label: string, role: TemplateRole): VisualTemplate => ({
  visual_template_id: templateId,
  label: Array.from(`${label} — ${ROLE_LABEL[role]}`).slice(0, 128).join(''),
  canvas: { aspect_ratio: ROLE_ASPECT[role] },
  background_image: null,
  geometry: { fit_mode: 'contain', focal_x: 0.5, focal_y: 0.5 },
  camera: { mode: 'static', max_zoom: 1.04 },
  visualizer: { enabled: false, bar_count: 24, opacity: 0.65 },
  progress: { enabled: false },
  color_treatment: { mode: 'none' },
})

const consumersOfTemplate = (state: CreationStateV3, templateId: string): FamilyConsumer[] => [
  ...state.albums.filter((item) => item.visual_template_id === templateId).map((item) => ({ kind: 'album' as const, id: item.album_plan_id, status: item.status, templateId })),
  ...state.singles.filter((item) => item.visual_template_id === templateId).map((item) => ({ kind: 'single' as const, id: item.single_id, status: item.status, templateId, approved: item.approved })),
  ...state.shorts.filter((item) => item.visual_template_id === templateId).map((item) => ({ kind: 'short' as const, id: item.short_id, status: item.status, templateId, approved: item.approved })),
]

export const familyConsumers = (state: CreationStateV3, family: VisualTemplateFamily): FamilyConsumer[] => familyVersions(state, family).flatMap((version) => consumersOfTemplate(state, version.templateId))

export const createTemplateFamily = (state: CreationStateV3, options: { name: string; sourceTemplateId?: string; sourceRole?: TemplateRole; randomUuid?: () => string }): CreationStateV3 => {
  if (!options.name.trim() || Array.from(options.name).length > 128) throw new Error('Family name must contain 1 through 128 characters.')
  const randomUuid = options.randomUuid ?? crypto.randomUUID.bind(crypto)
  const identities = documentIdentities(state)
  const familyId = allocateIdentity('visual-template-family', identities, randomUuid)
  const source = options.sourceTemplateId ? state.visual_templates.find((item) => item.visual_template_id === options.sourceTemplateId) : undefined
  if (options.sourceTemplateId && !source) throw new Error('The selected standalone template no longer exists.')
  if (source && !options.sourceRole) throw new Error('The current output type is required when grouping a standalone template.')
  if (source && familyMemberships(state, source.visual_template_id).length) throw new Error('The selected template already belongs to a family.')
  if (source && source.canvas.aspect_ratio !== ROLE_ASPECT[options.sourceRole!]) throw new Error(`The selected template is not compatible with the ${ROLE_LABEL[options.sourceRole!]} role.`)
  if (source && (options.sourceRole === 'album' || options.sourceRole === 'single')) {
    const opposite = options.sourceRole === 'album' ? 'single' : 'album'
    const oppositeConsumers = consumersOfTemplate(state, source.visual_template_id).filter((item) => item.kind === opposite)
    if (oppositeConsumers.length) throw new Error(`This standalone template still has ${ROLE_LABEL[opposite]} consumers. Reassign them explicitly before creating the family.`)
  }

  const generated: VisualTemplate[] = []
  const members = {} as VisualTemplateFamily['members']
  for (const role of ROLES) {
    if (source && role === options.sourceRole) {
      members[MEMBER_FIELD[role]] = source.visual_template_id
      continue
    }
    const templateId = allocateIdentity('visual-template', identities, randomUuid)
    const template = source
      ? { ...structuredClone(source), visual_template_id: templateId, canvas: { aspect_ratio: ROLE_ASPECT[role] } }
      : neutralTemplate(templateId, options.name, role)
    generated.push(template)
    members[MEMBER_FIELD[role]] = templateId
  }
  return {
    ...state,
    visual_templates: [...state.visual_templates, ...generated],
    visual_template_families: [...state.visual_template_families, { visual_template_family_id: familyId, name: options.name, members }],
  }
}

export const familySynchronizationImpact = (state: CreationStateV3, sourceTemplate: VisualTemplate): FamilySyncImpact => {
  const memberships = familyMemberships(state, sourceTemplate.visual_template_id)
  if (memberships.length !== 1) throw new Error('All Three Types requires one valid family member.')
  const versions = familyVersions(state, memberships[0].family)
  if (!hasApprovedVisualTemplateShape(sourceTemplate) || versions.some((item) => !item.template || !hasApprovedVisualTemplateShape(item.template))) {
    throw new Error('The family contains a visual field that the current All Three Types contract cannot synchronize safely.')
  }
  const configuration = JSON.stringify(visualConfiguration(sourceTemplate))
  const changedTemplateIds = versions.filter((item) => JSON.stringify(visualConfiguration(item.template!)) !== configuration).map((item) => item.templateId)
  return { changedTemplateIds, consumers: changedTemplateIds.flatMap((templateId) => consumersOfTemplate(state, templateId)) }
}

export const synchronizeTemplateFamily = (state: CreationStateV3, sourceTemplate: VisualTemplate): CreationStateV3 => {
  const impact = familySynchronizationImpact(state, sourceTemplate)
  if (!impact.changedTemplateIds.length) return state
  const changed = new Set(impact.changedTemplateIds)
  const templates = state.visual_templates.map((item) => changed.has(item.visual_template_id) ? withVisualConfiguration(item, sourceTemplate) : item)
  return {
    ...state,
    visual_templates: templates,
    singles: state.singles.map((item) => item.visual_template_id && changed.has(item.visual_template_id) ? { ...item, customized: true, approved: false } : item),
    shorts: state.shorts.map((item) => item.visual_template_id && changed.has(item.visual_template_id) ? { ...item, customized: true, approved: false } : item),
  }
}

export const renameTemplateFamily = (state: CreationStateV3, familyId: string, name: string): CreationStateV3 => {
  if (!name.trim() || Array.from(name).length > 128) throw new Error('Family name must contain 1 through 128 characters.')
  const family = state.visual_template_families.find((item) => item.visual_template_family_id === familyId)
  if (!family) throw new Error('The selected template family no longer exists.')
  if (family.name === name) return state
  return { ...state, visual_template_families: state.visual_template_families.map((item) => item.visual_template_family_id === familyId ? { ...item, name } : item) }
}

export const ungroupTemplateFamily = (state: CreationStateV3, familyId: string): CreationStateV3 => {
  if (!state.visual_template_families.some((item) => item.visual_template_family_id === familyId)) throw new Error('The selected template family no longer exists.')
  return { ...state, visual_template_families: state.visual_template_families.filter((item) => item.visual_template_family_id !== familyId) }
}

export const deleteUnusedTemplateFamily = (state: CreationStateV3, familyId: string): CreationStateV3 => {
  const family = state.visual_template_families.find((item) => item.visual_template_family_id === familyId)
  if (!family) throw new Error('The selected template family no longer exists.')
  const consumers = familyConsumers(state, family)
  if (consumers.length) throw new Error(`The family cannot be deleted because ${consumers.length} active or archived composition${consumers.length === 1 ? '' : 's'} still reference its members.`)
  const memberIds = new Set(familyVersions(state, family).map((item) => item.templateId))
  return {
    ...state,
    visual_templates: state.visual_templates.filter((item) => !memberIds.has(item.visual_template_id)),
    visual_template_families: state.visual_template_families.filter((item) => item.visual_template_family_id !== familyId),
  }
}
