import type { CreationStateV3, CreationStateV4, EditableVisualCreationState, VisualTemplate, VisualTemplateFamily } from '../../api/types'

export type TemplateRole = 'album' | 'single' | 'short'

export const ROLE_LABEL: Record<TemplateRole, string> = {
  album: 'Album',
  single: 'Single',
  short: 'Short',
}

const MEMBER_FIELD: Record<TemplateRole, keyof VisualTemplateFamily['members']> = {
  album: 'album_visual_template_id',
  single: 'single_visual_template_id',
  short: 'short_visual_template_id',
}

const ROLE_ASPECT: Record<TemplateRole, VisualTemplate['canvas']['aspect_ratio']> = {
  album: '16:9',
  single: '16:9',
  short: '9:16',
}

export interface TemplateFamilyMembership {
  family: VisualTemplateFamily
  role: TemplateRole
}

export interface FamilyTemplateChoice extends TemplateFamilyMembership {
  template: VisualTemplate
}

export interface FamilyVersion {
  role: TemplateRole
  templateId: string
  template: VisualTemplate | null
}

type FamilyCreationState = CreationStateV3 | CreationStateV4
const familyState = (state: EditableVisualCreationState): FamilyCreationState | null => (
  state.contract_version === 'wrld-creation-state/3.0' || state.contract_version === 'wrld-creation-state/4.0' ? state : null
)

export const familyMemberships = (state: EditableVisualCreationState, templateId: string): TemplateFamilyMembership[] => {
  const current = familyState(state)
  if (!current) return []
  return current.visual_template_families.flatMap((family) => (Object.keys(MEMBER_FIELD) as TemplateRole[]).flatMap((role) =>
    family.members[MEMBER_FIELD[role]] === templateId ? [{ family, role }] : [],
  ))
}

export const familyForTemplate = (state: EditableVisualCreationState, templateId: string): TemplateFamilyMembership | null => {
  const memberships = familyMemberships(state, templateId)
  return memberships.length === 1 ? memberships[0] : null
}

export const familyVersions = (state: EditableVisualCreationState, family: VisualTemplateFamily): FamilyVersion[] => (Object.keys(MEMBER_FIELD) as TemplateRole[]).map((role) => {
  const templateId = family.members[MEMBER_FIELD[role]]
  return { role, templateId, template: state.visual_templates.find((item) => item.visual_template_id === templateId) ?? null }
})

export const familyTemplateChoices = (state: EditableVisualCreationState, role: TemplateRole): FamilyTemplateChoice[] => {
  const current = familyState(state)
  if (!current) return []
  return current.visual_template_families.flatMap((family) => {
    const templateId = family.members[MEMBER_FIELD[role]]
    const template = current.visual_templates.find((item) => item.visual_template_id === templateId)
    const memberships = familyMemberships(current, templateId)
    const exactMembership = memberships.length === 1 && memberships[0].family.visual_template_family_id === family.visual_template_family_id && memberships[0].role === role
    return template?.canvas.aspect_ratio === ROLE_ASPECT[role] && exactMembership ? [{ family, role, template }] : []
  })
}

export const standaloneTemplates = (state: EditableVisualCreationState, role: TemplateRole): VisualTemplate[] => {
  const memberIds = new Set(state.contract_version === 'wrld-creation-state/3.0' || state.contract_version === 'wrld-creation-state/4.0'
    ? state.visual_template_families.flatMap((family) => Object.values(family.members))
    : [])
  return state.visual_templates.filter((template) => !memberIds.has(template.visual_template_id) && template.canvas.aspect_ratio === ROLE_ASPECT[role])
}

export const templateCompatibleWithRole = (state: EditableVisualCreationState, template: VisualTemplate, role: TemplateRole): boolean => {
  if (state.contract_version === 'wrld-creation-state/3.0' || state.contract_version === 'wrld-creation-state/4.0') {
    const memberships = familyMemberships(state, template.visual_template_id)
    if (memberships.length) return memberships.length === 1 && memberships[0].role === role
  }
  return template.canvas.aspect_ratio === ROLE_ASPECT[role]
}

export const familyGraphDiagnostics = (state: EditableVisualCreationState): string[] => {
  const current = familyState(state)
  if (!current) return []
  const templates = new Map(current.visual_templates.map((template) => [template.visual_template_id, template]))
  const consumers = new Map<string, string[]>()
  const diagnostics: string[] = []
  for (const family of current.visual_template_families) {
    const ids = (Object.keys(MEMBER_FIELD) as TemplateRole[]).map((role) => family.members[MEMBER_FIELD[role]])
    if (new Set(ids).size !== ids.length) diagnostics.push(`Family ${family.visual_template_family_id} reuses a concrete template in more than one role.`)
    for (const role of Object.keys(MEMBER_FIELD) as TemplateRole[]) {
      const templateId = family.members[MEMBER_FIELD[role]]
      const template = templates.get(templateId)
      if (!template) diagnostics.push(`Family ${family.visual_template_family_id} has a missing ${ROLE_LABEL[role]} member ${templateId}.`)
      else if (template.canvas.aspect_ratio !== ROLE_ASPECT[role]) diagnostics.push(`Family ${family.visual_template_family_id} has an invalid ${ROLE_LABEL[role]} aspect ratio.`)
      const owners = consumers.get(templateId) ?? []
      owners.push(`${family.visual_template_family_id}:${role}`)
      consumers.set(templateId, owners)
    }
  }
  consumers.forEach((owners, templateId) => {
    if (owners.length > 1) diagnostics.push(`Template ${templateId} appears in multiple family roles.`)
  })
  return [...new Set(diagnostics)]
}
