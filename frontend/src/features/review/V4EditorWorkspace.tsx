import { AlertTriangle, Archive, Check, Copy, Redo2, Save, Search, Trash2, Undo2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, assetAudioUrl, assetImageUrl, saveCreationState } from '../../api/client'
import type { VisualConfiguration } from '../../api/generated/creation-state-v4'
import type { CreationIssue, CreationStateV4, ReviewWorkspace, VisualTemplate } from '../../api/types'
import { useStudio } from '../../app/state'
import { AudioPreviewButton, useAudioPreview } from './AudioPreview'
import { CompositionPreview } from './CompositionPreview'
import {
  analyzeLegacyTemplates,
  applyLegacyCleanup,
  applyTemplateToComposition,
  compositionFor,
  configurationFromTemplate,
  configurationsEquivalent,
  createTemplateFamilyV4,
  deleteStandaloneTemplate,
  deleteTemplateFamilyV4,
  duplicateStandaloneTemplate,
  provenanceUsage,
  renameStandaloneTemplate,
  renameTemplateFamilyV4,
  saveCompositionAsTemplate,
  ungroupTemplateFamilyV4,
  updateCompositionConfiguration,
  updateTemplateFromComposition,
  type CleanupPlan,
  type CompositionTarget,
  type TemplateUpdateScope,
} from './creationV4'
import { familyForTemplate, familyTemplateChoices, familyVersions, ROLE_LABEL, standaloneTemplates, type TemplateRole } from './templateFamilies'
import { WaveformEditor } from './WaveformEditor'

const SAMPLE_RATE = 48_000
const STRONG_SHA256 = /^[0-9a-f]{64}$/
type Category = 'albums' | 'singles' | 'shorts'
type Target = CompositionTarget & { label: string; status: 'active' | 'archived'; assetId?: string }
const CATEGORIES: Category[] = ['albums', 'singles', 'shorts']
const CATEGORY_LABEL: Record<Category, string> = { albums: 'Albums', singles: 'Singles', shorts: 'Shorts' }

const targetList = (state: CreationStateV4, workspace: ReviewWorkspace, category: Category): Target[] => {
  const assetLabel = (assetId: string) => workspace.assets.find((item) => item.asset_id === assetId)?.relative_path.split('/').at(-1) ?? assetId
  if (category === 'albums') return state.albums.map((item) => ({ kind: 'album', id: item.album_plan_id, label: item.label, status: item.status }))
  if (category === 'singles') return state.singles.map((item, index) => ({ kind: 'single', id: item.single_id, label: `${assetLabel(item.asset_id)} · Single ${index + 1}`, status: item.status, assetId: item.asset_id }))
  return state.shorts.map((item, index) => ({ kind: 'short', id: item.short_id, label: `${assetLabel(item.asset_id)} · Short ${index + 1}`, status: item.status, assetId: item.asset_id }))
}

const previewTemplate = (configuration: VisualConfiguration, label: string): VisualTemplate => ({
  visual_template_id: 'composition-preview', label, ...structuredClone(configuration),
})

const currentV4Issues = (state: CreationStateV4): CreationIssue[] => {
  const result: CreationIssue[] = []
  for (const issue of state.issues ?? []) {
    if ('draft_id' in issue) { result.push(issue); continue }
    const affected = issue.affected_targets.filter((target) => {
      const composition = compositionFor(state, target)
      if (!composition) return false
      const background = composition.visual_configuration.background_image
      if (issue.code === 'VISUAL_SOURCE_REQUIRED') return background === null
      if (!background || background.asset_id !== issue.asset_id) return false
      if (issue.code === 'VISUAL_SOURCE_CHANGED') return background.expected_sha256 !== issue.observed_sha256
      return true
    })
    if (affected.length) result.push({ ...issue, affected_targets: affected })
  }
  return result
}

const VisualControls = ({ value, images, onChange, labelPrefix }: {
  value: VisualConfiguration
  images: ReviewWorkspace['assets']
  onChange: (value: VisualConfiguration) => void
  labelPrefix: string
}) => {
  const update = (patch: Partial<VisualConfiguration>) => onChange({ ...value, ...patch })
  const setBackground = (assetId: string) => {
    const asset = images.find((item) => item.asset_id === assetId)
    update({ background_image: asset?.sha256 ? { asset_id: asset.asset_id, expected_sha256: asset.sha256 } : null })
  }
  return <div className="v4-visual-controls">
    <section className="control-group"><strong>Background</strong><label>{labelPrefix} background<select aria-label={`${labelPrefix} background image`} value={value.background_image?.asset_id ?? ''} onChange={(event) => setBackground(event.target.value)}><option value="">No background</option>{images.map((item) => <option key={item.asset_id} value={item.asset_id}>{item.relative_path}</option>)}</select></label></section>
    <section className="control-group"><div className="two-fields"><label>Fit<select aria-label={`${labelPrefix} background fit`} value={value.geometry.fit_mode} onChange={(event) => update({ geometry: { ...value.geometry, fit_mode: event.target.value as 'contain' | 'cover' } })}><option value="contain">Contain</option><option value="cover">Cover</option></select></label><label>Focal X<input aria-label={`${labelPrefix} focal X`} type="number" min="0" max="1" step="0.05" value={value.geometry.focal_x} onChange={(event) => update({ geometry: { ...value.geometry, focal_x: Number(event.target.value) } })}/></label><label>Focal Y<input aria-label={`${labelPrefix} focal Y`} type="number" min="0" max="1" step="0.05" value={value.geometry.focal_y} onChange={(event) => update({ geometry: { ...value.geometry, focal_y: Number(event.target.value) } })}/></label></div></section>
    <section className="control-group"><label className="switch-row"><span><strong>Camera motion</strong><small>Approximate bounded movement</small></span><input aria-label={`${labelPrefix} camera motion`} type="checkbox" checked={value.camera.mode === 'bounded'} onChange={(event) => update({ camera: { ...value.camera, mode: event.target.checked ? 'bounded' : 'static' } })}/><i/></label><label className="range-label"><span>Maximum zoom</span><strong>{value.camera.max_zoom.toFixed(2)}×</strong><input aria-label={`${labelPrefix} maximum zoom`} type="range" min="1" max="1.05" step="0.01" value={value.camera.max_zoom} onChange={(event) => update({ camera: { ...value.camera, max_zoom: Number(event.target.value) } })}/></label></section>
    <section className="control-group"><label className="switch-row"><span><strong>Visualizer</strong><small>Approximate bars</small></span><input aria-label={`${labelPrefix} visualizer`} type="checkbox" checked={value.visualizer.enabled} onChange={(event) => update({ visualizer: { ...value.visualizer, enabled: event.target.checked } })}/><i/></label><div className="two-fields"><label>Bars<input aria-label={`${labelPrefix} bar count`} type="number" min="8" max="64" value={value.visualizer.bar_count} onChange={(event) => update({ visualizer: { ...value.visualizer, bar_count: Number(event.target.value) } })}/></label><label>Opacity<input aria-label={`${labelPrefix} bar opacity`} type="number" min="0.1" max="1" step="0.05" value={value.visualizer.opacity} onChange={(event) => update({ visualizer: { ...value.visualizer, opacity: Number(event.target.value) } })}/></label></div></section>
    <section className="control-group"><label className="switch-row"><span><strong>Track progress</strong><small>Browser playback approximation</small></span><input aria-label={`${labelPrefix} track progress`} type="checkbox" checked={value.progress.enabled} onChange={(event) => update({ progress: { enabled: event.target.checked } })}/><i/></label></section>
    <section className="control-group"><label className="switch-row"><span><strong>Color treatment</strong><small>Approximate tint</small></span><input aria-label={`${labelPrefix} color treatment`} type="checkbox" checked={value.color_treatment.mode === 'custom'} onChange={(event) => update({ color_treatment: event.target.checked ? { mode: 'custom', hex: '#416E9D', intensity: 0.18 } : { mode: 'none' } })}/><i/></label>{value.color_treatment.mode === 'custom' && <><input aria-label={`${labelPrefix} tint color`} type="color" value={value.color_treatment.hex} onChange={(event) => update({ color_treatment: { mode: 'custom', hex: event.target.value, intensity: value.color_treatment.mode === 'custom' ? value.color_treatment.intensity : 0.18 } })}/><label className="range-label"><span>Intensity</span><strong>{Math.round(value.color_treatment.intensity * 100)}%</strong><input aria-label={`${labelPrefix} tint intensity`} type="range" min="0" max="0.6" step="0.01" value={value.color_treatment.intensity} onChange={(event) => update({ color_treatment: { mode: 'custom', hex: value.color_treatment.mode === 'custom' ? value.color_treatment.hex : '#416E9D', intensity: Number(event.target.value) } })}/></label></>}</section>
  </div>
}

export const V4EditorWorkspace = ({ workspace, initialState }: { workspace: ReviewWorkspace; initialState: CreationStateV4 }) => {
  const { state: studioState, dispatch, registerGuard, requestGuarded } = useStudio()
  const [state, setState] = useState(() => structuredClone(initialState))
  const [saved, setSaved] = useState(() => structuredClone(initialState))
  const [past, setPast] = useState<CreationStateV4[]>([])
  const [future, setFuture] = useState<CreationStateV4[]>([])
  const [category, setCategory] = useState<Category>('albums')
  const [selectedId, setSelectedId] = useState('')
  const [albumAssignment, setAlbumAssignment] = useState<Record<string, string>>({})
  const [templateChoice, setTemplateChoice] = useState('')
  const [updateDestination, setUpdateDestination] = useState('')
  const [updateScope, setUpdateScope] = useState<TemplateUpdateScope>('current')
  const [newTemplateName, setNewTemplateName] = useState('')
  const [libraryTemplateId, setLibraryTemplateId] = useState('')
  const [librarySearch, setLibrarySearch] = useState('')
  const [libraryFilter, setLibraryFilter] = useState<'all' | 'families' | 'standalone' | TemplateRole>('all')
  const [familyName, setFamilyName] = useState('')
  const [familySourceId, setFamilySourceId] = useState('')
  const [familySourceRole, setFamilySourceRole] = useState<TemplateRole>('album')
  const [cleanupPlan, setCleanupPlan] = useState<CleanupPlan | null>(null)
  const [cleanupBusy, setCleanupBusy] = useState(false)
  const [error, setError] = useState('')
  const [errorCode, setErrorCode] = useState('')
  const preview = useAudioPreview(workspace.projectId)
  const images = workspace.assets.filter((item) => item.kind === 'image' && item.presence === 'present' && typeof item.sha256 === 'string' && STRONG_SHA256.test(item.sha256) && item.capabilities.inspection.status === 'supported')
  const dependencyError = (candidate: VisualConfiguration) => {
    if (!candidate.background_image) return ''
    const asset = images.find((item) => item.asset_id === candidate.background_image?.asset_id)
    if (!asset) return 'The selected visual source is not a currently included, present, supported project image.'
    if (asset.sha256 !== candidate.background_image.expected_sha256) return 'The selected visual source fingerprint has changed. Review the image before using it in a new visual relationship.'
    return ''
  }
  const dirty = JSON.stringify(state) !== JSON.stringify(saved)
  const displayedIssues = currentV4Issues(state)
  const categoryAvailability = useMemo<Record<Category, boolean>>(() => ({
    albums: state.albums.some((item) => item.status === 'active'),
    singles: state.singles.some((item) => item.status === 'active'),
    shorts: state.shorts.some((item) => item.status === 'active'),
  }), [state.albums, state.shorts, state.singles])

  const change = useCallback((next: CreationStateV4) => {
    if (JSON.stringify(next) === JSON.stringify(state)) return
    setPast((items) => [...items.slice(-39), structuredClone(state)])
    setFuture([])
    setState(next)
    setCleanupPlan(null)
  }, [state])
  const persist = useCallback(async (): Promise<boolean> => {
    setError(''); setErrorCode('')
    try {
      const result = await saveCreationState(workspace.projectId, state)
      if (result.contract_version !== 'wrld-creation-state/4.0') throw new Error('The server did not return Creation v4 after Save.')
      setState(result); setSaved(structuredClone(result)); setPast([]); setFuture([]); setCleanupPlan(null)
      return true
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Editor changes could not be saved.')
      setErrorCode(cause instanceof ApiError ? cause.code : '')
      return false
    }
  }, [state, workspace.projectId])
  const discard = useCallback(() => { setState(structuredClone(saved)); setPast([]); setFuture([]); setError(''); setErrorCode(''); setCleanupPlan(null) }, [saved])
  useEffect(() => registerGuard({ dirty, save: persist, discard, label: 'Editor' }), [dirty, discard, persist, registerGuard])

  useEffect(() => {
    const requested = studioState.editorTarget
    if (!requested || requested.projectId !== workspace.projectId) return
    setCategory(requested.kind === 'album' ? 'albums' : requested.kind === 'single' ? 'singles' : 'shorts')
    setSelectedId(requested.id)
    dispatch({ type: 'consume-editor-target' })
  }, [dispatch, studioState.editorTarget, workspace.projectId])

  useEffect(() => {
    if (categoryAvailability[category]) return
    const next = CATEGORIES.find((item) => categoryAvailability[item])
    if (next) { setCategory(next); setSelectedId(''); setTemplateChoice('') }
  }, [category, categoryAvailability])

  const targets = targetList(state, workspace, category)
  const target = targets.find((item) => item.id === selectedId) ?? targets.find((item) => item.status === 'active') ?? targets[0]
  const targetRef = target ? { kind: target.kind, id: target.id } : null
  const composition = targetRef ? compositionFor(state, targetRef) : undefined
  const configuration = composition?.visual_configuration
  const familyChoices = target ? familyTemplateChoices(state, target.kind) : []
  const standaloneChoices = target ? standaloneTemplates(state, target.kind) : []
  const availableTemplateIds = new Set([...familyChoices.map((item) => item.template.visual_template_id), ...standaloneChoices.map((item) => item.visual_template_id)])
  const selectedTemplateChoice = availableTemplateIds.has(templateChoice) ? templateChoice : ''
  const sourceId = composition?.source_visual_template_id ?? null
  const selectedImage = configuration?.background_image ? workspace.assets.find((item) => item.asset_id === configuration.background_image?.asset_id) : undefined
  const imageUrl = selectedImage ? assetImageUrl(workspace.projectId, selectedImage.asset_id) : undefined
  const short = target?.kind === 'short' ? state.shorts.find((item) => item.short_id === target.id) : undefined
  const single = target?.kind === 'single' ? state.singles.find((item) => item.single_id === target.id) : undefined
  const album = target?.kind === 'album' ? state.albums.find((item) => item.album_plan_id === target.id) : undefined
  const assignmentId = album ? albumAssignment[album.album_plan_id] ?? album.assignments[0]?.assignment_id : undefined
  const assignment = album?.assignments.find((item) => item.assignment_id === assignmentId)
  const audioAsset = workspace.assets.find((item) => item.asset_id === (short?.asset_id ?? single?.asset_id ?? assignment?.asset_id))
  const playbackKey = target ? `editor-v4-${target.kind}-${target.id}-${assignmentId ?? ''}` : 'editor-v4-none'
  const shortStart = short ? short.start_sample / SAMPLE_RATE : undefined
  const shortEnd = short ? (short.start_sample + short.sample_count) / SAMPLE_RATE : undefined

  const applyTemplate = () => {
    if (!targetRef || !selectedTemplateChoice) return
    const selected = state.visual_templates.find((item) => item.visual_template_id === selectedTemplateChoice)
    if (!selected || !configuration) return
    const dependency = dependencyError(configurationFromTemplate(selected)); if (dependency) { setError(dependency); return }
    if (!configurationsEquivalent(configuration, configurationFromTemplate(selected)) && !window.confirm(`Apply ${selected.label} to ${target?.label}? This replaces this composition's current visual settings without changing the reusable template.`)) return
    try { change(applyTemplateToComposition(state, targetRef, selected.visual_template_id)); setError('') } catch (cause) { setError(cause instanceof Error ? cause.message : 'The template could not be applied.') }
  }
  const updateTemplate = () => {
    if (!targetRef || !updateDestination) return
    const destination = state.visual_templates.find((item) => item.visual_template_id === updateDestination)
    const membership = destination ? familyForTemplate(state, destination.visual_template_id) : null
    const scope = membership ? updateScope : 'current'
    const dependency = configuration ? dependencyError(configuration) : 'The selected composition has no visual configuration.'
    if (dependency) { setError(dependency); return }
    if (!destination || !window.confirm(`${scope === 'all' ? 'Update all three members of' : 'Overwrite'} ${membership ? `${membership.family.name} — ${ROLE_LABEL[membership.role]}` : destination.label} from ${target?.label}? Existing compositions will not change.`)) return
    try { change(updateTemplateFromComposition(state, targetRef, destination.visual_template_id, scope)); setError('') } catch (cause) { setError(cause instanceof Error ? cause.message : 'The template could not be updated.') }
  }
  const saveAsTemplate = () => {
    if (!targetRef) return
    const dependency = configuration ? dependencyError(configuration) : 'The selected composition has no visual configuration.'
    if (dependency) { setError(dependency); return }
    try { const next = saveCompositionAsTemplate(state, targetRef, newTemplateName); const created = next.visual_templates.at(-1)!; change(next); setLibraryTemplateId(created.visual_template_id); setNewTemplateName(''); setError('') } catch (cause) { setError(cause instanceof Error ? cause.message : 'The template could not be created.') }
  }
  const editConfiguration = (next: VisualConfiguration) => { if (targetRef) change(updateCompositionConfiguration(state, targetRef, next)) }
  const updateShortRange = (start: number, end: number) => {
    if (!short || !audioAsset) return
    const total = Math.max(1, Math.round((audioAsset.media.duration_seconds ?? 0) * SAMPLE_RATE)); const minimum = Math.min(5 * SAMPLE_RATE, total)
    const startSample = Math.min(Math.max(0, Math.round(start * SAMPLE_RATE)), Math.max(0, total - minimum)); const endSample = Math.min(total, Math.max(startSample + minimum, Math.round(end * SAMPLE_RATE)))
    change({ ...state, shorts: state.shorts.map((item) => item.short_id === short.short_id ? { ...item, start_sample: startSample, sample_count: endSample - startSample, origin: 'manual', review_required: endSample - startSample < minimum, customized: true, approved: false } : item) })
  }

  const memberIds = useMemo(() => new Set(state.visual_template_families.flatMap((family) => Object.values(family.members))), [state.visual_template_families])
  const filteredFamilies = state.visual_template_families.filter((family) => libraryFilter !== 'standalone' && (libraryFilter === 'all' || libraryFilter === 'families' || Object.entries(family.members).some(([key]) => key.startsWith(libraryFilter))) && `${family.name} ${family.visual_template_family_id}`.toLocaleLowerCase().includes(librarySearch.toLocaleLowerCase()))
  const filteredStandalone = state.visual_templates.filter((template) => !memberIds.has(template.visual_template_id) && libraryFilter !== 'families' && (libraryFilter === 'all' || libraryFilter === 'standalone' || template.canvas.aspect_ratio === (libraryFilter === 'short' ? '9:16' : '16:9')) && `${template.label} ${template.visual_template_id}`.toLocaleLowerCase().includes(librarySearch.toLocaleLowerCase()))
  const libraryTemplate = state.visual_templates.find((item) => item.visual_template_id === libraryTemplateId)
  const libraryMembership = libraryTemplate ? familyForTemplate(state, libraryTemplate.visual_template_id) : null
  const libraryUsage = libraryTemplate ? provenanceUsage(state, libraryTemplate.visual_template_id) : []
  const editLibraryTemplate = (next: VisualConfiguration) => {
    if (!libraryTemplate) return
    change({ ...state, visual_templates: state.visual_templates.map((item) => item.visual_template_id === libraryTemplate.visual_template_id ? { ...item, ...structuredClone(next) } : item) })
  }
  const runCleanupAnalysis = async () => { setCleanupBusy(true); setError(''); try { setCleanupPlan(await analyzeLegacyTemplates(state)) } catch (cause) { setError(cause instanceof Error ? cause.message : 'Cleanup analysis failed.') } finally { setCleanupBusy(false) } }
  const performCleanup = async () => {
    if (!cleanupPlan || !window.confirm(`Remove ${cleanupPlan.before - cleanupPlan.after} PROVEN_DISPOSABLE template(s)? REVIEW_REQUIRED and RETAIN entries will remain.`)) return
    setCleanupBusy(true); try { change(await applyLegacyCleanup(state, cleanupPlan, true)); setCleanupPlan(null) } catch (cause) { setError(cause instanceof Error ? cause.message : 'Cleanup could not be applied.') } finally { setCleanupBusy(false) }
  }

  const undo = () => { const previous = past.at(-1); if (!previous) return; setFuture([structuredClone(state), ...future]); setState(previous); setPast(past.slice(0, -1)); setCleanupPlan(null) }
  const redo = () => { const next = future[0]; if (!next) return; setPast([...past, structuredClone(state)]); setState(next); setFuture(future.slice(1)); setCleanupPlan(null) }

  return <>
    {error && <div className="mode-banner" role="alert">{error}{(errorCode === 'REVISION_CONFLICT' || errorCode === 'COMMIT_UNRESOLVED') && <span> Pending edits are preserved; reload only after deciding how to reconcile them.</span>}</div>}
    {preview.error && <div className="mode-banner" role="alert">Audio preview unavailable. {preview.error}</div>}
    {displayedIssues.length > 0 && <details className="mode-banner editor-warnings"><summary><AlertTriangle size={17}/><strong>Creation warnings ({displayedIssues.length})</strong><span>Warnings are revalidated against composition-owned settings when you Save.</span></summary><div className="warning-groups">{displayedIssues.map((issue, index) => 'draft_id' in issue ? <article key={`${issue.draft_id}:${issue.code}`}><div><code>{issue.draft_id}</code><span>{issue.code.replaceAll('_', ' ').toLocaleLowerCase()} · {issue.relative_path}</span></div><button onClick={() => requestGuarded(() => dispatch({ type: 'navigate', route: 'import' }))}>Review in Import</button></article> : <article key={`${issue.code}:${index}`}><div><code>{issue.visual_template_id ?? 'composition visual'}</code><span>{issue.code.replaceAll('_', ' ').toLocaleLowerCase()} · {issue.affected_targets.length} target(s)</span></div><div>{issue.affected_targets[0] && <button onClick={() => { const affected = issue.affected_targets[0]; setCategory(affected.kind === 'album' ? 'albums' : affected.kind === 'single' ? 'singles' : 'shorts'); setSelectedId(affected.id) }}>Edit dependency</button>}<button onClick={() => requestGuarded(() => dispatch({ type: 'navigate', route: 'import' }))}>Review in Import</button></div></article>)}</div></details>}
    <div className="editor-toolbar panel"><div><span className="eyebrow">Composition-owned Editor · Creation v4</span><strong>{target?.label ?? 'Visual Editor'}</strong><span>{target ? `${target.kind} · ${target.id}` : 'Choose an active Creation target.'}</span></div><div className="heading-actions"><button disabled={!past.length} onClick={undo}><Undo2 size={16}/> Undo</button><button disabled={!future.length} onClick={redo}><Redo2 size={16}/> Redo</button><button className="primary" disabled={!dirty} onClick={() => void persist()}><Save size={16}/> Save editor draft</button></div></div>
    <nav className="composition-categories" aria-label="Composition category">{CATEGORIES.map((item) => { const available = categoryAvailability[item]; const tooltipId = `v4-category-disabled-${item}`; return <span className="category-tab" key={item}><button className={category === item && available ? 'active' : ''} aria-current={category === item && available ? 'page' : undefined} aria-disabled={!available} aria-describedby={!available ? tooltipId : undefined} onClick={() => { if (!available) return; setCategory(item); setSelectedId(''); setTemplateChoice('') }}>{CATEGORY_LABEL[item]}</button>{!available && <span id={tooltipId} role="tooltip">Item Disabled. There are no {CATEGORY_LABEL[item]} selected.</span>}</span> })}</nav>
    {!CATEGORIES.some((item) => categoryAvailability[item]) || !target || !composition || !configuration ? <div className="panel empty-state"><strong>No active Creation outputs</strong><span>Create or restore an Album, Single, or Short in Creation before editing visual settings.</span><button onClick={() => requestGuarded(() => dispatch({ type: 'select-review-tab', tab: 'creation' }))}>Open Creation</button></div> : <div className="template-editor-grid v4-editor-grid">
      <aside className="panel target-rail"><div className="panel-title"><div><span className="eyebrow">Compositions</span><h2>{CATEGORY_LABEL[category]}</h2></div></div><div className="target-list">{targets.filter((item) => item.status === 'active').map((item) => <button key={item.id} className={target.id === item.id ? 'selected' : ''} onClick={() => { setSelectedId(item.id); setTemplateChoice('') }}><strong>{item.label}</strong><small>{item.id}</small></button>)}</div>{targets.some((item) => item.status === 'archived') && <details className="archived-targets"><summary><Archive size={13}/> Archived</summary>{targets.filter((item) => item.status === 'archived').map((item) => <button key={item.id} className={target.id === item.id ? 'selected' : ''} onClick={() => setSelectedId(item.id)}>{item.label}</button>)}</details>}</aside>
      <main className="template-preview-column"><div className="panel preview-panel"><CompositionPreview title={target.label} template={previewTemplate(configuration, target.label)} imageUrl={imageUrl} progress={preview.activeKey === playbackKey ? preview.progress : 0}/></div><div className="panel composition-audio"><div><span className="eyebrow">Audio source</span><strong>{audioAsset?.relative_path ?? 'Source unavailable'}</strong></div>{album && <select aria-label="Album track" value={assignmentId} onChange={(event) => setAlbumAssignment((current) => ({ ...current, [album.album_plan_id]: event.target.value }))}>{album.assignments.map((item, index) => <option key={item.assignment_id} value={item.assignment_id}>Track {index + 1}</option>)}</select>}<AudioPreviewButton asset={audioAsset} controller={preview} playbackKey={playbackKey} playLabel={`Play ${target.label}`} pauseLabel={`Pause ${target.label}`} startSeconds={shortStart} endSeconds={shortEnd}/></div>{short && audioAsset && <div className="panel short-range"><WaveformEditor duration={audioAsset.media.duration_seconds ?? shortEnd ?? 0} region={{ shortId: short.short_id, start: shortStart ?? 0, end: shortEnd ?? 0, approved: short.approved, reviewRequired: short.review_required }} audioUrl={assetAudioUrl(workspace.projectId, audioAsset.asset_id)} onChange={updateShortRange}/><button className={`approval-button ${short.approved ? 'approved' : ''}`} disabled={short.review_required} onClick={() => change({ ...state, shorts: state.shorts.map((item) => item.short_id === short.short_id ? { ...item, approved: !item.approved } : item) })}>{short.approved ? <Check size={16}/> : null}{short.approved ? 'Approved' : 'Approve Short'}</button></div>}</main>
      <aside className="panel template-inspector"><div className="panel-title"><div><span className="eyebrow">Composition settings</span><h2>Independent visual configuration</h2></div></div><div className="provenance-note"><strong>Historical source</strong><code>{sourceId ?? 'None'}</code><span>Provenance is not a live dependency.</span></div><VisualControls value={configuration} images={images} onChange={editConfiguration} labelPrefix="Composition"/>
        <section className="control-group template-action"><strong>Apply Template</strong><p>Selection is for inspection only until Apply is confirmed.</p><select aria-label="Template to apply" value={selectedTemplateChoice} onChange={(event) => setTemplateChoice(event.target.value)}><option value="">Choose a compatible template</option>{familyChoices.length > 0 && <optgroup label="Template families">{familyChoices.map((item) => <option key={item.template.visual_template_id} value={item.template.visual_template_id}>{item.family.name} — {ROLE_LABEL[item.role]} · {item.template.label}</option>)}</optgroup>}{standaloneChoices.length > 0 && <optgroup label="Standalone templates">{standaloneChoices.map((item) => <option key={item.visual_template_id} value={item.visual_template_id}>{item.label} — {item.canvas.aspect_ratio}</option>)}</optgroup>}</select><button className="primary" disabled={!selectedTemplateChoice} onClick={applyTemplate}>Apply Template</button></section>
        <section className="control-group template-action"><strong>Update Template</strong><select aria-label="Template to update" value={updateDestination} onChange={(event) => { setUpdateDestination(event.target.value); setUpdateScope('current') }}><option value="">Choose destination</option>{familyChoices.map((item) => <option key={item.template.visual_template_id} value={item.template.visual_template_id}>{item.family.name} — {ROLE_LABEL[item.role]}</option>)}{standaloneChoices.map((item) => <option key={item.visual_template_id} value={item.visual_template_id}>{item.label} — standalone</option>)}</select>{updateDestination && familyForTemplate(state, updateDestination) && <fieldset><legend>Family update scope</legend><label><input type="radio" name="v4-update-scope" checked={updateScope === 'current'} onChange={() => setUpdateScope('current')}/> Current Type Only</label><label><input type="radio" name="v4-update-scope" checked={updateScope === 'all'} onChange={() => setUpdateScope('all')}/> All Three Types</label></fieldset>}<button disabled={!updateDestination} onClick={updateTemplate}>Update Template</button></section>
        <section className="control-group template-action"><strong>Save as New Template</strong><input aria-label="New template name" maxLength={128} value={newTemplateName} onChange={(event) => setNewTemplateName(event.target.value)} placeholder="Meaningful template name"/><button disabled={!newTemplateName.trim()} onClick={saveAsTemplate}>Save as New Template</button></section>
      </aside>
    </div>}
    <section className="panel template-library"><div className="panel-title"><div><span className="eyebrow">Reusable presets</span><h2>Template Library</h2></div><span>{state.visual_template_families.length} families · {state.visual_templates.length - memberIds.size} standalone</span></div><div className="library-filters"><label><Search size={14}/><input aria-label="Search template library" value={librarySearch} onChange={(event) => setLibrarySearch(event.target.value)} placeholder="Search name or stable ID"/></label><select aria-label="Filter template library" value={libraryFilter} onChange={(event) => setLibraryFilter(event.target.value as typeof libraryFilter)}><option value="all">All templates</option><option value="families">Families</option><option value="standalone">Standalone</option><option value="album">Album compatible</option><option value="single">Single compatible</option><option value="short">Short compatible</option></select></div>
      <div className="library-grid"><div className="library-list"><h3>Families</h3>{filteredFamilies.map((family) => <details key={family.visual_template_family_id} open><summary><strong>{family.name}</strong><code>{family.visual_template_family_id}</code></summary>{familyVersions(state, family).map((version) => <button key={version.role} className={libraryTemplateId === version.templateId ? 'selected' : ''} onClick={() => setLibraryTemplateId(version.templateId)}><b>{ROLE_LABEL[version.role]}</b><span>{version.template?.label ?? 'Missing member'}</span><small>{version.templateId}</small></button>)}</details>)}<details open><summary><h3>Standalone ({filteredStandalone.length})</h3></summary>{filteredStandalone.map((template) => <button key={template.visual_template_id} className={libraryTemplateId === template.visual_template_id ? 'selected' : ''} onClick={() => setLibraryTemplateId(template.visual_template_id)}><strong>{template.label}</strong><span>{template.canvas.aspect_ratio}</span><small>{template.visual_template_id}</small></button>)}</details></div>
        <div className="library-editor">{libraryTemplate ? <><span className="eyebrow">Editing reusable template preset</span><h3>{libraryTemplate.label}</h3><code>{libraryTemplate.visual_template_id}</code><p>{libraryMembership ? `${libraryMembership.family.name} · ${ROLE_LABEL[libraryMembership.role]} member` : 'Standalone template'} · {libraryUsage.length} historical provenance reference{libraryUsage.length === 1 ? '' : 's'}. Composition visuals will not change.</p><VisualControls value={configurationFromTemplate(libraryTemplate)} images={images} onChange={editLibraryTemplate} labelPrefix="Template"/>{!libraryMembership && <div className="library-actions"><button onClick={() => { const name = window.prompt('Rename standalone template', libraryTemplate.label); if (name) try { change(renameStandaloneTemplate(state, libraryTemplate.visual_template_id, name)) } catch (cause) { setError(cause instanceof Error ? cause.message : 'Rename failed.') } }}>Rename</button><button onClick={() => { const name = window.prompt('Name for duplicated template', `${libraryTemplate.label} copy`); if (name) try { const next = duplicateStandaloneTemplate(state, libraryTemplate.visual_template_id, name); change(next); setLibraryTemplateId(next.visual_templates.at(-1)!.visual_template_id) } catch (cause) { setError(cause instanceof Error ? cause.message : 'Duplicate failed.') } }}><Copy size={14}/> Duplicate</button><button className="danger-action" onClick={() => { if (window.confirm(`Delete ${libraryTemplate.label}? Composition-owned visuals remain unchanged; historical provenance may reference the removed ID.`)) { change(deleteStandaloneTemplate(state, libraryTemplate.visual_template_id)); setLibraryTemplateId('') } }}><Trash2 size={14}/> Delete</button></div>}</> : <p>Select a family member or standalone template to inspect and edit its reusable preset independently.</p>}</div></div>
      <div className="family-management v4-family-management"><strong>Family management</strong><input aria-label="New family name" value={familyName} onChange={(event) => setFamilyName(event.target.value)} placeholder="New family name"/><select aria-label="Family starting template" value={familySourceId} onChange={(event) => { const value = event.target.value; setFamilySourceId(value); const source = state.visual_templates.find((item) => item.visual_template_id === value); setFamilySourceRole(source?.canvas.aspect_ratio === '9:16' ? 'short' : 'album') }}><option value="">Create neutral family</option>{state.visual_templates.filter((item) => !memberIds.has(item.visual_template_id)).map((item) => <option key={item.visual_template_id} value={item.visual_template_id}>Reuse {item.label} · {item.canvas.aspect_ratio}</option>)}</select>{familySourceId && state.visual_templates.find((item) => item.visual_template_id === familySourceId)?.canvas.aspect_ratio === '16:9' && <select aria-label="Starting template family role" value={familySourceRole} onChange={(event) => setFamilySourceRole(event.target.value as TemplateRole)}><option value="album">Album member</option><option value="single">Single member</option></select>}<button disabled={!familyName.trim()} onClick={() => { try { change(createTemplateFamilyV4(state, familyName, familySourceId || undefined, familySourceId ? familySourceRole : undefined)); setFamilyName(''); setFamilySourceId('') } catch (cause) { setError(cause instanceof Error ? cause.message : 'Family creation failed.') } }}>Create Family</button>{libraryMembership && <><button onClick={() => { const name = window.prompt('Rename family', libraryMembership.family.name); if (name) change(renameTemplateFamilyV4(state, libraryMembership.family.visual_template_family_id, name)) }}>Rename Family</button><button onClick={() => { if (window.confirm(`Remove grouping for ${libraryMembership.family.name}? All presets and composition visuals remain.`)) change(ungroupTemplateFamilyV4(state, libraryMembership.family.visual_template_family_id)) }}>Remove Family Grouping</button><button className="danger-action" onClick={() => { if (window.confirm(`Delete ${libraryMembership.family.name} and its three reusable presets? Composition-owned visuals remain unchanged.`)) { change(deleteTemplateFamilyV4(state, libraryMembership.family.visual_template_family_id)); setLibraryTemplateId('') } }}>Delete Unused Family</button></>}</div>
      <details className="cleanup-panel"><summary>Legacy template cleanup</summary><p>Cleanup never uses names alone and removes only verified PROVEN_DISPOSABLE generated artifacts. Family members are protected.</p><button disabled={cleanupBusy} onClick={() => void runCleanupAnalysis()}>{cleanupBusy ? 'Analyzing…' : 'Analyze legacy templates'}</button>{cleanupPlan && <><p><strong>{cleanupPlan.before}</strong> before · <strong>{cleanupPlan.after}</strong> after · revision {cleanupPlan.revision}</p><div className="cleanup-inventory"><span>{cleanupPlan.familyMemberCount} family members</span><span>{cleanupPlan.standaloneCount} standalone</span><span>{cleanupPlan.activeReferenceCount} active associations</span><span>{cleanupPlan.archivedReferenceCount} archived associations</span><span>{cleanupPlan.provenanceOnlyReferenceCount} provenance-only references</span><span>{cleanupPlan.unreferencedCount} unreferenced</span></div><div className="cleanup-candidates">{cleanupPlan.candidates.map((item) => <article key={item.templateId} data-classification={item.classification}><strong>{item.classification}</strong><span>{item.label}</span><code>{item.templateId}</code><p>{item.reason}</p><small>{item.provenance.length} provenance reference(s) · equivalence group {item.equivalenceGroup.length}</small></article>)}</div><button className="danger-action" disabled={cleanupPlan.before === cleanupPlan.after || cleanupBusy} onClick={() => void performCleanup()}>Apply authorized cleanup</button></>}</details>
    </section>
    <div className="inspector-note">The browser preview uses this composition's owned settings and remains approximate. Creation v4 is not silently substituted into the WU3 renderer.</div>
  </>
}
