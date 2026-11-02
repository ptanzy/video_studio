import type { VisualConfiguration } from '../../api/generated/creation-state-v4'
import type { CreationStateV2, CreationStateV3, CreationStateV4, VisualTemplate, VisualTemplateFamily } from '../../api/types'
import { familyForTemplate, familyVersions, ROLE_LABEL, type TemplateRole } from './templateFamilies'

export type CompositionTarget = { kind: TemplateRole; id: string }
export type TemplateUpdateScope = 'current' | 'all'

const ROLE_ASPECT: Record<TemplateRole, '16:9' | '9:16'> = { album: '16:9', single: '16:9', short: '9:16' }
const CONFIGURATION_FIELDS = ['background_image', 'camera', 'canvas', 'color_treatment', 'geometry', 'progress', 'visualizer']

const exactKeys = (value: object, expected: string[]) => {
  const actual = Object.keys(value).sort()
  const wanted = [...expected].sort()
  return actual.length === wanted.length && actual.every((key, index) => key === wanted[index])
}

export const hasApprovedVisualConfigurationShape = (value: unknown): value is VisualConfiguration => {
  if (!value || typeof value !== 'object' || !exactKeys(value, CONFIGURATION_FIELDS)) return false
  const item = value as VisualConfiguration
  if (!exactKeys(item.canvas, ['aspect_ratio'])) return false
  if (item.background_image !== null && !exactKeys(item.background_image, ['asset_id', 'expected_sha256'])) return false
  if (!exactKeys(item.geometry, ['fit_mode', 'focal_x', 'focal_y'])) return false
  if (!exactKeys(item.camera, ['max_zoom', 'mode'])) return false
  if (!exactKeys(item.visualizer, ['bar_count', 'enabled', 'opacity'])) return false
  if (!exactKeys(item.progress, ['enabled'])) return false
  return item.color_treatment.mode === 'none'
    ? exactKeys(item.color_treatment, ['mode'])
    : exactKeys(item.color_treatment, ['hex', 'intensity', 'mode'])
}

export const configurationFromTemplate = (template: VisualTemplate): VisualConfiguration => ({
  canvas: structuredClone(template.canvas),
  background_image: structuredClone(template.background_image),
  geometry: structuredClone(template.geometry),
  camera: structuredClone(template.camera),
  visualizer: structuredClone(template.visualizer),
  progress: structuredClone(template.progress),
  color_treatment: structuredClone(template.color_treatment),
})

export const configurationsEquivalent = (left: unknown, right: unknown): boolean => (
  hasApprovedVisualConfigurationShape(left)
  && hasApprovedVisualConfigurationShape(right)
  && JSON.stringify(left) === JSON.stringify(right)
)

const templateFromConfiguration = (template: VisualTemplate, configuration: VisualConfiguration): VisualTemplate => ({
  ...template,
  ...structuredClone(configuration),
})

export const compositionFor = (state: CreationStateV4, target: CompositionTarget) => {
  if (target.kind === 'album') return state.albums.find((item) => item.album_plan_id === target.id)
  if (target.kind === 'single') return state.singles.find((item) => item.single_id === target.id)
  return state.shorts.find((item) => item.short_id === target.id)
}

const replaceComposition = (
  state: CreationStateV4,
  target: CompositionTarget,
  update: (item: CreationStateV4['albums'][number] | CreationStateV4['singles'][number] | CreationStateV4['shorts'][number]) => CreationStateV4['albums'][number] | CreationStateV4['singles'][number] | CreationStateV4['shorts'][number],
): CreationStateV4 => {
  if (target.kind === 'album') return { ...state, albums: state.albums.map((item) => item.album_plan_id === target.id ? update(item) as CreationStateV4['albums'][number] : item) }
  if (target.kind === 'single') return { ...state, singles: state.singles.map((item) => item.single_id === target.id ? update(item) as CreationStateV4['singles'][number] : item) }
  return { ...state, shorts: state.shorts.map((item) => item.short_id === target.id ? update(item) as CreationStateV4['shorts'][number] : item) }
}

export const updateCompositionConfiguration = (
  state: CreationStateV4,
  target: CompositionTarget,
  configuration: VisualConfiguration,
): CreationStateV4 => {
  if (!hasApprovedVisualConfigurationShape(configuration) || configuration.canvas.aspect_ratio !== ROLE_ASPECT[target.kind]) {
    throw new Error(`The ${target.kind} visual configuration is incomplete or has the wrong aspect ratio.`)
  }
  const current = compositionFor(state, target)
  if (!current) throw new Error('The selected composition no longer exists.')
  if (configurationsEquivalent(current.visual_configuration, configuration)) return state
  return replaceComposition(state, target, (item) => ({
    ...item,
    visual_configuration: structuredClone(configuration),
    ...(target.kind === 'album' ? {} : { customized: true, approved: false }),
  }))
}

export const compatibleTemplate = (state: CreationStateV4, template: VisualTemplate, role: TemplateRole): boolean => {
  const membership = familyForTemplate(state, template.visual_template_id)
  if (membership) return membership.role === role
  return template.canvas.aspect_ratio === ROLE_ASPECT[role]
}

export const applyTemplateToComposition = (
  state: CreationStateV4,
  target: CompositionTarget,
  templateId: string,
): CreationStateV4 => {
  const template = state.visual_templates.find((item) => item.visual_template_id === templateId)
  if (!template || !compatibleTemplate(state, template, target.kind)) throw new Error('The selected template is not compatible with this composition role.')
  const current = compositionFor(state, target)
  if (!current) throw new Error('The selected composition no longer exists.')
  const configuration = configurationFromTemplate(template)
  const pixelsChanged = !configurationsEquivalent(current.visual_configuration, configuration)
  if (!pixelsChanged && current.source_visual_template_id === templateId) return state
  return replaceComposition(state, target, (item) => ({
    ...item,
    visual_configuration: configuration,
    source_visual_template_id: templateId,
    ...(target.kind === 'album' || !pixelsChanged ? {} : { customized: true, approved: false }),
  }))
}

export const updateTemplateFromComposition = (
  state: CreationStateV4,
  target: CompositionTarget,
  templateId: string,
  scope: TemplateUpdateScope,
): CreationStateV4 => {
  const composition = compositionFor(state, target)
  const destination = state.visual_templates.find((item) => item.visual_template_id === templateId)
  if (!composition || !destination) throw new Error('The composition or destination template no longer exists.')
  if (!compatibleTemplate(state, destination, target.kind)) throw new Error('The destination template is not compatible with this composition role.')
  if (!hasApprovedVisualConfigurationShape(composition.visual_configuration)) throw new Error('The composition contains unsupported visual fields.')
  if (scope === 'current') {
    const updated = templateFromConfiguration(destination, composition.visual_configuration)
    if (JSON.stringify(updated) === JSON.stringify(destination)) return state
    return { ...state, visual_templates: state.visual_templates.map((item) => item.visual_template_id === templateId ? updated : item) }
  }
  const membership = familyForTemplate(state, templateId)
  if (!membership) throw new Error('All Three Types requires a valid family member destination.')
  const versions = familyVersions(state, membership.family)
  if (versions.some((item) => !item.template)) throw new Error('The family contains a missing template member.')
  const updatedTemplates = new Map(versions.map((item) => {
    const configuration = structuredClone(composition.visual_configuration)
    configuration.canvas.aspect_ratio = ROLE_ASPECT[item.role]
    return [item.templateId, templateFromConfiguration(item.template!, configuration)]
  }))
  if (versions.every((item) => JSON.stringify(item.template) === JSON.stringify(updatedTemplates.get(item.templateId)))) return state
  return { ...state, visual_templates: state.visual_templates.map((item) => updatedTemplates.get(item.visual_template_id) ?? item) }
}

const documentIdentities = (state: CreationStateV4) => new Set([
  ...state.visual_templates.map((item) => item.visual_template_id),
  ...state.visual_template_families.map((item) => item.visual_template_family_id),
  ...state.albums.flatMap((item) => [item.album_plan_id, ...item.assignments.map((assignment) => assignment.assignment_id)]),
  ...state.singles.map((item) => item.single_id),
  ...state.shorts.map((item) => item.short_id),
])

const allocateId = (state: CreationStateV4, prefix: string, randomUuid: () => string = () => crypto.randomUUID()) => {
  const id = `${prefix}-${randomUuid()}`
  if (documentIdentities(state).has(id)) throw new Error(`Generated identity ${id} collides with existing Creation work.`)
  return id
}

export const saveCompositionAsTemplate = (
  state: CreationStateV4,
  target: CompositionTarget,
  name: string,
  randomUuid?: () => string,
): CreationStateV4 => {
  if (!name.trim() || Array.from(name).length > 128) throw new Error('Template name must contain 1 through 128 characters.')
  const composition = compositionFor(state, target)
  if (!composition || !hasApprovedVisualConfigurationShape(composition.visual_configuration)) throw new Error('The selected composition has no supported visual configuration.')
  const template: VisualTemplate = {
    visual_template_id: allocateId(state, 'visual-template', randomUuid),
    label: name.trim(),
    ...structuredClone(composition.visual_configuration),
  }
  return { ...state, visual_templates: [...state.visual_templates, template] }
}

export const renameStandaloneTemplate = (state: CreationStateV4, templateId: string, name: string): CreationStateV4 => {
  if (!name.trim() || Array.from(name).length > 128) throw new Error('Template name must contain 1 through 128 characters.')
  if (familyForTemplate(state, templateId)) throw new Error('Family members are renamed through family/template member controls.')
  if (!state.visual_templates.some((item) => item.visual_template_id === templateId)) throw new Error('The standalone template no longer exists.')
  return { ...state, visual_templates: state.visual_templates.map((item) => item.visual_template_id === templateId ? { ...item, label: name.trim() } : item) }
}

export const duplicateStandaloneTemplate = (state: CreationStateV4, templateId: string, name: string, randomUuid?: () => string): CreationStateV4 => {
  const source = state.visual_templates.find((item) => item.visual_template_id === templateId)
  if (!source || familyForTemplate(state, templateId)) throw new Error('Only an existing standalone template can be duplicated.')
  if (!name.trim() || Array.from(name).length > 128) throw new Error('Template name must contain 1 through 128 characters.')
  const copy = { ...structuredClone(source), visual_template_id: allocateId(state, 'visual-template', randomUuid), label: name.trim() }
  return { ...state, visual_templates: [...state.visual_templates, copy] }
}

export const deleteStandaloneTemplate = (state: CreationStateV4, templateId: string): CreationStateV4 => {
  if (familyForTemplate(state, templateId)) throw new Error('Family members cannot be deleted as standalone templates.')
  if (!state.visual_templates.some((item) => item.visual_template_id === templateId)) throw new Error('The standalone template no longer exists.')
  return { ...state, visual_templates: state.visual_templates.filter((item) => item.visual_template_id !== templateId) }
}

const neutralConfiguration = (role: TemplateRole): VisualConfiguration => ({
  canvas: { aspect_ratio: ROLE_ASPECT[role] },
  background_image: null,
  geometry: { fit_mode: 'contain', focal_x: 0.5, focal_y: 0.5 },
  camera: { mode: 'static', max_zoom: 1.04 },
  visualizer: { enabled: false, bar_count: 24, opacity: 0.65 },
  progress: { enabled: false },
  color_treatment: { mode: 'none' },
})

export const createTemplateFamilyV4 = (
  state: CreationStateV4,
  name: string,
  sourceTemplateId?: string,
  sourceRole?: TemplateRole,
  randomUuid?: () => string,
): CreationStateV4 => {
  if (!name.trim() || Array.from(name).length > 128) throw new Error('Family name must contain 1 through 128 characters.')
  const source = sourceTemplateId ? state.visual_templates.find((item) => item.visual_template_id === sourceTemplateId) : undefined
  if (sourceTemplateId && (!source || familyForTemplate(state, sourceTemplateId))) throw new Error('The starting template must be an existing standalone template.')
  if (source && (!sourceRole || source.canvas.aspect_ratio !== ROLE_ASPECT[sourceRole])) throw new Error('The starting template is incompatible with the selected family role.')
  let next = state
  const members = {} as VisualTemplateFamily['members']
  const created: VisualTemplate[] = []
  ;(['album', 'single', 'short'] as TemplateRole[]).forEach((role) => {
    if (source && role === sourceRole) {
      members[role === 'album' ? 'album_visual_template_id' : role === 'single' ? 'single_visual_template_id' : 'short_visual_template_id'] = source.visual_template_id
      return
    }
    const id = allocateId(next, 'visual-template', randomUuid)
    const configuration = source ? configurationFromTemplate(source) : neutralConfiguration(role)
    configuration.canvas.aspect_ratio = ROLE_ASPECT[role]
    created.push({ visual_template_id: id, label: `${name.trim()} — ${ROLE_LABEL[role]}`.slice(0, 128), ...configuration })
    next = { ...next, visual_templates: [...next.visual_templates, created.at(-1)!] }
    members[role === 'album' ? 'album_visual_template_id' : role === 'single' ? 'single_visual_template_id' : 'short_visual_template_id'] = id
  })
  const familyId = allocateId(next, 'visual-template-family', randomUuid)
  return { ...next, visual_template_families: [...next.visual_template_families, { visual_template_family_id: familyId, name: name.trim(), members }] }
}

export const renameTemplateFamilyV4 = (state: CreationStateV4, familyId: string, name: string): CreationStateV4 => {
  if (!name.trim() || Array.from(name).length > 128) throw new Error('Family name must contain 1 through 128 characters.')
  if (!state.visual_template_families.some((item) => item.visual_template_family_id === familyId)) throw new Error('The selected template family no longer exists.')
  return { ...state, visual_template_families: state.visual_template_families.map((item) => item.visual_template_family_id === familyId ? { ...item, name: name.trim() } : item) }
}

export const ungroupTemplateFamilyV4 = (state: CreationStateV4, familyId: string): CreationStateV4 => {
  if (!state.visual_template_families.some((item) => item.visual_template_family_id === familyId)) throw new Error('The selected template family no longer exists.')
  return { ...state, visual_template_families: state.visual_template_families.filter((item) => item.visual_template_family_id !== familyId) }
}

export const deleteTemplateFamilyV4 = (state: CreationStateV4, familyId: string): CreationStateV4 => {
  const family = state.visual_template_families.find((item) => item.visual_template_family_id === familyId)
  if (!family) throw new Error('The selected template family no longer exists.')
  const memberIds = new Set(Object.values(family.members))
  return {
    ...state,
    visual_templates: state.visual_templates.filter((item) => !memberIds.has(item.visual_template_id)),
    visual_template_families: state.visual_template_families.filter((item) => item.visual_template_family_id !== familyId),
  }
}

export const provenanceUsage = (state: CreationStateV4, templateId: string) => [
  ...state.albums.filter((item) => item.source_visual_template_id === templateId).map((item) => ({ kind: 'album' as const, id: item.album_plan_id, status: item.status })),
  ...state.singles.filter((item) => item.source_visual_template_id === templateId).map((item) => ({ kind: 'single' as const, id: item.single_id, status: item.status })),
  ...state.shorts.filter((item) => item.source_visual_template_id === templateId).map((item) => ({ kind: 'short' as const, id: item.short_id, status: item.status })),
]

export interface V3UpgradeFinding { kind: TemplateRole; id: string; status: 'active' | 'archived'; reference: string | null; reason?: 'null' | 'dangling' }
export interface V3UpgradePreflight {
  currentVersion: 'wrld-creation-state/3.0'
  targetVersion: 'wrld-creation-state/4.0'
  albums: number
  singles: number
  shorts: number
  active: number
  archived: number
  resolvable: number
  nullReferences: V3UpgradeFinding[]
  danglingReferences: V3UpgradeFinding[]
  canUpgrade: boolean
}

export const preflightV3Upgrade = (state: CreationStateV3): V3UpgradePreflight => {
  const templates = new Set(state.visual_templates.map((item) => item.visual_template_id))
  const findings: V3UpgradeFinding[] = [
    ...state.albums.map((item) => ({ kind: 'album' as const, id: item.album_plan_id, status: item.status, reference: item.visual_template_id })),
    ...state.singles.map((item) => ({ kind: 'single' as const, id: item.single_id, status: item.status, reference: item.visual_template_id })),
    ...state.shorts.map((item) => ({ kind: 'short' as const, id: item.short_id, status: item.status, reference: item.visual_template_id })),
  ]
  const nullReferences = findings.filter((item) => item.reference === null).map((item) => ({ ...item, reason: 'null' as const }))
  const danglingReferences = findings.filter((item) => item.reference !== null && !templates.has(item.reference)).map((item) => ({ ...item, reason: 'dangling' as const }))
  return {
    currentVersion: 'wrld-creation-state/3.0', targetVersion: 'wrld-creation-state/4.0',
    albums: state.albums.length, singles: state.singles.length, shorts: state.shorts.length,
    active: findings.filter((item) => item.status === 'active').length,
    archived: findings.filter((item) => item.status === 'archived').length,
    resolvable: findings.length - nullReferences.length - danglingReferences.length,
    nullReferences, danglingReferences, canUpgrade: nullReferences.length === 0 && danglingReferences.length === 0,
  }
}

export const migrateCreationStateV2ToV3 = async (state: CreationStateV2): Promise<CreationStateV3> => {
  const preserved = structuredClone(state)
  delete preserved.issues
  const identities = new Set([
    ...preserved.visual_templates.map((item) => item.visual_template_id),
    ...preserved.albums.flatMap((item) => [item.album_plan_id, ...item.assignments.map((assignment) => assignment.assignment_id)]),
    ...preserved.singles.map((item) => item.single_id),
    ...preserved.shorts.map((item) => item.short_id),
  ])
  const migrationId = async (templateId: string, role: TemplateRole | 'family') => {
    const digest = await sha256(`${preserved.project_id}\0${templateId}\0wrld-creation-state/3.0\0${role}`)
    return `${role === 'family' ? 'visual-template-family' : 'visual-template'}-${digest.slice(0, 32)}`
  }
  const reserve = (identity: string) => {
    if (identities.has(identity)) throw new Error(`Deterministic Creation v3 identity ${identity} collides with existing work.`)
    identities.add(identity)
  }
  const albumConsumers = new Set(preserved.albums.flatMap((item) => item.visual_template_id ? [item.visual_template_id] : []))
  const singleConsumers = new Set(preserved.singles.flatMap((item) => item.visual_template_id ? [item.visual_template_id] : []))
  const generated: VisualTemplate[] = []
  const families: VisualTemplateFamily[] = []
  const albumReplacements = new Map<string, string>()
  for (const source of preserved.visual_templates) {
    const primary: TemplateRole = source.canvas.aspect_ratio === '9:16' ? 'short' : singleConsumers.has(source.visual_template_id) ? 'single' : 'album'
    const familyId = await migrationId(source.visual_template_id, 'family'); reserve(familyId)
    const members = {} as VisualTemplateFamily['members']
    for (const role of ['album', 'single', 'short'] as TemplateRole[]) {
      let memberId = source.visual_template_id
      if (role !== primary) {
        memberId = await migrationId(source.visual_template_id, role); reserve(memberId)
        generated.push({ ...structuredClone(source), visual_template_id: memberId, canvas: { aspect_ratio: ROLE_ASPECT[role] } })
      }
      members[role === 'album' ? 'album_visual_template_id' : role === 'single' ? 'single_visual_template_id' : 'short_visual_template_id'] = memberId
    }
    families.push({ visual_template_family_id: familyId, name: source.label, members })
    if (primary === 'single' && albumConsumers.has(source.visual_template_id)) albumReplacements.set(source.visual_template_id, members.album_visual_template_id)
  }
  return {
    ...preserved,
    contract_version: 'wrld-creation-state/3.0',
    visual_templates: [...preserved.visual_templates, ...generated],
    visual_template_families: families,
    albums: preserved.albums.map((item) => item.visual_template_id && albumReplacements.has(item.visual_template_id) ? { ...item, visual_template_id: albumReplacements.get(item.visual_template_id)! } : item),
  }
}

export const migrateCreationStateV3ToV4 = (state: CreationStateV3): CreationStateV4 => {
  const preflight = preflightV3Upgrade(state)
  if (!preflight.canUpgrade) {
    const finding = preflight.danglingReferences[0] ?? preflight.nullReferences[0]
    throw new Error(`${finding.kind} ${finding.id} cannot be migrated losslessly because its visual template reference is ${finding.reason}.`)
  }
  const templates = new Map(state.visual_templates.map((item) => [item.visual_template_id, item]))
  const migrate = <T extends { visual_template_id: string | null }>(item: T) => {
    const template = templates.get(item.visual_template_id!)!
    const { visual_template_id, ...preserved } = item
    return { ...preserved, visual_configuration: configurationFromTemplate(template), source_visual_template_id: visual_template_id }
  }
  const preservedState = structuredClone(state)
  delete preservedState.issues
  return {
    ...preservedState,
    contract_version: 'wrld-creation-state/4.0',
    albums: state.albums.map(migrate),
    singles: state.singles.map(migrate),
    shorts: state.shorts.map(migrate),
  }
}

const sha256 = async (value: string) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)))).map((item) => item.toString(16).padStart(2, '0')).join('')
const stableStringify = (value: unknown): string => {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`
  if (value && typeof value === 'object') return `{${Object.entries(value).sort(([left], [right]) => left.localeCompare(right)).map(([key, item]) => `${JSON.stringify(key)}:${stableStringify(item)}`).join(',')}}`
  return JSON.stringify(value)
}

export type CleanupClassification = 'PROVEN_DISPOSABLE' | 'REVIEW_REQUIRED' | 'RETAIN'
export interface CleanupCandidate {
  templateId: string
  label: string
  classification: CleanupClassification
  reason: string
  provenance: Array<{ kind: TemplateRole; id: string; status: 'active' | 'archived' }>
  equivalenceGroup: string[]
}
export interface CleanupPlan {
  revision: number
  fingerprint: string
  before: number
  after: number
  familyMemberCount: number
  standaloneCount: number
  activeReferenceCount: number
  archivedReferenceCount: number
  provenanceOnlyReferenceCount: number
  unreferencedCount: number
  candidates: CleanupCandidate[]
}

export const analyzeLegacyTemplates = async (state: CreationStateV4): Promise<CleanupPlan> => {
  const source = structuredClone(state) as CreationStateV4 & { issues?: unknown }
  delete source.issues
  const fingerprint = await sha256(stableStringify(source))
  const familyMembers = new Set(state.visual_template_families.flatMap((family) => Object.values(family.members)))
  const provenance = new Map<string, CleanupCandidate['provenance']>()
  const add = (templateId: string | null, kind: TemplateRole, id: string, status: 'active' | 'archived') => {
    if (!templateId) return
    provenance.set(templateId, [...(provenance.get(templateId) ?? []), { kind, id, status }])
  }
  state.albums.forEach((item) => add(item.source_visual_template_id, 'album', item.album_plan_id, item.status))
  state.singles.forEach((item) => add(item.source_visual_template_id, 'single', item.single_id, item.status))
  state.shorts.forEach((item) => add(item.source_visual_template_id, 'short', item.short_id, item.status))
  const groups = new Map<string, string[]>()
  state.visual_templates.forEach((template) => {
    const key = JSON.stringify(configurationFromTemplate(template))
    groups.set(key, [...(groups.get(key) ?? []), template.visual_template_id])
  })
  const generated = new Map<string, string>()
  await Promise.all(state.shorts.map(async (item) => generated.set(item.short_id, `visual-template-${(await sha256(`${state.project_id}\0${item.short_id}\0wrld-creation-state/2.0`)).slice(0, 32)}`)))
  const candidates = state.visual_templates.map((template): CleanupCandidate => {
    const linked = provenance.get(template.visual_template_id) ?? []
    const exactShort = state.shorts.find((item) => generated.get(item.short_id) === template.visual_template_id && template.label === `Short visual ${item.short_id}`.slice(0, 128))
    const equivalent = groups.get(JSON.stringify(configurationFromTemplate(template))) ?? []
    if (familyMembers.has(template.visual_template_id)) return { templateId: template.visual_template_id, label: template.label, classification: 'RETAIN', reason: 'Family members are protected.', provenance: linked, equivalenceGroup: equivalent }
    if (exactShort && exactShort.source_visual_template_id === template.visual_template_id && linked.length && linked.every((reference) => {
      const target = compositionFor(state, { kind: reference.kind, id: reference.id })
      return target ? configurationsEquivalent(target.visual_configuration, configurationFromTemplate(template)) : false
    })) return { templateId: template.visual_template_id, label: template.label, classification: 'PROVEN_DISPOSABLE', reason: 'Stable migration identity, exact label, provenance, and visual equivalence are verified.', provenance: linked, equivalenceGroup: equivalent }
    if (exactShort || template.label.startsWith('Short visual short-') || equivalent.length > 1) return { templateId: template.visual_template_id, label: template.label, classification: 'REVIEW_REQUIRED', reason: 'The template may be generated or redundant, but safe disposal is not proven.', provenance: linked, equivalenceGroup: equivalent }
    return { templateId: template.visual_template_id, label: template.label, classification: 'RETAIN', reason: 'The template is unique, intentional, or of uncertain origin.', provenance: linked, equivalenceGroup: equivalent }
  })
  const disposable = candidates.filter((item) => item.classification === 'PROVEN_DISPOSABLE').length
  const references = candidates.flatMap((item) => item.provenance)
  return {
    revision: state.revision, fingerprint, before: candidates.length, after: candidates.length - disposable,
    familyMemberCount: familyMembers.size,
    standaloneCount: candidates.length - familyMembers.size,
    activeReferenceCount: references.filter((item) => item.status === 'active').length,
    archivedReferenceCount: references.filter((item) => item.status === 'archived').length,
    provenanceOnlyReferenceCount: references.length,
    unreferencedCount: candidates.filter((item) => item.provenance.length === 0).length,
    candidates,
  }
}

export const applyLegacyCleanup = async (state: CreationStateV4, plan: CleanupPlan, authorized: boolean): Promise<CreationStateV4> => {
  if (!authorized) throw new Error('Legacy cleanup requires explicit authorization.')
  const current = await analyzeLegacyTemplates(state)
  if (current.revision !== plan.revision || current.fingerprint !== plan.fingerprint || JSON.stringify(current.candidates) !== JSON.stringify(plan.candidates)) throw new Error('The cleanup plan is stale and must be reviewed again.')
  const removable = new Set(plan.candidates.filter((item) => item.classification === 'PROVEN_DISPOSABLE').map((item) => item.templateId))
  if (!removable.size) return state
  return { ...state, visual_templates: state.visual_templates.filter((item) => !removable.has(item.visual_template_id)) }
}
