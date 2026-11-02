import { AlertTriangle, Archive, Check, ChevronRight, Copy, ImagePlus, Redo2, Save, Undo2, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, assetAudioUrl, assetImageUrl, loadCreationState, saveCreationState } from '../../api/client'
import type { CreationIssue, CreationState, ReviewWorkspace, VisualCreationState, VisualSourceIssue, VisualTemplate } from '../../api/types'
import { useStudio } from '../../app/state'
import { AudioPreviewButton, useAudioPreview } from './AudioPreview'
import { CompositionPreview } from './CompositionPreview'
import { DemonstrationEditor } from './DemonstrationEditor'
import { migrateCreationState, newVisualTemplate } from './creationV2'
import { migrateCreationStateV2ToV3, migrateCreationStateV3ToV4, preflightV3Upgrade } from './creationV4'
import { familyForTemplate, familyGraphDiagnostics, familyTemplateChoices, familyVersions, ROLE_LABEL, standaloneTemplates, templateCompatibleWithRole, type TemplateRole } from './templateFamilies'
import { createTemplateFamily, deleteUnusedTemplateFamily, familyConsumers, familySynchronizationImpact, renameTemplateFamily, synchronizeTemplateFamily, ungroupTemplateFamily, visualConfiguration } from './templateFamilyOperations'
import { WaveformEditor } from './WaveformEditor'
import { V4EditorWorkspace } from './V4EditorWorkspace'

const SAMPLE_RATE = 48_000
const STRONG_SHA256 = /^[0-9a-f]{64}$/
type Category = 'albums' | 'singles' | 'shorts'
type Target = { kind: 'album' | 'single' | 'short'; id: string; label: string; status: 'active' | 'archived'; templateId: string | null; assetId?: string }
const CATEGORIES: Category[] = ['albums', 'singles', 'shorts']
const CATEGORY_LABEL: Record<Category, string> = { albums: 'Albums', singles: 'Singles', shorts: 'Shorts' }
const targetKey = (target: Pick<Target, 'kind' | 'id'>) => `${target.kind}:${target.id}`

const targetList = (state: VisualCreationState, workspace: ReviewWorkspace, category: Category): Target[] => {
  const assetLabel = (assetId: string) => workspace.assets.find((item) => item.asset_id === assetId)?.relative_path.split('/').at(-1) ?? assetId
  if (category === 'albums') return state.albums.map((item) => ({ kind: 'album', id: item.album_plan_id, label: item.label, status: item.status, templateId: item.visual_template_id }))
  if (category === 'singles') return state.singles.map((item, index) => ({ kind: 'single', id: item.single_id, label: `${assetLabel(item.asset_id)} · Single ${index + 1}`, status: item.status, templateId: item.visual_template_id, assetId: item.asset_id }))
  return state.shorts.map((item, index) => ({ kind: 'short', id: item.short_id, label: `${assetLabel(item.asset_id)} · Short ${index + 1}`, status: item.status, templateId: item.visual_template_id, assetId: item.asset_id }))
}

const referencesTo = (state: VisualCreationState, templateId: string) => [
  ...state.albums.filter((item) => item.visual_template_id === templateId).map((item) => ({ kind: 'Album', id: item.album_plan_id, status: item.status })),
  ...state.singles.filter((item) => item.visual_template_id === templateId).map((item) => ({ kind: 'Single', id: item.single_id, status: item.status })),
  ...state.shorts.filter((item) => item.visual_template_id === templateId).map((item) => ({ kind: 'Short', id: item.short_id, status: item.status })),
]

const targetReference = (state: VisualCreationState, kind: 'album' | 'single' | 'short', id: string) => {
  if (kind === 'album') return state.albums.find((item) => item.album_plan_id === id)?.visual_template_id
  if (kind === 'single') return state.singles.find((item) => item.single_id === id)?.visual_template_id
  return state.shorts.find((item) => item.short_id === id)?.visual_template_id
}

const currentIssues = (state: VisualCreationState): CreationIssue[] => {
  const result: CreationIssue[] = []
  for (const issue of state.issues ?? []) {
    if ('draft_id' in issue) { result.push(issue); continue }
    const template = issue.visual_template_id ? state.visual_templates.find((item) => item.visual_template_id === issue.visual_template_id) : undefined
    const affected = issue.affected_targets.filter((target) => {
      const reference = targetReference(state, target.kind, target.id)
      if (issue.code === 'LEGACY_VISUAL_SETTINGS_UNMAPPED') return issue.visual_template_id ? reference === issue.visual_template_id : reference == null
      if (!template || reference !== template.visual_template_id) return false
      if (issue.code === 'VISUAL_SOURCE_REQUIRED') return template.background_image === null
      if (!template.background_image || template.background_image.asset_id !== issue.asset_id) return false
      if (issue.code === 'VISUAL_SOURCE_CHANGED' && template.background_image.expected_sha256 !== issue.expected_sha256) return false
      return true
    })
    if (affected.length) result.push({ ...issue, affected_targets: affected })
  }
  return result
}

type IssueEntry = { issue: CreationIssue; target?: VisualSourceIssue['affected_targets'][number] }
type IssueGroup = { key: string; code: string; kind: string; entries: IssueEntry[] }
const groupIssues = (issues: CreationIssue[]): IssueGroup[] => {
  const groups = new Map<string, IssueGroup>()
  const add = (code: string, kind: string, entry: IssueEntry) => {
    const key = `${code}:${kind}`
    const group = groups.get(key) ?? { key, code, kind, entries: [] }
    group.entries.push(entry); groups.set(key, group)
  }
  issues.forEach((issue) => {
    if ('draft_id' in issue) { add(issue.code, 'dependency', { issue }); return }
    issue.affected_targets.forEach((target) => add(issue.code, target.kind, { issue, target }))
  })
  return [...groups.values()]
}

const issueGroupLabel = (group: IssueGroup) => {
  const count = group.entries.length
  const noun = group.kind === 'dependency' ? `dependenc${count === 1 ? 'y' : 'ies'}` : `${group.kind[0].toUpperCase()}${group.kind.slice(1)}${count === 1 ? '' : 's'}`
  if (group.code === 'VISUAL_SOURCE_REQUIRED') return `${count} ${noun} need${count === 1 ? 's' : ''} a background.`
  if (group.code === 'VISUAL_SOURCE_MISSING') return `${count} ${noun} ${count === 1 ? 'has' : 'have'} a missing background.`
  if (group.code === 'VISUAL_SOURCE_CHANGED') return `${count} ${noun} ${count === 1 ? 'has' : 'have'} a changed background.`
  if (group.code === 'VISUAL_SOURCE_EXCLUDED') return `${count} ${noun} use${count === 1 ? 's' : ''} an excluded background.`
  if (group.code === 'VISUAL_SOURCE_UNSUPPORTED') return `${count} ${noun} use${count === 1 ? 's' : ''} an unsupported background.`
  if (group.code === 'LEGACY_VISUAL_SETTINGS_UNMAPPED') return `${count} ${noun} need${count === 1 ? 's' : ''} visual settings review.`
  return `${count} ${noun} need${count === 1 ? 's' : ''} source review.`
}

const DurableEditorWorkspace = ({ workspace }: { workspace: ReviewWorkspace }) => {
  const { state: studioState, dispatch, registerGuard, requestGuarded } = useStudio()
  const [creation, setCreation] = useState<CreationState | null>(null)
  const [saved, setSaved] = useState<CreationState | null>(null)
  const [past, setPast] = useState<VisualCreationState[]>([])
  const [future, setFuture] = useState<VisualCreationState[]>([])
  const [category, setCategory] = useState<Category>('albums')
  const [selectedId, setSelectedId] = useState('')
  const [albumAssignment, setAlbumAssignment] = useState<Record<string, string>>({})
  const [error, setError] = useState('')
  const [errorCode, setErrorCode] = useState('')
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [assignOpen, setAssignOpen] = useState(false)
  const [assignSelection, setAssignSelection] = useState<Set<string>>(() => new Set())
  const [locallyCreatedTemplateIds, setLocallyCreatedTemplateIds] = useState<Set<string>>(() => new Set())
  const [editScope, setEditScope] = useState<'current' | 'all'>('current')
  const [familyCreateOpen, setFamilyCreateOpen] = useState(false)
  const [familyName, setFamilyName] = useState('')
  const [familySourceId, setFamilySourceId] = useState('')
  const [managedFamilyId, setManagedFamilyId] = useState('')
  const [managedFamilyName, setManagedFamilyName] = useState('')
  const [upgradeRemediationTemplate, setUpgradeRemediationTemplate] = useState<Record<string, string>>({})
  const loadGeneration = useRef(0)
  const categoryButtons = useRef<Partial<Record<Category, HTMLButtonElement>>>({})
  const preview = useAudioPreview(workspace.projectId)
  const stopPreview = preview.stop

  useEffect(() => {
    stopPreview()
  }, [albumAssignment, category, selectedId, stopPreview])

  useEffect(() => {
    const controller = new AbortController(); const generation = ++loadGeneration.current
    setCreation(null); setSaved(null); setPast([]); setFuture([]); setError(''); setErrorCode(''); setCategory('albums'); setSelectedId(''); setAssignOpen(false); setAssignSelection(new Set()); setLocallyCreatedTemplateIds(new Set()); setEditScope('current'); setFamilyCreateOpen(false); setFamilyName(''); setFamilySourceId(''); setManagedFamilyId(''); setManagedFamilyName('')
    void loadCreationState(workspace.projectId, controller.signal).then((value) => {
      if (controller.signal.aborted || generation !== loadGeneration.current) return
      setCreation(value); setSaved(structuredClone(value))
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted && generation === loadGeneration.current) setError(cause instanceof Error ? cause.message : 'Editor state could not be loaded.')
    })
    return () => controller.abort()
  }, [workspace.projectId, loadAttempt])

  useEffect(() => {
    if (creation?.contract_version !== 'wrld-creation-state/3.0') { setManagedFamilyId(''); return }
    setManagedFamilyId((current) => creation.visual_template_families.some((family) => family.visual_template_family_id === current) ? current : creation.visual_template_families[0]?.visual_template_family_id ?? '')
  }, [creation])

  useEffect(() => {
    if (creation?.contract_version !== 'wrld-creation-state/3.0') { setManagedFamilyName(''); return }
    setManagedFamilyName(creation.visual_template_families.find((family) => family.visual_template_family_id === managedFamilyId)?.name ?? '')
  }, [creation, managedFamilyId])

  useEffect(() => { setEditScope('current') }, [category, selectedId])

  useEffect(() => {
    const requested = studioState.editorTarget
    if (!creation || creation.contract_version === 'wrld-creation-state/4.0' || !requested || requested.projectId !== workspace.projectId) return
    const nextCategory: Category = requested.kind === 'album' ? 'albums' : requested.kind === 'single' ? 'singles' : 'shorts'
    const exists = creation.contract_version !== 'wrld-creation-state/1.0' && targetList(creation, workspace, nextCategory).some((item) => item.id === requested.id)
    if (exists) { setCategory(nextCategory); setSelectedId(requested.id) }
    dispatch({ type: 'consume-editor-target' })
  }, [creation, dispatch, studioState.editorTarget, workspace])

  const categoryAvailability: Record<Category, boolean> = useMemo(() => creation && creation.contract_version !== 'wrld-creation-state/1.0' ? ({
    albums: creation.albums.some((item) => item.status === 'active'),
    singles: creation.singles.some((item) => item.status === 'active'),
    shorts: creation.shorts.some((item) => item.status === 'active'),
  }) : ({ albums: true, singles: true, shorts: true }), [creation])
  const availabilityKey = CATEGORIES.map((item) => categoryAvailability[item] ? '1' : '0').join('')
  useEffect(() => {
    if (!creation || creation.contract_version === 'wrld-creation-state/1.0' || categoryAvailability[category]) return
    const next = CATEGORIES.find((item) => categoryAvailability[item])
    const focused = categoryButtons.current[category] === document.activeElement
    setSelectedId(''); setAssignOpen(false); setAssignSelection(new Set())
    if (next) {
      setCategory(next)
      if (focused) window.requestAnimationFrame(() => categoryButtons.current[next]?.focus())
    }
  }, [availabilityKey, category, categoryAvailability, creation])

  const dirty = Boolean(creation && saved && JSON.stringify(creation) !== JSON.stringify(saved))
  const persist = useCallback(async (): Promise<boolean> => {
    if (!creation) return true
    setError(''); setErrorCode('')
    try { const value = await saveCreationState(workspace.projectId, creation); setCreation(value); setSaved(structuredClone(value)); setPast([]); setFuture([]); setLocallyCreatedTemplateIds(new Set()); return true }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Editor changes could not be saved.'); setErrorCode(cause instanceof ApiError ? cause.code : ''); return false }
  }, [creation, workspace.projectId])
  const discard = useCallback(() => { if (saved) { setCreation(structuredClone(saved)); setPast([]); setFuture([]); setError(''); setErrorCode(''); setAssignOpen(false); setAssignSelection(new Set()); setLocallyCreatedTemplateIds(new Set()) } }, [saved])
  useEffect(() => {
    if (!creation || !saved || creation.contract_version === 'wrld-creation-state/4.0') return
    return registerGuard({ dirty, save: persist, discard, label: 'Editor' })
  }, [creation, saved, dirty, persist, discard, registerGuard])

  if (!creation) return <div className="panel empty-state"><strong>{error ? 'Editor state could not be loaded.' : 'Loading durable Editor state…'}</strong>{error && <><span role="alert">{error}</span><button onClick={() => setLoadAttempt((value) => value + 1)}>Retry</button></>}</div>

  if (creation.contract_version === 'wrld-creation-state/1.0') {
    const upgrade = async () => {
      setError('')
      try { const candidate = await migrateCreationState(creation); const value = await saveCreationState(workspace.projectId, candidate); setCreation(value); setSaved(structuredClone(value)); setPast([]); setFuture([]) }
      catch (cause) { setError(cause instanceof Error ? cause.message : 'Creation document could not be upgraded.') }
    }
    return <div className="panel upgrade-panel"><span className="eyebrow">Creation contract</span><h2>Upgrade required for visual templates</h2><p>Your v1 Creation document remains unchanged until this explicit revision-safe Save succeeds. Existing identities, approvals, excerpts, and legacy settings are preserved.</p>{error && <div role="alert">{error}</div>}<button className="primary" onClick={() => void upgrade()}>Upgrade Creation document</button></div>
  }

  if (creation.contract_version === 'wrld-creation-state/4.0') {
    return <V4EditorWorkspace key={`${creation.project_id}:${creation.revision}:${creation.save_id}`} workspace={workspace} initialState={creation}/>
  }

  const state = creation
  const targets = targetList(state, workspace, category)
  const target = targets.find((item) => item.id === selectedId) ?? targets.find((item) => item.status === 'active') ?? targets[0]
  const template = target?.templateId ? state.visual_templates.find((item) => item.visual_template_id === target.templateId) : undefined
  const targetRole = target?.kind as TemplateRole | undefined
  const familyChoices = targetRole ? familyTemplateChoices(state, targetRole) : []
  const standaloneChoices = targetRole ? standaloneTemplates(state, targetRole) : []
  const assignedFamily = template ? familyForTemplate(state, template.visual_template_id) : null
  const assignedFamilyVersions = assignedFamily ? familyVersions(state, assignedFamily.family) : []
  const v3State = state.contract_version === 'wrld-creation-state/3.0' ? state : null
  const managedFamily = v3State?.visual_template_families.find((family) => family.visual_template_family_id === managedFamilyId) ?? null
  const managedFamilyConsumers = v3State && managedFamily ? familyConsumers(v3State, managedFamily) : []
  const familyDiagnostics = familyGraphDiagnostics(state)
  const unresolvedTemplateReference = target?.templateId && !template ? target.templateId : null
  const assignedRoleMismatch = assignedFamily && targetRole && assignedFamily.role !== targetRole
  const imageAssets = workspace.assets.filter((item) => item.kind === 'image' && item.presence === 'present' && typeof item.sha256 === 'string' && STRONG_SHA256.test(item.sha256) && item.capabilities.inspection.status === 'supported')
  const allTargets = CATEGORIES.flatMap((item) => targetList(state, workspace, item))
  const compatibleActiveTargets = template ? allTargets.filter((item) => item.status === 'active' && templateCompatibleWithRole(state, template, item.kind)) : []
  const incompatibleActiveTargets = template ? allTargets.filter((item) => item.status === 'active' && !templateCompatibleWithRole(state, template, item.kind)) : []
  const selectedAssignmentTargets = compatibleActiveTargets.filter((item) => assignSelection.has(targetKey(item)))
  const changedAssignmentTargets = selectedAssignmentTargets.filter((item) => item.templateId !== template?.visual_template_id)
  const displayedIssues = currentIssues(state)
  const issueGroups = groupIssues(displayedIssues)
  const selectedImage = template?.background_image ? workspace.assets.find((item) => item.asset_id === template.background_image?.asset_id) : undefined
  const imageUrl = selectedImage ? assetImageUrl(workspace.projectId, selectedImage.asset_id) : undefined
  const short = target?.kind === 'short' ? state.shorts.find((item) => item.short_id === target.id) : undefined
  const single = target?.kind === 'single' ? state.singles.find((item) => item.single_id === target.id) : undefined
  const album = target?.kind === 'album' ? state.albums.find((item) => item.album_plan_id === target.id) : undefined
  const selectedAssignmentId = album ? (albumAssignment[album.album_plan_id] ?? album.assignments[0]?.assignment_id) : undefined
  const assignment = album?.assignments.find((item) => item.assignment_id === selectedAssignmentId)
  const audioAssetId = short?.asset_id ?? single?.asset_id ?? assignment?.asset_id
  const audioAsset = workspace.assets.find((item) => item.asset_id === audioAssetId)
  const playbackKey = target ? `editor-${target.kind}-${target.id}-${assignment?.assignment_id ?? ''}` : 'editor-none'
  const shortStart = short ? short.start_sample / SAMPLE_RATE : undefined
  const shortEnd = short ? (short.start_sample + short.sample_count) / SAMPLE_RATE : undefined

  const change = (next: VisualCreationState) => {
    if (JSON.stringify(next) === JSON.stringify(state)) return
    setPast((items) => [...items.slice(-39), structuredClone(state)]); setFuture([]); setCreation(next)
  }
  const v3Preflight = state.contract_version === 'wrld-creation-state/3.0' ? preflightV3Upgrade(state) : null
  const remediateUpgradeTarget = (finding: NonNullable<typeof v3Preflight>['nullReferences'][number] | NonNullable<typeof v3Preflight>['danglingReferences'][number]) => {
    if (state.contract_version !== 'wrld-creation-state/3.0') return
    const templateId = upgradeRemediationTemplate[`${finding.kind}:${finding.id}`]
    const candidate = state.visual_templates.find((item) => item.visual_template_id === templateId)
    if (!candidate || !templateCompatibleWithRole(state, candidate, finding.kind)) { setError('Choose a compatible existing template for this composition.'); return }
    if (!window.confirm(`Assign ${candidate.label} to ${finding.kind} ${finding.id} as a separate v3 remediation change? Save it before upgrading.`)) return
    if (finding.kind === 'album') change({ ...state, albums: state.albums.map((item) => item.album_plan_id === finding.id ? { ...item, visual_template_id: templateId } : item) })
    else if (finding.kind === 'single') change({ ...state, singles: state.singles.map((item) => item.single_id === finding.id ? { ...item, visual_template_id: templateId, customized: true, approved: false } : item) })
    else change({ ...state, shorts: state.shorts.map((item) => item.short_id === finding.id ? { ...item, visual_template_id: templateId, customized: true, approved: false } : item) })
  }
  const upgradeV3 = async () => {
    if (state.contract_version !== 'wrld-creation-state/3.0' || !v3Preflight?.canUpgrade || dirty) return
    if (!window.confirm(`Upgrade Creation v3 to v4? ${v3Preflight.resolvable} composition visual configurations will be copied losslessly. This uses the current revision-safe Save protocol.`)) return
    setError(''); setErrorCode('')
    try {
      const candidate = migrateCreationStateV3ToV4(state)
      const value = await saveCreationState(workspace.projectId, candidate)
      setCreation(value); setSaved(structuredClone(value)); setPast([]); setFuture([])
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Creation v4 upgrade failed.'); setErrorCode(cause instanceof ApiError ? cause.code : '') }
  }
  const upgradeV2 = async () => {
    if (state.contract_version !== 'wrld-creation-state/2.0' || dirty) return
    if (!window.confirm('Upgrade Creation v2 to v3 as a separate revision-safe Save? Existing templates and composition references are preserved while deterministic family members are added.')) return
    setError(''); setErrorCode('')
    try {
      const candidate = await migrateCreationStateV2ToV3(state)
      const value = await saveCreationState(workspace.projectId, candidate)
      setCreation(value); setSaved(structuredClone(value)); setPast([]); setFuture([])
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Creation v3 upgrade failed.'); setErrorCode(cause instanceof ApiError ? cause.code : '') }
  }
  const undo = () => { const previous = past.at(-1); if (!previous) return; setFuture([structuredClone(state), ...future]); setCreation(previous); setPast(past.slice(0, -1)) }
  const redo = () => { const next = future[0]; if (!next) return; setPast([...past, structuredClone(state)]); setCreation(next); setFuture(future.slice(1)) }
  const replaceTargetTemplate = (templateId: string | null, nextState: VisualCreationState = state, invalidate = true): VisualCreationState => {
    if (!target) return nextState
    if (target.kind === 'album') return { ...nextState, albums: nextState.albums.map((item) => item.album_plan_id === target.id ? { ...item, visual_template_id: templateId } : item) }
    if (target.kind === 'single') return { ...nextState, singles: nextState.singles.map((item) => item.single_id === target.id ? { ...item, visual_template_id: templateId, ...(invalidate ? { customized: true, approved: false } : {}) } : item) }
    return { ...nextState, shorts: nextState.shorts.map((item) => item.short_id === target.id ? { ...item, visual_template_id: templateId, ...(invalidate ? { customized: true, approved: false } : {}) } : item) }
  }
  const assignTemplate = (templateId: string | null) => {
    if (!target || target.templateId === templateId) return
    if (templateId) {
      const candidate = state.visual_templates.find((item) => item.visual_template_id === templateId)
      if (!candidate || !templateCompatibleWithRole(state, candidate, target.kind)) {
        setError('That template is not the registered family member or standalone aspect required for this output type.')
        setErrorCode('CREATION_STATE_INVALID')
        return
      }
    }
    setError(''); setErrorCode(''); setEditScope('current'); change(replaceTargetTemplate(templateId))
  }
  const createTemplate = () => {
    if (!target) return
    const nextTemplate = newVisualTemplate(target.kind === 'short' ? '9:16' : '16:9', `${target.label} visual`)
    setLocallyCreatedTemplateIds((current) => new Set(current).add(nextTemplate.visual_template_id))
    change(replaceTargetTemplate(nextTemplate.visual_template_id, { ...state, visual_templates: [...state.visual_templates, nextTemplate] }))
  }
  const customize = () => {
    if (!target || !template) return
    const identities = new Set([
      ...state.visual_templates.map((item) => item.visual_template_id),
      ...(state.contract_version === 'wrld-creation-state/3.0' ? state.visual_template_families.map((item) => item.visual_template_family_id) : []),
      ...state.albums.flatMap((item) => [item.album_plan_id, ...item.assignments.map((assignmentItem) => assignmentItem.assignment_id)]),
      ...state.singles.map((item) => item.single_id),
      ...state.shorts.map((item) => item.short_id),
    ])
    const copiedId = `visual-template-${crypto.randomUUID()}`
    if (identities.has(copiedId)) { setError(`Generated identity ${copiedId} collides with existing Creation work.`); setErrorCode('CREATION_STATE_INVALID'); return }
    const copied: VisualTemplate = { ...structuredClone(template), visual_template_id: copiedId, label: `${template.label} copy`.slice(0, 128) }
    setError(''); setErrorCode(''); setEditScope('current')
    change(replaceTargetTemplate(copied.visual_template_id, { ...state, visual_templates: [...state.visual_templates, copied] }, false))
  }
  const editTemplate = (update: (value: VisualTemplate) => VisualTemplate, pixelAffecting = true) => {
    if (!template) return
    const nextTemplate = update(structuredClone(template))
    if (JSON.stringify(nextTemplate) === JSON.stringify(template)) return
    if (!pixelAffecting) {
      change({ ...state, visual_templates: state.visual_templates.map((item) => item.visual_template_id === template.visual_template_id ? nextTemplate : item) })
      return
    }
    if (JSON.stringify(visualConfiguration(nextTemplate)) === JSON.stringify(visualConfiguration(template))) return
    if (editScope === 'all') {
      if (!v3State || !assignedFamily) { setError('All Three Types is available only for a valid Creation v3 family member.'); setErrorCode('CREATION_STATE_INVALID'); return }
      try {
        if (nextTemplate.background_image) {
          const eligibleImage = imageAssets.find((item) => item.asset_id === nextTemplate.background_image?.asset_id)
          if (!eligibleImage?.sha256 || eligibleImage.sha256 !== nextTemplate.background_image.expected_sha256) throw new Error('All Three Types cannot copy a missing, excluded, unsupported, or changed background. Recover or replace it first.')
        }
        const impact = familySynchronizationImpact(v3State, nextTemplate)
        if (!impact.changedTemplateIds.length) return
        const active = impact.consumers.filter((item) => item.status === 'active').length
        const archived = impact.consumers.filter((item) => item.status === 'archived').length
        const approvals = impact.consumers.filter((item) => item.approved).length
        if (!window.confirm(`Apply the edited ${ROLE_LABEL[assignedFamily.role]} configuration to all three members of ${assignedFamily.family.name}? ${active} active and ${archived} archived consumers are affected; ${approvals} approval${approvals === 1 ? '' : 's'} will be invalidated. Member IDs, labels, roles, and aspect ratios remain unchanged.`)) return
        setError(''); setErrorCode(''); change(synchronizeTemplateFamily(v3State, nextTemplate))
      } catch (cause) { setError(cause instanceof Error ? cause.message : 'The family could not be synchronized safely.'); setErrorCode('CREATION_STATE_INVALID') }
      return
    }
    const refs = referencesTo(state, template.visual_template_id)
    const active = refs.filter((item) => item.status === 'active').length
    const archived = refs.filter((item) => item.status === 'archived').length
    if (refs.length > 1 && !window.confirm(`Edit only this ${assignedFamily ? ROLE_LABEL[assignedFamily.role] : template.canvas.aspect_ratio} template for ${active} active and ${archived} archived consumers? Other family members remain unchanged. Linked Single/Short approvals will be invalidated. Affected: ${refs.map((item) => `${item.kind} ${item.id} (${item.status})`).join(', ')}.`)) return
    let next: VisualCreationState = { ...state, visual_templates: state.visual_templates.map((item) => item.visual_template_id === template.visual_template_id ? nextTemplate : item) }
    next = { ...next, singles: next.singles.map((item) => item.visual_template_id === template.visual_template_id ? { ...item, customized: true, approved: false } : item), shorts: next.shorts.map((item) => item.visual_template_id === template.visual_template_id ? { ...item, customized: true, approved: false } : item) }
    change(next)
  }
  const createFamily = () => {
    if (!v3State || !targetRole) return
    try {
      const next = createTemplateFamily(v3State, { name: familyName, sourceTemplateId: familySourceId || undefined, sourceRole: familySourceId ? targetRole : undefined })
      const priorFamilies = new Set(v3State.visual_template_families.map((item) => item.visual_template_family_id))
      const createdFamily = next.visual_template_families.find((item) => !priorFamilies.has(item.visual_template_family_id))!
      const priorTemplates = new Set(v3State.visual_templates.map((item) => item.visual_template_id))
      const createdTemplateIds = next.visual_templates.filter((item) => !priorTemplates.has(item.visual_template_id)).map((item) => item.visual_template_id)
      setLocallyCreatedTemplateIds((current) => new Set([...current, ...createdTemplateIds]))
      setError(''); setErrorCode(''); change(next); setManagedFamilyId(createdFamily.visual_template_family_id); setFamilyCreateOpen(false); setFamilyName(''); setFamilySourceId('')
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'The template family could not be created.'); setErrorCode('CREATION_STATE_INVALID') }
  }
  const renameFamily = () => {
    if (!v3State || !managedFamily) return
    try { setError(''); setErrorCode(''); change(renameTemplateFamily(v3State, managedFamily.visual_template_family_id, managedFamilyName)) }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'The family could not be renamed.'); setErrorCode('CREATION_STATE_INVALID') }
  }
  const ungroupFamily = () => {
    if (!v3State || !managedFamily || !window.confirm(`Remove grouping for ${managedFamily.name}? All three concrete templates, composition references, approvals, and visual settings will be preserved.`)) return
    try { const next = ungroupTemplateFamily(v3State, managedFamily.visual_template_family_id); setError(''); setErrorCode(''); change(next); setManagedFamilyId('') }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'The family could not be ungrouped.'); setErrorCode('CREATION_STATE_INVALID') }
  }
  const deleteFamily = () => {
    if (!v3State || !managedFamily) return
    if (managedFamilyConsumers.length) { setError(`The family cannot be deleted because ${managedFamilyConsumers.length} active or archived composition${managedFamilyConsumers.length === 1 ? '' : 's'} still reference its members.`); setErrorCode('CREATION_STATE_INVALID'); return }
    if (!window.confirm(`Delete unused family ${managedFamily.name} and all three unreferenced member templates? This does not affect unrelated standalone templates.`)) return
    try { const next = deleteUnusedTemplateFamily(v3State, managedFamily.visual_template_family_id); setError(''); setErrorCode(''); change(next); setManagedFamilyId('') }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'The unused family could not be deleted.'); setErrorCode('CREATION_STATE_INVALID') }
  }
  const setBackground = (assetId: string) => editTemplate((item) => {
    const asset = imageAssets.find((candidate) => candidate.asset_id === assetId)
    return { ...item, background_image: asset?.sha256 ? { asset_id: asset.asset_id, expected_sha256: asset.sha256 } : null }
  })
  const updateShortRange = (start: number, end: number) => {
    if (!short || !audioAsset) return
    const total = Math.max(1, Math.round((audioAsset.media.duration_seconds ?? 0) * SAMPLE_RATE)); const minimum = Math.min(5 * SAMPLE_RATE, total)
    const startSample = Math.min(Math.max(0, Math.round(start * SAMPLE_RATE)), Math.max(0, total - minimum)); const endSample = Math.min(total, Math.max(startSample + minimum, Math.round(end * SAMPLE_RATE)))
    change({ ...state, shorts: state.shorts.map((item) => item.short_id === short.short_id ? { ...item, start_sample: startSample, sample_count: endSample - startSample, origin: 'manual', review_required: endSample - startSample < 5 * SAMPLE_RATE, customized: true, approved: false } : item) })
  }
  const focusIssue = (issue: VisualSourceIssue, selectedTarget = issue.affected_targets[0]) => {
    const affected = selectedTarget
    if (!affected) return
    setCategory(affected.kind === 'album' ? 'albums' : affected.kind === 'single' ? 'singles' : 'shorts')
    setSelectedId(affected.id)
  }
  const acceptChangedImage = (issue: VisualSourceIssue) => {
    if (issue.code !== 'VISUAL_SOURCE_CHANGED' || !issue.visual_template_id || !issue.asset_id) return
    const asset = workspace.assets.find((item) => item.asset_id === issue.asset_id)
    if (!asset?.sha256) return
    const refs = referencesTo(state, issue.visual_template_id)
    if (!window.confirm(`Accept the changed image for ${refs.length} target${refs.length === 1 ? '' : 's'} and clear linked Single/Short approvals?`)) return
    change({
      ...state,
      visual_templates: state.visual_templates.map((item) => item.visual_template_id === issue.visual_template_id ? { ...item, background_image: { asset_id: asset.asset_id, expected_sha256: asset.sha256! } } : item),
      singles: state.singles.map((item) => item.visual_template_id === issue.visual_template_id ? { ...item, customized: true, approved: false } : item),
      shorts: state.shorts.map((item) => item.visual_template_id === issue.visual_template_id ? { ...item, customized: true, approved: false } : item),
    })
  }
  const setAssignmentScope = (scope: 'current' | Category) => {
    const selected = scope === 'current'
      ? (target && target.status === 'active' && compatibleActiveTargets.some((item) => item.kind === target.kind && item.id === target.id) ? [target] : [])
      : compatibleActiveTargets.filter((item) => scope === 'albums' ? item.kind === 'album' : scope === 'singles' ? item.kind === 'single' : item.kind === 'short')
    setAssignSelection(new Set(selected.map(targetKey)))
  }
  const applySharedAssignment = () => {
    if (!template || changedAssignmentTargets.length === 0) return
    const selected = new Set(changedAssignmentTargets.map(targetKey))
    const next: VisualCreationState = {
      ...state,
      albums: state.albums.map((item) => selected.has(`album:${item.album_plan_id}`) && item.status === 'active' ? { ...item, visual_template_id: template.visual_template_id } : item),
      singles: state.singles.map((item) => selected.has(`single:${item.single_id}`) && item.status === 'active' ? { ...item, visual_template_id: template.visual_template_id, customized: true, approved: false } : item),
      shorts: state.shorts.map((item) => selected.has(`short:${item.short_id}`) && item.status === 'active' ? { ...item, visual_template_id: template.visual_template_id, customized: true, approved: false } : item),
    }
    change(next); setAssignOpen(false); setAssignSelection(new Set())
  }

  return <>
    {error && <div className="mode-banner" role="alert">{error}{(errorCode === 'REVISION_CONFLICT' || errorCode === 'COMMIT_UNRESOLVED') && <button onClick={() => setLoadAttempt((value) => value + 1)}>Reload server state</button>}</div>}
    {preview.error && <div className="mode-banner" role="alert">Audio preview unavailable. {preview.error}</div>}
    {state.contract_version === 'wrld-creation-state/2.0' && <div className="mode-banner v4-upgrade-preflight"><strong>Sequential upgrade required</strong><span>Creation v2 must be explicitly saved as v3 before the v3→v4 preflight is available. No multi-generation migration occurs automatically.</span><button className="primary" disabled={dirty} onClick={() => void upgradeV2()}>Upgrade to Creation v3</button>{dirty && <small>Save or discard current v2 edits first.</small>}</div>}
    {v3Preflight && <details className="mode-banner v4-upgrade-preflight">
      <summary><strong>Creation v4 upgrade available</strong><span>Explicit, lossless, and revision-safe</span><ChevronRight className="disclosure-arrow" size={16}/></summary>
      <div className="upgrade-summary"><span><b>Current</b> {v3Preflight.currentVersion}</span><span><b>Target</b> {v3Preflight.targetVersion}</span><span><b>Albums</b> {v3Preflight.albums}</span><span><b>Singles</b> {v3Preflight.singles}</span><span><b>Shorts</b> {v3Preflight.shorts}</span><span><b>Active / archived</b> {v3Preflight.active} / {v3Preflight.archived}</span><span><b>Resolvable</b> {v3Preflight.resolvable}</span></div>
      <p>Upgrade copies each resolved template's complete effective visual configuration into its composition. Identities, archive state, approvals, settings, template families, and reusable templates are preserved. Loading v3 does not mark the workspace dirty.</p>
      {[...v3Preflight.nullReferences, ...v3Preflight.danglingReferences].length > 0 && <div className="upgrade-blockers" role="group" aria-label="Creation v4 upgrade blockers"><strong>{v3Preflight.nullReferences.length} null and {v3Preflight.danglingReferences.length} dangling reference(s) block lossless migration.</strong><p>No defaults will be synthesized. Remediation is a separate undoable v3 assignment that must be explicitly saved before preflight can pass.</p>{[...v3Preflight.nullReferences, ...v3Preflight.danglingReferences].map((finding) => {
        const key = `${finding.kind}:${finding.id}`
        const choices = [...familyTemplateChoices(state, finding.kind).map((item) => item.template), ...standaloneTemplates(state, finding.kind)]
        return <div key={key} className="upgrade-remediation"><code>{key}</code><span>{finding.reason === 'null' ? 'No authoritative visual settings' : `Dangling reference ${finding.reference}`}</span><select aria-label={`Remediation template for ${key}`} value={upgradeRemediationTemplate[key] ?? ''} onChange={(event) => setUpgradeRemediationTemplate((current) => ({ ...current, [key]: event.target.value }))}><option value="">Choose compatible existing template</option>{choices.map((item) => <option key={item.visual_template_id} value={item.visual_template_id}>{item.label} · {item.visual_template_id}</option>)}</select><button disabled={!upgradeRemediationTemplate[key]} onClick={() => remediateUpgradeTarget(finding)}>Assign for remediation</button></div>
      })}</div>}
      {dirty && <p><strong>Save or discard current v3 edits before upgrading.</strong> Upgrade is never combined with unrelated pending changes.</p>}
      <button className="primary" disabled={!v3Preflight.canUpgrade || dirty} onClick={() => void upgradeV3()}>Upgrade to Creation v4</button>
    </details>}
    {!!displayedIssues.length && <details className="mode-banner editor-warnings">
      <summary><AlertTriangle size={17}/><strong>Creation warnings ({displayedIssues.length})</strong><span>Unresolved warnings remain; expand to review.</span><ChevronRight className="disclosure-arrow" size={16}/></summary>
      <p className="warning-freshness">Warnings are reconciled with unsaved Editor changes and revalidated by the server when you Save.</p>
      <div className="warning-groups">{issueGroups.map((group) => <details key={group.key} className="warning-group"><summary><strong>{issueGroupLabel(group)}</strong><ChevronRight className="disclosure-arrow" size={14}/></summary><div>{group.entries.map((entry, index) => {
        const issue = entry.issue
        if ('draft_id' in issue) return <article key={`${issue.draft_id}-${issue.code}-${index}`}><div><code>{issue.draft_id}</code><span>{issue.relative_path || issue.asset_id}</span></div><button onClick={() => requestGuarded(() => dispatch({ type: 'navigate', route: 'import' }))}>Review in Import</button></article>
        const affected = entry.target
        const importApplicable = issue.code === 'VISUAL_SOURCE_MISSING' || issue.code === 'VISUAL_SOURCE_EXCLUDED' || (issue.code === 'VISUAL_SOURCE_REQUIRED' && imageAssets.length === 0)
        return <article key={`${issue.code}-${issue.visual_template_id ?? 'visual'}-${affected?.id ?? index}`}><div><code>{affected?.id ?? issue.visual_template_id ?? 'visual'}</code><span>{issue.visual_template_id ?? 'No typed template'} · {issue.code.replaceAll('_', ' ').toLocaleLowerCase()}</span></div><div>{issue.code === 'VISUAL_SOURCE_CHANGED' && workspace.assets.some((item) => item.asset_id === issue.asset_id && item.sha256) && <button onClick={() => acceptChangedImage(issue)}>Accept changed image</button>}<button onClick={() => focusIssue(issue, affected)}>Edit dependency</button>{importApplicable && <button onClick={() => requestGuarded(() => dispatch({ type: 'navigate', route: 'import' }))}>Review in Import</button>}</div></article>
      })}</div></details>)}</div>
    </details>}
    <div className="editor-toolbar panel"><div><strong>{target?.label ?? 'Visual Editor'}</strong><span>{target ? `${target.kind} · ${target.id}` : 'Choose or create an active Creation target.'}</span></div><div className="heading-actions"><button disabled={!past.length} onClick={undo}><Undo2 size={16}/> Undo</button><button disabled={!future.length} onClick={redo}><Redo2 size={16}/> Redo</button><button className="primary" disabled={!dirty} onClick={() => void persist()}><Save size={16}/> Save editor draft</button></div></div>
    <nav className="composition-categories" aria-label="Composition category">{CATEGORIES.map((item) => {
      const available = categoryAvailability[item]
      const tooltipId = `category-disabled-${item}`
      return <span className="category-tab" key={item}><button ref={(node) => { if (node) categoryButtons.current[item] = node }} type="button" className={category === item && available ? 'active' : ''} aria-current={category === item && available ? 'page' : undefined} aria-disabled={!available} aria-describedby={!available ? tooltipId : undefined} onClick={() => { if (!available) return; setCategory(item); setSelectedId(''); setAssignOpen(false); setAssignSelection(new Set()) }}>{CATEGORY_LABEL[item]}</button>{!available && <span id={tooltipId} role="tooltip">Item Disabled. There are no {CATEGORY_LABEL[item]} selected.</span>}</span>
    })}</nav>
    {!CATEGORIES.some((item) => categoryAvailability[item]) ? <div className="panel empty-state editor-empty"><strong>No active Creation outputs</strong><span>Create or restore an Album, Single, or Short in Creation before editing a visual template.</span><button onClick={() => requestGuarded(() => dispatch({ type: 'select-review-tab', tab: 'creation' }))}>Open Creation</button></div> : <div className="template-editor-grid">
      <aside className="panel target-rail"><div className="panel-title"><div><span className="eyebrow">Compositions</span><h2>{category}</h2></div></div><div className="target-list">{targets.filter((item) => item.status === 'active').map((item) => <button key={item.id} className={target?.id === item.id ? 'selected' : ''} onClick={() => setSelectedId(item.id)}><strong>{item.label}</strong><small>{item.id}</small></button>)}</div>{targets.some((item) => item.status === 'archived') && <details className="archived-targets"><summary><Archive size={13}/> Archived</summary>{targets.filter((item) => item.status === 'archived').map((item) => <button key={item.id} className={target?.id === item.id ? 'selected' : ''} onClick={() => setSelectedId(item.id)}>{item.label}</button>)}</details>}</aside>
      <main className="template-preview-column"><div className="panel preview-panel"><CompositionPreview title={target?.label ?? 'No composition selected'} template={template} imageUrl={imageUrl} progress={preview.activeKey === playbackKey ? preview.progress : 0}/></div>{target && <div className="panel composition-audio"><div><span className="eyebrow">Audio source</span><strong>{audioAsset?.relative_path ?? 'Source unavailable'}</strong></div>{album && album.assignments.length > 0 && <select aria-label="Album track" value={selectedAssignmentId} onChange={(event) => setAlbumAssignment((current) => ({ ...current, [album.album_plan_id]: event.target.value }))}>{album.assignments.map((item, index) => <option key={item.assignment_id} value={item.assignment_id}>Track {index + 1} · {workspace.assets.find((asset) => asset.asset_id === item.asset_id)?.relative_path ?? item.asset_id}</option>)}</select>}<AudioPreviewButton asset={audioAsset} controller={preview} playbackKey={playbackKey} playLabel={`Play ${target.label}`} pauseLabel={`Pause ${target.label}`} startSeconds={shortStart} endSeconds={shortEnd}/></div>}{short && audioAsset && <div className="panel short-range"><WaveformEditor duration={audioAsset.media.duration_seconds ?? shortEnd ?? 0} region={{ shortId: short.short_id, start: shortStart ?? 0, end: shortEnd ?? 0, approved: short.approved, reviewRequired: short.review_required }} audioUrl={assetAudioUrl(workspace.projectId, audioAsset.asset_id)} onChange={updateShortRange}/><button className={`approval-button ${short.approved ? 'approved' : ''}`} disabled={short.review_required} onClick={() => change({ ...state, shorts: state.shorts.map((item) => item.short_id === short.short_id ? { ...item, approved: !item.approved } : item) })}>{short.approved ? <Check size={16}/> : null}{short.approved ? 'Approved' : 'Approve Short'}</button></div>}</main>
      <aside className="panel template-inspector"><div className="panel-title"><div><span className="eyebrow">Visual template</span><h2>{template?.label ?? 'No template assigned'}</h2></div></div>{target && <section className="control-group template-assignment">
        <div className="assigned-template-summary" aria-live="polite">{template ? assignedFamily ? <><span><strong>Family</strong>{assignedFamily.family.name}</span><span><strong>Version</strong>{ROLE_LABEL[assignedFamily.role]} — {template.canvas.aspect_ratio}</span><span><strong>Template</strong>{template.label}</span><code>{assignedFamily.family.visual_template_family_id}</code></> : <span><strong>Standalone</strong>{template.label}</span> : <span><strong>Assigned Template</strong>None</span>}</div>
        {assignedFamily && <div className="family-version-list" aria-label={`${assignedFamily.family.name} family versions`}><strong>Family versions</strong>{assignedFamilyVersions.map((version) => <span key={version.role} className={version.role === assignedFamily.role ? 'current' : ''}><b>{ROLE_LABEL[version.role]}</b><small>{version.template?.canvas.aspect_ratio ?? (version.role === 'short' ? '9:16' : '16:9')} · {version.template?.label ?? version.templateId}</small>{version.role === assignedFamily.role && <em>Current</em>}</span>)}</div>}
        {(unresolvedTemplateReference || assignedRoleMismatch || familyDiagnostics.length > 0) && <div className="family-diagnostics" role="alert"><strong>Template family data requires repair.</strong>{unresolvedTemplateReference && <span>Assigned template {unresolvedTemplateReference} could not be resolved.</span>}{assignedFamily && assignedRoleMismatch && <span>The assigned {ROLE_LABEL[assignedFamily.role]} member cannot be used by this {ROLE_LABEL[target.kind]} output.</span>}{familyDiagnostics.map((message) => <span key={message}>{message}</span>)}</div>}
        <label>Assigned template<select aria-label="Assigned visual template" value={template?.visual_template_id ?? unresolvedTemplateReference ?? ''} onChange={(event) => { assignTemplate(event.target.value || null); setAssignOpen(false); setAssignSelection(new Set()) }}><option value="">No template</option>{unresolvedTemplateReference && <option value={unresolvedTemplateReference} disabled>Unavailable template · {unresolvedTemplateReference}</option>}{state.contract_version === 'wrld-creation-state/3.0' && familyChoices.length > 0 && <optgroup label="Template families">{familyChoices.map((item) => <option key={item.family.visual_template_family_id} value={item.template.visual_template_id}>{item.family.name} — {ROLE_LABEL[item.role]} — {item.template.canvas.aspect_ratio} · {item.family.visual_template_family_id}</option>)}</optgroup>}{standaloneChoices.length > 0 && <optgroup label={state.contract_version === 'wrld-creation-state/3.0' ? 'Standalone templates' : 'Templates'}>{standaloneChoices.map((item) => <option key={item.visual_template_id} value={item.visual_template_id}>{item.label} — {item.canvas.aspect_ratio}</option>)}</optgroup>}</select></label>
        <div><button onClick={createTemplate}><ImagePlus size={13}/> New template</button><button disabled={!template} onClick={customize}><Copy size={13}/> Customize copy · This Composition Only</button></div>
        {state.contract_version === 'wrld-creation-state/2.0' && <p className="family-version-note">Template families require Creation v3. This v2 document remains editable and will not be migrated automatically.</p>}
        {v3State && <><button className="family-create-button" onClick={() => { setFamilyCreateOpen((value) => !value); if (!familyCreateOpen) setFamilySourceId(!assignedFamily && template ? template.visual_template_id : '') }}>Create Template Family</button>{familyCreateOpen && <div className="family-create-panel" role="group" aria-label="Create Template Family"><label>Family name<input aria-label="New family name" value={familyName} onChange={(event) => setFamilyName(event.target.value)}/></label><label>Starting point<select aria-label="Family starting point" value={familySourceId} onChange={(event) => setFamilySourceId(event.target.value)}><option value="">Create from scratch</option>{standaloneChoices.map((item) => <option key={item.visual_template_id} value={item.visual_template_id}>Reuse {item.label} as {targetRole ? ROLE_LABEL[targetRole] : 'current'} member</option>)}</select></label><p>Creates one Album, Single, and Short member without choosing a background or reassigning compositions.</p><div><button onClick={() => { setFamilyCreateOpen(false); setFamilyName(''); setFamilySourceId('') }}>Cancel</button><button className="primary" disabled={!familyName.trim() || Array.from(familyName).length > 128} onClick={createFamily}>Create family</button></div></div>}</>}
        <button className="assign-to-button" disabled={!template} onClick={() => { setAssignOpen((value) => !value); if (!assignOpen) setAssignmentScope('current') }}>Assign to…</button>{assignOpen && template && <div className="assign-panel" role="group" aria-label="Assign shared visual template"><strong>Assign shared template</strong><p>Selected outputs will reference this one template. Future pixel changes affect every consumer.</p><div className="assignment-scopes"><button onClick={() => setAssignmentScope('current')}>Current output</button>{CATEGORIES.map((item) => compatibleActiveTargets.some((candidate) => candidate.kind === (item === 'albums' ? 'album' : item === 'singles' ? 'single' : 'short')) && <button key={item} onClick={() => setAssignmentScope(item)}>All active {CATEGORY_LABEL[item]}</button>)}</div><fieldset><legend>Compatible active outputs</legend>{compatibleActiveTargets.map((item) => <label key={targetKey(item)}><input type="checkbox" checked={assignSelection.has(targetKey(item))} onChange={() => setAssignSelection((current) => { const next = new Set(current); const key = targetKey(item); if (next.has(key)) next.delete(key); else next.add(key); return next })}/><span>{item.label}</span><small>{item.kind} · {item.templateId === template.visual_template_id ? 'already assigned' : 'will change'}</small></label>)}</fieldset>{incompatibleActiveTargets.length > 0 && <p>{incompatibleActiveTargets.length} active output{incompatibleActiveTargets.length === 1 ? ' is' : 's are'} excluded because this {assignedFamily ? `${ROLE_LABEL[assignedFamily.role]} family member is role-specific` : `${template.canvas.aspect_ratio} template is incompatible`}.</p>}<details><summary>Existing consumers ({referencesTo(state, template.visual_template_id).length})</summary><ul>{referencesTo(state, template.visual_template_id).map((item) => <li key={`${item.kind}-${item.id}`}>{item.kind} {item.id} ({item.status})</li>)}</ul></details><div className="assignment-impact"><strong>{changedAssignmentTargets.length} output{changedAssignmentTargets.length === 1 ? '' : 's'} will change.</strong><span>{selectedAssignmentTargets.length - changedAssignmentTargets.length} no-op assignment{selectedAssignmentTargets.length - changedAssignmentTargets.length === 1 ? '' : 's'} will be preserved.</span></div><div className="assignment-actions"><button onClick={() => { setAssignOpen(false); setAssignSelection(new Set()) }}>Cancel</button><button className="primary" disabled={!changedAssignmentTargets.length} onClick={applySharedAssignment}>Apply to {changedAssignmentTargets.length}</button></div></div>}
        {v3State && v3State.visual_template_families.length > 0 && <div className="family-management" role="group" aria-label="Manage Template Family"><strong>Manage Template Family</strong><select aria-label="Managed template family" value={managedFamily?.visual_template_family_id ?? ''} onChange={(event) => setManagedFamilyId(event.target.value)}>{v3State.visual_template_families.map((family) => <option key={family.visual_template_family_id} value={family.visual_template_family_id}>{family.name} · {family.visual_template_family_id}</option>)}</select>{managedFamily && <><label>Family name<input aria-label="Managed family name" value={managedFamilyName} onChange={(event) => setManagedFamilyName(event.target.value)}/></label><span>{managedFamilyConsumers.filter((item) => item.status === 'active').length} active · {managedFamilyConsumers.filter((item) => item.status === 'archived').length} archived consumers</span><div><button disabled={managedFamilyName === managedFamily.name || !managedFamilyName.trim() || Array.from(managedFamilyName).length > 128} onClick={renameFamily}>Rename Family</button><button onClick={ungroupFamily}>Remove Family Grouping</button><button className="danger-action" onClick={deleteFamily}>Delete Unused Family</button></div></>}</div>}
      </section>}{template && assignedFamily && v3State && <section className="control-group edit-scope"><strong>Edit scope</strong><label><input type="radio" name="family-edit-scope" value="current" checked={editScope === 'current'} onChange={() => setEditScope('current')}/> Current Type Only <small>Only {ROLE_LABEL[assignedFamily.role]} changes; other family members remain unchanged.</small></label><label><input type="radio" name="family-edit-scope" value="all" checked={editScope === 'all'} onChange={() => setEditScope('all')}/> All Three Types <small>Transfers the complete visual configuration while preserving each member's identity, label, role, and aspect ratio.</small></label><span>Selected: {editScope === 'all' ? 'All Three Types' : 'Current Type Only'}</span><details><summary>Consumer impact</summary><ul>{familyConsumers(v3State, assignedFamily.family).map((item) => <li key={`${item.kind}:${item.id}`}>{ROLE_LABEL[item.kind]} {item.id} ({item.status}){item.approved ? ' · approved' : ''}</li>)}</ul></details></section>}{template && <>
        <section className="control-group"><label>Template label<input aria-label="Template label" type="text" maxLength={128} value={template.label} onChange={(event) => editTemplate((item) => ({ ...item, label: event.target.value }), false)}/></label></section>
        <section className="control-group"><div className="control-name"><span><strong>Background</strong><small>Imported project image</small></span>{template.background_image && <button aria-label="Remove background" onClick={() => editTemplate((item) => ({ ...item, background_image: null }))}><X size={13}/></button>}</div><select aria-label="Background image" value={template.background_image?.asset_id ?? ''} onChange={(event) => setBackground(event.target.value)}><option value="">No background selected</option>{imageAssets.map((item) => <option key={item.asset_id} value={item.asset_id}>{item.relative_path}</option>)}</select>{template.background_image === null && locallyCreatedTemplateIds.has(template.visual_template_id) && imageAssets.length === 1 && <button className="sole-image-suggestion" onClick={() => setBackground(imageAssets[0].asset_id)}>Use only included image</button>}{selectedImage && <img className="background-thumb" src={assetImageUrl(workspace.projectId, selectedImage.asset_id)} alt={`Selected background ${selectedImage.relative_path}`}/>}</section>
        <section className="control-group"><div className="two-fields"><label>Fit<select aria-label="Background fit" value={template.geometry.fit_mode} onChange={(event) => editTemplate((item) => ({ ...item, geometry: { ...item.geometry, fit_mode: event.target.value as 'contain' | 'cover' } }))}><option value="contain">Contain</option><option value="cover">Cover</option></select></label><label>Focal X<input aria-label="Focal X" type="number" min="0" max="1" step="0.05" value={template.geometry.focal_x} onChange={(event) => editTemplate((item) => ({ ...item, geometry: { ...item.geometry, focal_x: Number(event.target.value) } }))}/></label><label>Focal Y<input aria-label="Focal Y" type="number" min="0" max="1" step="0.05" value={template.geometry.focal_y} onChange={(event) => editTemplate((item) => ({ ...item, geometry: { ...item.geometry, focal_y: Number(event.target.value) } }))}/></label></div></section>
        <section className="control-group"><label className="switch-row"><span><strong>Camera motion</strong><small>Approximate bounded movement</small></span><input aria-label="Camera motion" type="checkbox" checked={template.camera.mode === 'bounded'} onChange={(event) => editTemplate((item) => ({ ...item, camera: { ...item.camera, mode: event.target.checked ? 'bounded' : 'static' } }))}/><i/></label><label className="range-label"><span>Maximum zoom</span><strong>{template.camera.max_zoom.toFixed(2)}×</strong><input aria-label="Maximum zoom" type="range" min="1" max="1.05" step="0.01" value={template.camera.max_zoom} onChange={(event) => editTemplate((item) => ({ ...item, camera: { ...item.camera, max_zoom: Number(event.target.value) } }))}/></label></section>
        <section className="control-group"><label className="switch-row"><span><strong>Visualizer</strong><small>Approximate bars</small></span><input aria-label="Visualizer" type="checkbox" checked={template.visualizer.enabled} onChange={(event) => editTemplate((item) => ({ ...item, visualizer: { ...item.visualizer, enabled: event.target.checked } }))}/><i/></label><div className="two-fields"><label>Bars<input aria-label="Bar count" type="number" min="8" max="64" value={template.visualizer.bar_count} onChange={(event) => editTemplate((item) => ({ ...item, visualizer: { ...item.visualizer, bar_count: Number(event.target.value) } }))}/></label><label>Opacity<input aria-label="Bar opacity" type="number" min="0.1" max="1" step="0.05" value={template.visualizer.opacity} onChange={(event) => editTemplate((item) => ({ ...item, visualizer: { ...item.visualizer, opacity: Number(event.target.value) } }))}/></label></div></section>
        <section className="control-group"><label className="switch-row"><span><strong>Track progress</strong><small>Browser playback approximation</small></span><input aria-label="Track progress" type="checkbox" checked={template.progress.enabled} onChange={(event) => editTemplate((item) => ({ ...item, progress: { enabled: event.target.checked } }))}/><i/></label></section>
        <section className="control-group"><label className="switch-row"><span><strong>Color treatment</strong><small>Approximate tint</small></span><input aria-label="Color treatment" type="checkbox" checked={template.color_treatment.mode === 'custom'} onChange={(event) => editTemplate((item) => ({ ...item, color_treatment: event.target.checked ? { mode: 'custom', hex: '#416E9D', intensity: 0.18 } : { mode: 'none' } }))}/><i/></label>{template.color_treatment.mode === 'custom' && <><div className="color-field"><input aria-label="Tint color" type="color" value={template.color_treatment.hex} onChange={(event) => editTemplate((item) => ({ ...item, color_treatment: { mode: 'custom', hex: event.target.value, intensity: item.color_treatment.mode === 'custom' ? item.color_treatment.intensity : 0.18 } }))}/><code>{template.color_treatment.hex.toUpperCase()}</code></div><label className="range-label"><span>Intensity</span><strong>{Math.round(template.color_treatment.intensity * 100)}%</strong><input aria-label="Tint intensity" type="range" min="0" max="0.6" step="0.01" value={template.color_treatment.intensity} onChange={(event) => editTemplate((item) => ({ ...item, color_treatment: { mode: 'custom', hex: item.color_treatment.mode === 'custom' ? item.color_treatment.hex : '#416E9D', intensity: Number(event.target.value) } }))}/></label></>}</section>
        <div className="inspector-note">{referencesTo(state, template.visual_template_id).length} target(s) use this template. Shared pixel changes require confirmation and invalidate affected approvals.</div>
      </>}</aside>
    </div>}
  </>
}

export const EditorWorkspace = ({ workspace }: { workspace: ReviewWorkspace }) => workspace.sourceMode === 'demonstration'
  ? <DemonstrationEditor workspace={workspace}/>
  : <DurableEditorWorkspace workspace={workspace}/>
