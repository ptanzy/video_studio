import { AlertTriangle, ArchiveRestore, ChevronDown, ChevronRight, ChevronUp, Minus, Plus, Redo2, Save, Trash2, Undo2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, loadAlbum, loadCreationState, saveCreationState } from '../../api/client'
import type { VisualConfiguration } from '../../api/generated/creation-state-v4'
import type { CreationAlbumAny, CreationIssue, CreationState, ReviewWorkspace, ShortDraftAny, SingleDraftAny, VisualSourceIssue } from '../../api/types'
import { useStudio } from '../../app/state'
import { AudioPreviewButton, useAudioPreview, type AudioPreviewController } from './AudioPreview'

const SAMPLE_RATE = 48_000
const STRONG_SHA256 = /^[0-9a-f]{64}$/
const id = (prefix: string) => `${prefix}-${crypto.randomUUID()}`
const fileName = (path: string) => path.split('/').at(-1) ?? path
const active = <T extends { status: 'active' | 'archived' }>(items: T[], assetId: string) => items.filter((item) => 'asset_id' in item && item.asset_id === assetId && item.status === 'active')
const naturalParts = (value: string) => value.toLocaleLowerCase('en-US').match(/\d+|\D+/g) ?? []
const naturalTextCompare = (left: string, right: string) => {
  const leftParts = naturalParts(left); const rightParts = naturalParts(right)
  for (let index = 0; index < Math.max(leftParts.length, rightParts.length); index += 1) {
    const a = leftParts[index]; const b = rightParts[index]
    if (a === undefined) return -1
    if (b === undefined) return 1
    if (a === b) continue
    if (/^\d+$/.test(a) && /^\d+$/.test(b)) {
      const normalizedA = a.replace(/^0+(?=\d)/, ''); const normalizedB = b.replace(/^0+(?=\d)/, '')
      if (normalizedA.length !== normalizedB.length) return normalizedA.length - normalizedB.length
      if (normalizedA !== normalizedB) return normalizedA < normalizedB ? -1 : 1
    }
    return a < b ? -1 : 1
  }
  return 0
}
const naturalAssetCompare = (left: ReviewWorkspace['assets'][number], right: ReviewWorkspace['assets'][number]) => naturalTextCompare(fileName(left.relative_path), fileName(right.relative_path)) || naturalTextCompare(left.relative_path, right.relative_path) || (left.asset_id < right.asset_id ? -1 : left.asset_id > right.asset_id ? 1 : 0)
const newVisualConfiguration = (aspectRatio: '16:9' | '9:16'): VisualConfiguration => ({
  canvas: { aspect_ratio: aspectRatio }, background_image: null,
  geometry: { fit_mode: 'contain', focal_x: 0.5, focal_y: 0.5 }, camera: { mode: 'static', max_zoom: 1.04 },
  visualizer: { enabled: false, bar_count: 24, opacity: 0.65 }, progress: { enabled: false }, color_treatment: { mode: 'none' },
})

const issueTargetReference = (state: CreationState, kind: 'album' | 'single' | 'short', targetId: string) => {
  if (state.contract_version === 'wrld-creation-state/1.0') return undefined
  if (state.contract_version === 'wrld-creation-state/4.0') {
    if (kind === 'album') return state.albums.find((item) => item.album_plan_id === targetId)?.source_visual_template_id
    if (kind === 'single') return state.singles.find((item) => item.single_id === targetId)?.source_visual_template_id
    return state.shorts.find((item) => item.short_id === targetId)?.source_visual_template_id
  }
  if (kind === 'album') return state.albums.find((item) => item.album_plan_id === targetId)?.visual_template_id
  if (kind === 'single') return state.singles.find((item) => item.single_id === targetId)?.visual_template_id
  return state.shorts.find((item) => item.short_id === targetId)?.visual_template_id
}

const currentCreationIssues = (state: CreationState, workspace: ReviewWorkspace): CreationIssue[] => {
  const assets = workspace.allAssets ?? workspace.assets
  const references = [
    ...state.albums.flatMap((album) => album.assignments.map((item) => ({ id: item.assignment_id, ...item }))),
    ...state.singles.map((item) => ({ id: item.single_id, ...item })),
    ...state.shorts.map((item) => ({ id: item.short_id, ...item })),
  ]
  const current: CreationIssue[] = []
  for (const issue of state.issues ?? []) {
    if ('draft_id' in issue) {
      const reference = references.find((item) => item.id === issue.draft_id)
      const asset = assets.find((item) => item.asset_id === issue.asset_id)
      if (!reference) { current.push(issue); continue }
      if (issue.code === 'SOURCE_CHANGED' && asset?.sha256 === reference.expected_sha256) continue
      if (issue.code === 'SOURCE_MISSING' && asset?.presence === 'present') continue
      current.push(issue); continue
    }
    if (state.contract_version === 'wrld-creation-state/1.0') { current.push(issue); continue }
    const template = issue.visual_template_id ? state.visual_templates.find((item) => item.visual_template_id === issue.visual_template_id) : undefined
    const affected = issue.affected_targets.filter((target) => {
      const reference = issueTargetReference(state, target.kind, target.id)
      if (issue.code === 'LEGACY_VISUAL_SETTINGS_UNMAPPED') return issue.visual_template_id ? reference === issue.visual_template_id : reference == null
      const background = state.contract_version === 'wrld-creation-state/4.0'
        ? (target.kind === 'album' ? state.albums.find((item) => item.album_plan_id === target.id) : target.kind === 'single' ? state.singles.find((item) => item.single_id === target.id) : state.shorts.find((item) => item.short_id === target.id))?.visual_configuration.background_image
        : template && reference === template.visual_template_id ? template.background_image : undefined
      if (issue.code === 'VISUAL_SOURCE_REQUIRED') return background === null
      if (!background || background.asset_id !== issue.asset_id) return false
      if (issue.code === 'VISUAL_SOURCE_CHANGED' && background.expected_sha256 !== issue.expected_sha256) return false
      return true
    })
    if (affected.length) current.push({ ...issue, affected_targets: affected })
  }
  return current
}

export const CreationWorkspace = ({ workspace }: { workspace: ReviewWorkspace }) => {
  const { dispatch, registerGuard, requestGuarded } = useStudio()
  const [state, setState] = useState<CreationState | null>(null)
  const [saved, setSaved] = useState<CreationState | null>(null)
  const [past, setPast] = useState<CreationState[]>([])
  const [future, setFuture] = useState<CreationState[]>([])
  const [error, setError] = useState('')
  const [errorCode, setErrorCode] = useState('')
  const [selectedByAlbum, setSelectedByAlbum] = useState<Record<string, string>>({})
  const [highlightOccurrence, setHighlightOccurrence] = useState('')
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [addingAlbum, setAddingAlbum] = useState(false)
  const [singleSelection, setSingleSelection] = useState<Set<string>>(() => new Set())
  const [shortSelection, setShortSelection] = useState<Set<string>>(() => new Set())
  const [operationSummary, setOperationSummary] = useState<Record<'singles' | 'shorts', string>>({ singles: '', shorts: '' })
  const loadGeneration = useRef(0)
  const projectIdRef = useRef(workspace.projectId)
  const stateRef = useRef<CreationState | null>(state)
  projectIdRef.current = workspace.projectId
  stateRef.current = state
  const audio = useMemo(() => workspace.assets.filter((item) => item.kind === 'audio' && item.presence === 'present' && typeof item.sha256 === 'string' && STRONG_SHA256.test(item.sha256)), [workspace.assets])
  const audioSelectionKey = useMemo(() => audio.map((item) => item.asset_id).join('\u0000'), [audio])
  const allAssets = workspace.allAssets ?? workspace.assets
  const excludedAssetIds = useMemo(() => new Set(workspace.excludedAssetIds ?? []), [workspace.excludedAssetIds])
  const preview = useAudioPreview(workspace.projectId)
  useEffect(() => {
    const selected = new Set(audioSelectionKey ? audioSelectionKey.split('\u0000') : [])
    setSingleSelection(new Set(selected)); setShortSelection(new Set(selected))
    setOperationSummary({ singles: '', shorts: '' })
  }, [workspace.projectId, audioSelectionKey])
  useEffect(() => {
    const controller = new AbortController()
    const generation = ++loadGeneration.current
    setState(null); setSaved(null); setError(''); setErrorCode('')
    void loadCreationState(workspace.projectId, controller.signal).then((value) => {
      if (controller.signal.aborted || generation !== loadGeneration.current) return
      setState(value); setSaved(structuredClone(value)); setPast([]); setFuture([]); setError(''); setErrorCode('')
    }).catch((cause: unknown) => {
      if (controller.signal.aborted || generation !== loadGeneration.current) return
      setError(cause instanceof Error ? cause.message : 'Creation state could not be loaded.')
    })
    return () => controller.abort()
  }, [workspace.projectId, loadAttempt])
  const isDirty = Boolean(state && saved && JSON.stringify(state) !== JSON.stringify(saved))
  const save = useCallback(async (): Promise<boolean> => {
    if (!state) return true
    setError(''); setErrorCode('')
    try { const next = await saveCreationState(workspace.projectId, state); setState(next); setSaved(structuredClone(next)); setPast([]); setFuture([]); return true }
    catch (cause: unknown) { setError(cause instanceof Error ? cause.message : 'Creation state could not be saved.'); setErrorCode(cause instanceof ApiError ? cause.code : ''); return false }
  }, [state, workspace.projectId])
  const discard = useCallback(() => { if (saved) { setState(structuredClone(saved)); setPast([]); setFuture([]); setError(''); setErrorCode('') } }, [saved])
  useEffect(() => {
    if (!state || !saved) return
    return registerGuard({ dirty: isDirty, save, discard, label: 'Creation' })
  }, [state, saved, isDirty, registerGuard, save, discard])
  if (!state) return <div className="panel empty-state"><strong>{error ? 'Creation workspace could not be loaded.' : 'Loading Creation workspace…'}</strong>{error && <><span role="alert">{error}</span><button onClick={() => setLoadAttempt((value) => value + 1)}>Retry</button></>}</div>

  const change = (next: CreationState) => { setPast((items) => [...items.slice(-39), structuredClone(state)]); setFuture([]); setState(next) }
  const replace = (patch: Partial<CreationState>) => change({ ...state, ...patch } as CreationState)
  const undo = () => { const previous = past.at(-1); if (!previous) return; setFuture([structuredClone(state), ...future]); setState(previous); setPast(past.slice(0, -1)) }
  const redo = () => { const next = future[0]; if (!next) return; setPast([...past, structuredClone(state)]); setState(next); setFuture(future.slice(1)) }
  const addAlbum = async (empty = false) => {
    const projectId = workspace.projectId
    setAddingAlbum(true)
    try {
      let ordered = [...audio].sort(naturalAssetCompare)
      if (!empty && ordered.length) {
        try {
          const manifest = await loadAlbum(projectId)
          const remaining = new Map(ordered.map((asset) => [asset.relative_path, asset]))
          const manifestOrdered = manifest.tracks.flatMap((track) => {
            const asset = remaining.get(track.audio)
            if (!asset) return []
            remaining.delete(track.audio)
            return [asset]
          })
          ordered = [...manifestOrdered, ...ordered.filter((asset) => remaining.has(asset.relative_path))]
        } catch {
          // Manifest enrichment is optional; deterministic natural ordering is the approved fallback.
        }
      }
      const current = stateRef.current
      if (projectIdRef.current !== projectId || !current) return
      const assignments = empty ? [] : ordered.map((asset) => ({ assignment_id: id('assignment'), asset_id: asset.asset_id, expected_sha256: asset.sha256!, duplicate_acknowledged: false }))
      const album = { album_plan_id: id('album-plan'), label: `Album ${current.albums.filter((item) => item.status === 'active').length + 1}`, status: 'active' as const, assignments }
      const created = current.contract_version === 'wrld-creation-state/1.0'
        ? album
        : current.contract_version === 'wrld-creation-state/4.0'
          ? { ...album, visual_configuration: newVisualConfiguration('16:9'), source_visual_template_id: null }
          : { ...album, visual_template_id: null }
      const next = { ...current, albums: [...current.albums, created] } as CreationState
      setPast((items) => [...items.slice(-39), structuredClone(current)])
      setFuture([])
      setState(next)
    } finally {
      if (projectIdRef.current === projectId) setAddingAlbum(false)
    }
  }
  const editAlbum = (albumId: string, update: (album: CreationAlbumAny) => CreationAlbumAny) => replace({ albums: state.albums.map((album) => album.album_plan_id === albumId ? update(album) : album) } as Partial<CreationState>)
  const addAssignment = (album: CreationAlbumAny) => {
    const assetId = selectedByAlbum[album.album_plan_id] ?? audio[0]?.asset_id
    const asset = audio.find((item) => item.asset_id === assetId)
    if (!asset?.sha256) return
    editAlbum(album.album_plan_id, (current) => ({ ...current, assignments: [...current.assignments, { assignment_id: id('assignment'), asset_id: asset.asset_id, expected_sha256: asset.sha256!, duplicate_acknowledged: false }] }))
  }
  const moveAssignment = (album: CreationAlbumAny, index: number, offset: number) => {
    const target = index + offset
    if (target < 0 || target >= album.assignments.length) return
    editAlbum(album.album_plan_id, (current) => { const assignments = [...current.assignments]; [assignments[index], assignments[target]] = [assignments[target], assignments[index]]; return { ...current, assignments } })
  }
  const removeAssignment = (album: CreationAlbumAny, assignmentId: string) => editAlbum(album.album_plan_id, (current) => ({ ...current, assignments: current.assignments.filter((item) => item.assignment_id !== assignmentId) }))
  const deleteAlbum = (album: CreationAlbumAny) => {
    if (album.assignments.length && !window.confirm(`Delete ${album.label} and remove its ${album.assignments.length} track assignment${album.assignments.length === 1 ? '' : 's'}? Source recordings, Singles, Shorts, and shared visual templates will be preserved.`)) return
    change({ ...state, albums: state.albums.filter((item) => item.album_plan_id !== album.album_plan_id) } as CreationState)
    setSelectedByAlbum((current) => { const next = { ...current }; delete next[album.album_plan_id]; return next })
  }
  const createSingle = (assetId: string): SingleDraftAny => {
    const asset = audio.find((item) => item.asset_id === assetId)!
    const draft = { single_id: id('single'), asset_id: assetId, expected_sha256: asset.sha256!, status: 'active' as const, customized: false, approved: false, settings: {} }
    return state.contract_version === 'wrld-creation-state/1.0' ? draft : state.contract_version === 'wrld-creation-state/4.0' ? { ...draft, visual_configuration: newVisualConfiguration('16:9'), source_visual_template_id: null } : { ...draft, visual_template_id: null }
  }
  const createShort = (assetId: string): ShortDraftAny => {
    const asset = audio.find((item) => item.asset_id === assetId)!
    const total = Math.max(1, Math.round((asset.media.duration_seconds ?? 0) * SAMPLE_RATE))
    const draft = { short_id: id('short'), asset_id: assetId, expected_sha256: asset.sha256!, status: 'active' as const, start_sample: 0, sample_count: Math.min(total, state.preferred_short_duration_seconds * SAMPLE_RATE), origin: 'manual_required' as const, review_required: true, customized: false, approved: false, settings: {} }
    return state.contract_version === 'wrld-creation-state/1.0' ? draft : state.contract_version === 'wrld-creation-state/4.0' ? { ...draft, visual_configuration: newVisualConfiguration('9:16'), source_visual_template_id: null } : { ...draft, visual_template_id: null }
  }
  const toggleRecordingSelection = (kind: 'singles' | 'shorts', assetId: string, selected: boolean) => {
    const update = (current: Set<string>) => { const next = new Set(current); if (selected) next.add(assetId); else next.delete(assetId); return next }
    if (kind === 'singles') setSingleSelection(update); else setShortSelection(update)
  }
  const addMissingSingles = () => {
    const represented = new Set(state.singles.map((item) => item.asset_id))
    const missing = audio.filter((item) => !represented.has(item.asset_id))
    const alreadyRepresented = audio.length - missing.length
    if (missing.length) change({ ...state, singles: [...state.singles, ...missing.map((item) => createSingle(item.asset_id))] } as CreationState)
    setOperationSummary((current) => ({ ...current, singles: `${missing.length} Single${missing.length === 1 ? '' : 's'} added · ${alreadyRepresented} recording${alreadyRepresented === 1 ? '' : 's'} already represented.` }))
  }
  const bulkAdjust = (kind: 'singles' | 'shorts', direction: 1 | -1) => {
    const selection = kind === 'singles' ? singleSelection : shortSelection
    const selected = audio.filter((item) => selection.has(item.asset_id))
    if (!selected.length) return
    const items = state[kind].map((item) => ({ ...item })) as Array<SingleDraftAny | ShortDraftAny>
    if (direction === 1) {
      let restored = 0; let created = 0
      selected.forEach((asset) => {
        const archived = items.find((item) => item.asset_id === asset.asset_id && item.status === 'archived')
        if (archived) { archived.status = 'active'; restored += 1 }
        else { items.push(kind === 'singles' ? createSingle(asset.asset_id) : createShort(asset.asset_id)); created += 1 }
      })
      const next = kind === 'singles' ? { ...state, singles: items as CreationState['singles'] } : { ...state, shorts: items as CreationState['shorts'] }
      change(next as CreationState)
      setOperationSummary((current) => ({ ...current, [kind]: `${kind === 'singles' ? 'Singles' : 'Shorts'}: ${created} created · ${restored} restored.` }))
      return
    }
    const candidates = selected.flatMap((asset) => {
      const current = items.filter((item) => item.asset_id === asset.asset_id && item.status === 'active')
      const candidate = [...current].reverse().find((item) => !item.customized && !item.approved) ?? current.at(-1)
      return candidate ? [candidate] : []
    })
    const protectedDrafts = candidates.filter((item) => item.customized || item.approved)
    if (protectedDrafts.length && !window.confirm(`Archive ${candidates.length} ${kind === 'singles' ? 'Single' : 'Short'} draft${candidates.length === 1 ? '' : 's'}, including ${protectedDrafts.length} customized or approved draft${protectedDrafts.length === 1 ? '' : 's'}? All can be restored later.`)) return
    candidates.forEach((candidate) => { candidate.status = 'archived' })
    const skipped = selected.length - candidates.length
    if (candidates.length) {
      const next = kind === 'singles' ? { ...state, singles: items as CreationState['singles'] } : { ...state, shorts: items as CreationState['shorts'] }
      change(next as CreationState)
    }
    setOperationSummary((current) => ({ ...current, [kind]: `${kind === 'singles' ? 'Singles' : 'Shorts'}: ${candidates.length} archived · ${skipped} skipped.` }))
  }
  const setCount = (kind: 'singles' | 'shorts', assetId: string, count: number) => {
    const items = state[kind].map((item) => ({ ...item })) as Array<SingleDraftAny | ShortDraftAny>
    const current = items.filter((item) => item.asset_id === assetId && item.status === 'active')
    if (count > current.length) {
      const archived = items.find((item) => item.asset_id === assetId && item.status === 'archived')
      if (archived) archived.status = 'active'
      else items.push(kind === 'singles' ? createSingle(assetId) : createShort(assetId))
    } else if (count < current.length) {
      const amount = count === 0 ? current.length : 1
      const candidates = count === 0 ? current : [([...current].reverse().find((item) => !item.customized && !item.approved) ?? current.at(-1))!]
      const protectedDrafts = candidates.filter((item) => item.customized || item.approved)
      if (protectedDrafts.length && !window.confirm(`Archive ${amount} draft${amount === 1 ? '' : 's'}, including customized or approved work? All can be restored later.`)) return
      candidates.forEach((candidate) => { candidate.status = 'archived' })
    }
    replace({ [kind]: items } as Partial<CreationState>)
  }
  const restore = (kind: 'singles' | 'shorts', draftId: string) => {
    const key = kind === 'singles' ? 'single_id' : 'short_id'
    replace({ [kind]: state[kind].map((item) => item[key as keyof typeof item] === draftId ? { ...item, status: 'active' } : item) } as Partial<CreationState>)
  }
  const editShort = (shortId: string, startSeconds: number, durationSeconds: number) => {
    replace({ shorts: state.shorts.map((item) => {
      if (item.short_id !== shortId) return item
      const asset = audio.find((candidate) => candidate.asset_id === item.asset_id)
      const total = Math.max(1, Math.round((asset?.media.duration_seconds ?? 0) * SAMPLE_RATE))
      const minimum = Math.min(5 * SAMPLE_RATE, total)
      const start = Math.min(Math.max(0, Math.round(startSeconds * SAMPLE_RATE)), Math.max(0, total - minimum))
      const requested = Math.max(minimum, Math.round(durationSeconds * SAMPLE_RATE))
      const count = Math.min(requested, total - start)
      const reviewRequired = count < 5 * SAMPLE_RATE
      return { ...item, start_sample: start, sample_count: count, origin: 'manual', review_required: reviewRequired, customized: true, approved: false }
    }) })
  }
  const acceptChangedSource = (assetId: string) => {
    const asset = workspace.assets.find((item) => item.asset_id === assetId)
    if (!asset?.sha256) return
    const protectedDraft = [...state.singles, ...state.shorts].some((item) => item.asset_id === assetId && item.approved)
    if (protectedDraft && !window.confirm('Accept this changed recording and invalidate approvals that referenced the previous bytes?')) return
    replace({
      albums: state.albums.map((album) => ({ ...album, assignments: album.assignments.map((item) => item.asset_id === assetId ? { ...item, expected_sha256: asset.sha256! } : item) })),
      singles: state.singles.map((item) => item.asset_id === assetId ? { ...item, expected_sha256: asset.sha256!, approved: false, customized: true } : item),
      shorts: state.shorts.map((item) => item.asset_id === assetId ? { ...item, expected_sha256: asset.sha256!, approved: false, customized: true, review_required: true } : item),
    })
  }

  const missingSingles = audio.filter((asset) => !state.singles.some((item) => item.asset_id === asset.asset_id)).length
  const displayedIssues = currentCreationIssues(state, workspace)
  const canRemoveSingles = state.singles.some((item) => item.status === 'active' && singleSelection.has(item.asset_id))
  const canRemoveShorts = state.shorts.some((item) => item.status === 'active' && shortSelection.has(item.asset_id))

  return <>
    <div className="creation-toolbar panel"><div><span className="eyebrow">Creation planning</span><h2>Albums, Singles & Shorts</h2><p>Drafts reference original recordings without copying media. Render readiness is validated later by WU6.</p></div><div className="heading-actions"><button disabled={!past.length} onClick={undo}><Undo2 size={15}/> Undo</button><button disabled={!future.length} onClick={redo}><Redo2 size={15}/> Redo</button><button className="primary" disabled={!isDirty} onClick={() => void save()}><Save size={15}/> Save Creation</button></div></div>
    {error && <div className="mode-banner" role="alert">{error}{(errorCode === 'REVISION_CONFLICT' || errorCode === 'COMMIT_UNRESOLVED') && <button onClick={() => void loadCreationState(workspace.projectId).then((value) => { setState(value); setSaved(structuredClone(value)); setPast([]); setFuture([]); setError(''); setErrorCode('') })}>Reload server state</button>}</div>}
    {preview.error && <div className="mode-banner" role="alert">Audio preview unavailable. {preview.error}</div>}
    {!!displayedIssues.length && <CreationWarnings issues={displayedIssues} state={state} workspace={workspace} onAcceptChanged={acceptChangedSource} onImport={() => requestGuarded(() => dispatch({ type: 'navigate', route: 'import' }))} onEditor={(target) => requestGuarded(() => dispatch({ type: 'open-editor-target', target: { projectId: workspace.projectId, kind: target.kind, id: target.id } }))}/>}
    <div className="creation-grid">
      <section className="panel creation-column"><div className="panel-title"><div><span className="eyebrow">Albums</span><h2>{state.albums.filter((item) => item.status === 'active').length} album plans</h2></div><div className="album-create-actions"><button disabled={addingAlbum} onClick={() => void addAlbum(false)}><Plus size={15}/> {addingAlbum ? 'Creating…' : 'Add Album'}</button><button disabled={addingAlbum} onClick={() => void addAlbum(true)}>Create Empty Album</button></div></div>
        {!state.albums.some((item) => item.status === 'active') && <div className="empty-state">Create an album plan, then add recordings in any order. The same recording may appear more than once.</div>}
        {state.albums.filter((item) => item.status === 'active').map((album) => <article className="creation-card" key={album.album_plan_id}><div className="album-card-heading"><input aria-label="Album label" value={album.label} onChange={(event) => editAlbum(album.album_plan_id, (item) => ({ ...item, label: event.target.value }))}/><button className="danger-action" aria-label={`Delete ${album.label}`} onClick={() => deleteAlbum(album)}><Trash2 size={13}/> Delete Album</button></div><div className="inline-add"><select aria-label={`Recording for ${album.label}`} value={selectedByAlbum[album.album_plan_id] ?? audio[0]?.asset_id ?? ''} onChange={(event) => setSelectedByAlbum((value) => ({ ...value, [album.album_plan_id]: event.target.value }))}>{audio.map((item) => <option key={item.asset_id} value={item.asset_id}>{fileName(item.relative_path)}</option>)}</select><button disabled={!audio.length} onClick={() => addAssignment(album)}>Add track</button></div>
          <ol className="assignment-list">{album.assignments.map((assignment, index) => {
            const duplicates = album.assignments.filter((item) => item.asset_id === assignment.asset_id)
            const repeated = duplicates.length > 1
            const asset = audio.find((item) => item.asset_id === assignment.asset_id)
            const inventoryAsset = allAssets.find((item) => item.asset_id === assignment.asset_id)
            const excluded = excludedAssetIds.has(assignment.asset_id)
            const label = fileName(inventoryAsset?.relative_path ?? assignment.asset_id)
            return <li id={`occurrence-${assignment.assignment_id}`} key={assignment.assignment_id} className={highlightOccurrence === `${album.album_plan_id}:${assignment.assignment_id}` ? 'highlighted' : ''}><span>{index + 1}</span><div className="recording-title"><strong>{label}</strong>{excluded && <small className="assignment-warning">Excluded from Import</small>}<AudioPreviewButton asset={asset} controller={preview} playbackKey={`album:${assignment.assignment_id}`} playLabel={`Play ${label}`} pauseLabel={`Pause ${label}`}/>{excluded && <button onClick={() => requestGuarded(() => dispatch({ type: 'navigate', route: 'import' }))}>Restore in Import</button>}</div><div><button title="Move this occurrence earlier" aria-label="Move track up" disabled={!index} onClick={() => moveAssignment(album, index, -1)}><ChevronUp size={13}/></button><button title="Move this occurrence later" aria-label="Move track down" disabled={index === album.assignments.length - 1} onClick={() => moveAssignment(album, index, 1)}><ChevronDown size={13}/></button><button title="Remove this assignment without deleting its source recording" aria-label="Remove track assignment" onClick={() => removeAssignment(album, assignment.assignment_id)}><Minus size={13}/></button></div>{repeated && <small>Repeated recording · <button onClick={() => { const next = duplicates[(duplicates.findIndex((item) => item.assignment_id === assignment.assignment_id) + 1) % duplicates.length]; setHighlightOccurrence(`${album.album_plan_id}:${next.assignment_id}`); document.getElementById(`occurrence-${next.assignment_id}`)?.scrollIntoView?.({ block: 'nearest' }) }}>next occurrence ({duplicates.length})</button><label><input type="checkbox" checked={assignment.duplicate_acknowledged} onChange={(event) => editAlbum(album.album_plan_id, (current) => ({ ...current, assignments: current.assignments.map((item) => item.assignment_id === assignment.assignment_id ? { ...item, duplicate_acknowledged: event.target.checked } : item) }))}/> intentional</label></small>}</li>
          })}</ol></article>)}
      </section>
      <DraftCountColumn title="Singles" assets={audio} items={state.singles} preview={preview} selectedRecordings={singleSelection} operationSummary={operationSummary.singles} missingCount={missingSingles} canBulkRemove={canRemoveSingles} onSelection={(assetId, selected) => toggleRecordingSelection('singles', assetId, selected)} onSelectAll={() => setSingleSelection(new Set(audio.map((item) => item.asset_id)))} onClear={() => setSingleSelection(new Set())} onAddMissing={addMissingSingles} onBulk={(direction) => bulkAdjust('singles', direction)} onCount={(assetId, count) => setCount('singles', assetId, count)} onRestore={(draftId) => restore('singles', draftId)} />
      <section className="panel creation-column"><div className="panel-title"><div><span className="eyebrow">Shorts</span><h2>{state.shorts.filter((item) => item.status === 'active').length} active drafts</h2></div><SectionSelection title="Shorts" count={shortSelection.size} total={audio.length} canRemove={canRemoveShorts} onSelectAll={() => setShortSelection(new Set(audio.map((item) => item.asset_id)))} onClear={() => setShortSelection(new Set())} onBulk={(direction) => bulkAdjust('shorts', direction)}/></div>{operationSummary.shorts && <span className="operation-summary section-summary" role="status" aria-live="polite">{operationSummary.shorts}</span>}<label className="duration-control">Preferred duration <input aria-label="Preferred Short duration" type="number" min="20" max="120" value={state.preferred_short_duration_seconds} onChange={(event) => replace({ preferred_short_duration_seconds: Number(event.target.value) })}/><span>seconds · automatic recommendations may vary by ±15 seconds</span></label><div className="analyzer-actions"><button disabled title="No approved WRLD Music Analyzer section contract is configured">Suggest Shorts</button><button disabled title="No approved WRLD Music Analyzer section contract is configured">Find Highlights</button><span>Analyzer recommendations unavailable. Create and edit ranges manually; no musical observations are being invented.</span></div>
        {audio.map((asset) => { const drafts = active(state.shorts, asset.asset_id) as ShortDraftAny[]; const archived = state.shorts.filter((item) => item.asset_id === asset.asset_id && item.status === 'archived'); const sourceSeconds = asset.media.duration_seconds ?? 0; const minimumSeconds = Math.min(5, sourceSeconds); const label = fileName(asset.relative_path); return <article className="draft-row" key={asset.asset_id}><div><label><input aria-label={`Select ${label} for Shorts bulk changes`} type="checkbox" checked={shortSelection.has(asset.asset_id)} onChange={(event) => toggleRecordingSelection('shorts', asset.asset_id, event.target.checked)}/><strong>{label}</strong></label><small>{drafts.length} active · {archived.length} archived</small></div><div className="count-control"><AudioPreviewButton asset={asset} controller={preview} playbackKey={`short-source:${asset.asset_id}`} playLabel={`Play ${label}`} pauseLabel={`Pause ${label}`}/><button aria-label={`Decrease Shorts for ${label}`} disabled={!drafts.length} onClick={() => setCount('shorts', asset.asset_id, drafts.length - 1)}><Minus size={13}/></button><output>{drafts.length}</output><button aria-label={`Increase Shorts for ${label}`} onClick={() => setCount('shorts', asset.asset_id, drafts.length + 1)}><Plus size={13}/></button></div>{(drafts.length > 0 || archived.length > 0) && <details className="draft-disclosure"><summary aria-label={`Edit ${drafts.length} active and ${archived.length} archived Short drafts for ${label}`}><ChevronRight size={12} aria-hidden="true"/> Edit drafts</summary>{drafts.map((draft) => <div className="draft-detail" key={draft.short_id}><code>{draft.short_id}</code><label>Start <input aria-label={`Start for ${draft.short_id}`} type="number" min="0" max={Math.max(0, sourceSeconds - minimumSeconds)} step="0.1" value={draft.start_sample / SAMPLE_RATE} onChange={(event) => editShort(draft.short_id, Number(event.target.value), draft.sample_count / SAMPLE_RATE)}/></label><label>Duration <input aria-label={`Duration for ${draft.short_id}`} type="number" min={minimumSeconds} max={sourceSeconds} step="0.1" value={draft.sample_count / SAMPLE_RATE} onChange={(event) => editShort(draft.short_id, draft.start_sample / SAMPLE_RATE, Number(event.target.value))}/></label><span>{draft.origin === 'manual_required' ? 'Manual range required' : 'Manual range'}</span><div className="draft-actions"><AudioPreviewButton asset={asset} controller={preview} playbackKey={`short-excerpt:${draft.short_id}`} playLabel={`Preview excerpt ${draft.short_id}`} pauseLabel={`Pause excerpt ${draft.short_id}`} startSeconds={draft.start_sample / SAMPLE_RATE} endSeconds={(draft.start_sample + draft.sample_count) / SAMPLE_RATE}/><button disabled title="No approved analyzer evidence is available for this selection">Explain This Selection</button></div></div>)}{archived.map((draft) => <button key={draft.short_id} onClick={() => restore('shorts', draft.short_id)}><ArchiveRestore size={13}/> Restore {draft.short_id}</button>)}</details>}</article> })}
      </section>
    </div>
  </>
}

const CreationWarnings = ({ issues, state, workspace, onAcceptChanged, onImport, onEditor }: { issues: CreationIssue[]; state: CreationState; workspace: ReviewWorkspace; onAcceptChanged: (assetId: string) => void; onImport: () => void; onEditor: (target: VisualSourceIssue['affected_targets'][number]) => void }) => {
  const assets = workspace.allAssets ?? workspace.assets
  const targetLabel = (kind: 'album' | 'single' | 'short', targetId: string) => {
    if (kind === 'album') return state.albums.find((item) => item.album_plan_id === targetId)?.label ?? targetId
    const item = kind === 'single' ? state.singles.find((candidate) => candidate.single_id === targetId) : state.shorts.find((candidate) => candidate.short_id === targetId)
    const path = item && assets.find((asset) => asset.asset_id === item.asset_id)?.relative_path
    return path ? fileName(path) : targetId
  }
  type WarningEntry = { issue: CreationIssue; target?: VisualSourceIssue['affected_targets'][number]; key: string; label: string; technicalId: string }
  const entries: WarningEntry[] = []
  issues.forEach((issue) => {
    if ('draft_id' in issue) entries.push({ issue, key: `${issue.code}:recording`, label: fileName(issue.relative_path || issue.asset_id), technicalId: issue.draft_id })
    else issue.affected_targets.forEach((target) => entries.push({ issue, target, key: `${issue.code}:${target.kind}`, label: targetLabel(target.kind, target.id), technicalId: target.id }))
  })
  const groups = [...new Set(entries.map((entry) => entry.key))].map((key) => ({ key, entries: entries.filter((entry) => entry.key === key) }))
  const groupLabel = (group: (typeof groups)[number]) => {
    const { issue } = group.entries[0]
    const count = group.entries.length
    if ('draft_id' in issue) return issue.code === 'SOURCE_MISSING' ? `${count} recording source${count === 1 ? '' : 's'} missing` : `${count} recording source${count === 1 ? '' : 's'} changed`
    const kind = group.key.split(':')[1]
    const noun = `${kind[0].toUpperCase()}${kind.slice(1)}${count === 1 ? '' : 's'}`
    if (issue.code === 'VISUAL_SOURCE_REQUIRED') return `${count} ${noun} need${count === 1 ? 's' : ''} a background`
    if (issue.code === 'VISUAL_SOURCE_MISSING') return `${count} ${noun} ${count === 1 ? 'has' : 'have'} a missing background`
    if (issue.code === 'VISUAL_SOURCE_CHANGED') return `${count} ${noun} ${count === 1 ? 'has' : 'have'} a changed background`
    if (issue.code === 'VISUAL_SOURCE_EXCLUDED') return `${count} ${noun} use${count === 1 ? 's' : ''} an excluded background`
    if (issue.code === 'VISUAL_SOURCE_UNSUPPORTED') return `${count} ${noun} use${count === 1 ? 's' : ''} an unsupported background`
    return `${count} ${noun} need${count === 1 ? 's' : ''} visual settings review`
  }
  return <details className="panel creation-warnings"><summary onKeyDown={(event) => { if (event.key !== 'Enter' && event.key !== ' ') return; event.preventDefault(); const details = event.currentTarget.parentElement as HTMLDetailsElement; details.open = !details.open }}><AlertTriangle size={17}/><strong>Creation warnings ({issues.length})</strong><span>Unresolved warnings remain; expand to review.</span><ChevronRight className="disclosure-arrow" size={16}/></summary><div className="creation-warning-groups">{groups.map((group) => <section key={group.key}><h3>{groupLabel(group)}</h3>{group.entries.map((entry, index) => {
    const issue = entry.issue
    return <article key={`${entry.technicalId}-${issue.code}-${index}`}><div><strong>{entry.label}</strong><code>{entry.technicalId}{'draft_id' in issue ? '' : ` · ${issue.visual_template_id ?? 'No typed template'}`}</code></div><div>{'draft_id' in issue ? issue.code === 'SOURCE_CHANGED' ? <button onClick={() => onAcceptChanged(issue.asset_id)}>Accept changed source</button> : <button onClick={onImport}>Relink in Import</button> : <><button onClick={() => entry.target && onEditor(entry.target)}>Review in Editor</button>{(issue.code === 'VISUAL_SOURCE_MISSING' || issue.code === 'VISUAL_SOURCE_EXCLUDED') && <button onClick={onImport}>Review in Import</button>}</>}</div></article>
  })}</section>)}</div><p>The server revalidates unresolved dependencies on Save.</p></details>
}

const SectionSelection = ({ title, count, total, canRemove, onSelectAll, onClear, onBulk }: { title: 'Singles' | 'Shorts'; count: number; total: number; canRemove: boolean; onSelectAll: () => void; onClear: () => void; onBulk: (direction: 1 | -1) => void }) => <div className="section-selection"><span>{count} of {total} selected</span><div className="draft-section-actions"><button disabled={count === total} onClick={onSelectAll}>Select All</button><button disabled={!count} onClick={onClear}>Clear</button><button aria-label={`Increase all selected ${title}`} disabled={!count} onClick={() => onBulk(1)}><Plus size={13}/> All</button><button aria-label={`Decrease all selected ${title}`} disabled={!canRemove} onClick={() => onBulk(-1)}><Minus size={13}/> All</button></div></div>

const DraftCountColumn = ({ title, assets, items, preview, selectedRecordings, operationSummary, missingCount, canBulkRemove, onSelection, onSelectAll, onClear, onAddMissing, onBulk, onCount, onRestore }: { title: 'Singles'; assets: ReviewWorkspace['assets']; items: SingleDraftAny[]; preview: AudioPreviewController; selectedRecordings: Set<string>; operationSummary: string; missingCount: number; canBulkRemove: boolean; onSelection: (assetId: string, selected: boolean) => void; onSelectAll: () => void; onClear: () => void; onAddMissing: () => void; onBulk: (direction: 1 | -1) => void; onCount: (assetId: string, count: number) => void; onRestore: (draftId: string) => void }) => <section className="panel creation-column"><div className="panel-title"><div><span className="eyebrow">{title}</span><h2>{items.filter((item) => item.status === 'active').length} active drafts</h2></div><div><button disabled={!missingCount} title={!missingCount ? 'Every included recording already has an active or archived Single.' : undefined} onClick={onAddMissing}>Add Missing Singles</button><SectionSelection title={title} count={selectedRecordings.size} total={assets.length} canRemove={canBulkRemove} onSelectAll={onSelectAll} onClear={onClear} onBulk={onBulk}/></div></div>{operationSummary && <span className="operation-summary section-summary" role="status" aria-live="polite">{operationSummary}</span>}{assets.map((asset) => { const drafts = active(items, asset.asset_id) as SingleDraftAny[]; const archived = items.filter((item) => item.asset_id === asset.asset_id && item.status === 'archived'); const label = fileName(asset.relative_path); return <article className="draft-row" key={asset.asset_id}><div><label><input aria-label={`Select ${label} for Singles bulk changes`} type="checkbox" checked={selectedRecordings.has(asset.asset_id)} onChange={(event) => onSelection(asset.asset_id, event.target.checked)}/><strong>{label}</strong></label><small>{drafts.length} active · {archived.length} archived</small></div><div className="count-control"><AudioPreviewButton asset={asset} controller={preview} playbackKey={`single-source:${asset.asset_id}`} playLabel={`Play ${label}`} pauseLabel={`Pause ${label}`}/><button aria-label={`Decrease ${title} for ${label}`} disabled={!drafts.length} onClick={() => onCount(asset.asset_id, drafts.length - 1)}><Minus size={13}/></button><output>{drafts.length}</output><button aria-label={`Increase ${title} for ${label}`} onClick={() => onCount(asset.asset_id, drafts.length + 1)}><Plus size={13}/></button></div>{archived.length > 0 && <details className="draft-disclosure"><summary aria-label={`${archived.length} archived Single drafts for ${label}`}><ChevronRight size={12} aria-hidden="true"/> Archived drafts</summary>{archived.map((draft) => <button key={draft.single_id} onClick={() => onRestore(draft.single_id)}><ArchiveRestore size={13}/> Restore {draft.single_id}</button>)}</details>}</article>})}</section>
