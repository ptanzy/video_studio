import { AlertTriangle, Check, Download, FilePlus2, Redo2, RefreshCw, Save, Undo2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ApiError, exportYouTubeMetadata, initializeYouTubeMetadata, loadCreationState, loadYouTubeMetadata,
  previewYouTubeMetadataExport, previewYouTubeMetadataReconcile, reconcileYouTubeMetadata,
  saveYouTubeMetadata, validateYouTubeMetadata,
} from '../../api/client'
import type { MetadataDiagnostic, MetadataValidation, YouTubeMetadataState } from '../../api/types'
import { useStudio } from '../../app/state'

type Target = YouTubeMetadataState['targets'][number]
type Content = Target['content']
type FieldName = keyof Content
type View = 'table' | 'detail'

const errorMessage = (value: unknown) => value instanceof Error ? value.message : 'The metadata operation failed.'
const targetLabel = (target: Target) => target.content.title.value || target.target_key
const splitComma = (value: string) => value.split(',').map((item) => item.trim()).filter(Boolean)
const splitLines = (value: string) => value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
const diagnosticSummary = (items: MetadataDiagnostic[]) => items.length ? `${items.filter((item) => item.severity === 'error').length} errors · ${items.filter((item) => item.severity === 'warning').length} warnings` : 'No issues'

export const MetadataWorkspace = () => {
  const { state: studio, registerGuard } = useStudio()
  const projectId = studio.selectedAlbumId
  const project = studio.albums.find((item) => item.projectId === projectId)
  const [saved, setSaved] = useState<YouTubeMetadataState | null>(null)
  const [draft, setDraft] = useState<YouTubeMetadataState | null>(null)
  const [past, setPast] = useState<YouTubeMetadataState[]>([])
  const [future, setFuture] = useState<YouTubeMetadataState[]>([])
  const [selectedKey, setSelectedKey] = useState('')
  const [exportKeys, setExportKeys] = useState<string[]>([])
  const [view, setView] = useState<View>('table')
  const [showInactive, setShowInactive] = useState(false)
  const [status, setStatus] = useState<'loading' | 'ready' | 'missing' | 'upgrade' | 'error'>('loading')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [validation, setValidation] = useState<MetadataValidation | null>(null)
  const dirty = Boolean(saved && draft && JSON.stringify(saved) !== JSON.stringify(draft))

  const accept = useCallback((value: YouTubeMetadataState) => {
    setSaved(value); setDraft(structuredClone(value)); setPast([]); setFuture([]); setValidation(null)
    setSelectedKey((current) => value.targets.some((item) => item.target_key === current) ? current : value.targets.find((item) => item.lifecycle === 'active')?.target_key ?? value.targets[0]?.target_key ?? '')
    setExportKeys((current) => current.filter((key) => value.targets.some((item) => item.target_key === key && item.lifecycle === 'active')))
    setStatus('ready')
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setStatus('loading'); setSaved(null); setDraft(null); setMessage(''); setValidation(null)
    if (!projectId) { setStatus('missing'); return () => controller.abort() }
    loadYouTubeMetadata(projectId, controller.signal).then(accept).catch((error: unknown) => {
      if (controller.signal.aborted) return
      if (error instanceof ApiError && error.code === 'METADATA_STATE_NOT_FOUND') setStatus('missing')
      else if (error instanceof ApiError && error.code === 'CREATION_UPGRADE_REQUIRED') setStatus('upgrade')
      else { setStatus('error'); setMessage(errorMessage(error)) }
    })
    return () => controller.abort()
  }, [accept, projectId])

  const save = useCallback(async () => {
    if (!draft || !projectId || busy) return false
    setBusy(true); setMessage('')
    try { const next = await saveYouTubeMetadata(projectId, draft); accept(next); setMessage(`Saved revision ${next.revision}.`); return true }
    catch (error) { setMessage(errorMessage(error)); return false }
    finally { setBusy(false) }
  }, [accept, busy, draft, projectId])

  useEffect(() => registerGuard({ dirty, save, discard: () => saved && accept(saved), label: 'Metadata' }), [accept, dirty, registerGuard, save, saved])

  const change = (mutate: (next: YouTubeMetadataState) => void) => {
    if (!draft) return
    const next = structuredClone(draft); mutate(next)
    setPast((items) => [...items.slice(-39), draft]); setDraft(next); setFuture([]); setValidation(null); setMessage('')
  }
  const undo = () => { const previous = past.at(-1); if (!previous || !draft) return; setPast((items) => items.slice(0, -1)); setFuture((items) => [draft, ...items]); setDraft(previous); setValidation(null) }
  const redo = () => { const next = future[0]; if (!next || !draft) return; setFuture((items) => items.slice(1)); setPast((items) => [...items, draft]); setDraft(next); setValidation(null) }
  const updateField = (targetKey: string, field: FieldName, value: Content[FieldName]['value']) => change((next) => {
    const target = next.targets.find((item) => item.target_key === targetKey)
    if (!target) return
    const current = target.content[field] as { value: unknown; origin: string; source_fingerprint: string | null }
    current.value = value; current.origin = 'edited'; current.source_fingerprint = null; target.approval = null
  })
  const updateChapter = (targetKey: string, trackId: string, value: string) => change((next) => {
    const target = next.targets.find((item) => item.target_key === targetKey)
    const entry = target?.chapters?.entries.find((item) => item.track_id === trackId)
    if (!target || !entry) return
    entry.label = { value, origin: 'edited', source_fingerprint: null }; target.approval = null
  })

  const initialize = async () => {
    if (!projectId) return
    setBusy(true); setMessage('')
    try {
      const creation = await loadCreationState(projectId)
      if (creation.contract_version !== 'wrld-creation-state/4.0') { setStatus('upgrade'); return }
      accept(await initializeYouTubeMetadata(projectId, creation))
      setMessage('Publishing metadata initialized from Creation v4. No legacy draft was imported.')
    } catch (error) { setMessage(errorMessage(error)) }
    finally { setBusy(false) }
  }

  const validate = async (mode: MetadataValidation['mode'] = 'draft', keys: string[] | null = null) => {
    if (!draft || !projectId) return null
    setBusy(true); setMessage('')
    try { const result = await validateYouTubeMetadata(projectId, draft, mode, keys); setValidation(result); setMessage(`${mode[0].toUpperCase()}${mode.slice(1)} validation: ${diagnosticSummary(result.diagnostics)}.`); return result }
    catch (error) { setMessage(errorMessage(error)); return null }
    finally { setBusy(false) }
  }

  const approve = async (target: Target) => {
    const result = await validate('approval', [target.target_key])
    const fingerprint = result?.target_fingerprints.find((item) => item.target_key === target.target_key)?.approval_fingerprint
    if (!result?.valid || !fingerprint) return
    change((next) => { const item = next.targets.find((candidate) => candidate.target_key === target.target_key); if (item) item.approval = { approved_fingerprint: fingerprint, approved_at: new Date().toISOString() } })
    setMessage('Approval added locally. Save to persist it.')
  }

  const reconcile = async () => {
    if (!draft || !projectId || dirty) { setMessage('Save or discard local edits before reconciling.'); return }
    setBusy(true); setMessage('')
    try {
      const preview = await previewYouTubeMetadataReconcile(projectId, draft)
      if (!preview.changes.length) { setMessage('Metadata is already reconciled with Creation.'); return }
      if (!window.confirm(`Apply ${preview.changes.length} metadata reconciliation change(s)? Existing field edits are preserved.`)) return
      accept(await reconcileYouTubeMetadata(projectId, draft, preview.preview_fingerprint)); setMessage(`Applied ${preview.changes.length} reconciliation change(s).`)
    } catch (error) { setMessage(errorMessage(error)) }
    finally { setBusy(false) }
  }

  const exportSelected = async () => {
    if (!draft || !projectId || dirty) { setMessage('Save approved metadata before exporting.'); return }
    if (!exportKeys.length) { setMessage('Select at least one active target to export.'); return }
    setBusy(true); setMessage('')
    try {
      const preview = await previewYouTubeMetadataExport(projectId, draft, exportKeys)
      setValidation({ contract_version: 'wrld-youtube-metadata-validation/1.0', mode: 'export', valid: preview.eligible, target_fingerprints: [], diagnostics: preview.diagnostics })
      if (!preview.eligible) { setMessage(`Export blocked: ${diagnosticSummary(preview.diagnostics)}.`); return }
      const replace = preview.existing_sha256 !== null
      if (!window.confirm(replace ? `Replace the existing owned export at its verified SHA-256? This exports ${exportKeys.length} selected target(s).` : `Export ${exportKeys.length} selected target(s) atomically?`)) return
      const result = await exportYouTubeMetadata(projectId, draft, exportKeys, preview, replace)
      setMessage(`${result.reused ? 'Reused' : 'Wrote'} ${result.path} (revision ${result.revision}, ${result.byte_size} bytes).`)
    } catch (error) { setMessage(errorMessage(error)) }
    finally { setBusy(false) }
  }

  const visible = useMemo(() => draft?.targets.filter((item) => showInactive || item.lifecycle === 'active') ?? [], [draft, showInactive])
  const selected = draft?.targets.find((item) => item.target_key === selectedKey) ?? visible[0]

  if (!projectId) return <Empty title="Select a project" body="Choose or import a project before opening its publishing metadata." />
  if (status === 'loading') return <Empty title="Loading publishing metadata" body="Reading project-local editor state…" />
  if (status === 'upgrade') return <Empty title="Creation v4 required" body="Upgrade this project's Creation workspace to v4 before initializing WU5 metadata." />
  if (status === 'missing') return <Empty title="Metadata is not initialized" body="Initialization creates deterministic project-local drafts for every Creation v4 Album, Single, and Short. It does not import legacy drafts or write portable output."><button className="primary" disabled={busy} onClick={() => void initialize()}><FilePlus2 size={16}/> Initialize metadata</button>{message && <p role="status">{message}</p>}</Empty>
  if (status === 'error' || !draft) return <Empty title="Metadata unavailable" body={message || 'The project-local metadata document could not be loaded.'} />

  return <>
    <section className="page-heading"><div><span className="kicker">03 · METADATA</span><h1>Publishing metadata</h1><p>Project-local drafts, target approval, and selected-set portable export for {project?.name ?? projectId}.</p></div><span className="status-chip">Revision {draft.revision}{dirty ? ' · unsaved' : ''}</span></section>
    <section className="metadata-toolbar panel" aria-label="Metadata actions">
      <div className="subworkspace-tabs" role="tablist" aria-label="Metadata view"><button className={view === 'table' ? 'active' : ''} role="tab" aria-selected={view === 'table'} onClick={() => setView('table')}>Table</button><button className={view === 'detail' ? 'active' : ''} role="tab" aria-selected={view === 'detail'} onClick={() => setView('detail')}>Detail</button></div>
      <div><button disabled={!past.length || busy} onClick={undo} aria-label="Undo metadata change"><Undo2 size={15}/></button><button disabled={!future.length || busy} onClick={redo} aria-label="Redo metadata change"><Redo2 size={15}/></button><button disabled={busy} onClick={() => void validate()}><Check size={15}/> Validate</button><button disabled={busy || dirty} onClick={() => void reconcile()}><RefreshCw size={15}/> Reconcile</button><button className="primary" disabled={!dirty || busy} onClick={() => void save()}><Save size={15}/> Save</button></div>
    </section>
    {message && <div className="metadata-message" role="status">{message}</div>}
    <div className="metadata-layout">
      <aside className="panel metadata-targets"><div className="panel-title"><div><span className="eyebrow">Creation v4 targets</span><h2>{visible.length} drafts</h2></div></div><label className="metadata-toggle"><input type="checkbox" checked={showInactive} onChange={(event) => setShowInactive(event.target.checked)}/> Show archived/orphaned</label><div>{visible.map((target) => <button key={target.target_key} className={selected?.target_key === target.target_key ? 'selected' : ''} onClick={() => setSelectedKey(target.target_key)}><strong>{targetLabel(target)}</strong><small>{target.target.kind} · {target.lifecycle}{target.approval ? ' · approved' : ''}</small></button>)}</div></aside>
      <main className="panel metadata-editor">{view === 'table' ? <MetadataTable targets={visible} exportKeys={exportKeys} setExportKeys={setExportKeys} select={setSelectedKey} updateField={updateField}/> : selected && <MetadataDetail target={selected} updateField={updateField} updateChapter={updateChapter} approve={() => void approve(selected)} unapprove={() => change((next) => { const item = next.targets.find((candidate) => candidate.target_key === selected.target_key); if (item) item.approval = null })}/>}</main>
      <aside className="panel metadata-validation"><div className="panel-title"><div><span className="eyebrow">Readiness</span><h2>{validation ? diagnosticSummary(validation.diagnostics) : 'Not checked'}</h2></div></div>{validation?.diagnostics.length ? <ul>{validation.diagnostics.map((item, index) => <li key={`${item.code}-${item.target_key}-${index}`} className={item.severity}><AlertTriangle size={13}/><span><strong>{item.code}</strong>{item.message}</span></li>)}</ul> : <p>Validate drafts before approval. Export revalidates saved state and approvals atomically.</p>}<div className="metadata-export"><strong>{exportKeys.length} selected</strong><button disabled={busy || !exportKeys.length || dirty} onClick={() => void exportSelected()}><Download size={15}/> Preview & export</button></div></aside>
    </div>
  </>
}

const Empty = ({ title, body, children }: { title: string; body: string; children?: React.ReactNode }) => <section className="future-hero panel metadata-empty"><span className="eyebrow">WU5 METADATA</span><h2>{title}</h2><p>{body}</p>{children}</section>

const MetadataTable = ({ targets, exportKeys, setExportKeys, select, updateField }: { targets: Target[]; exportKeys: string[]; setExportKeys: (value: string[]) => void; select: (key: string) => void; updateField: (key: string, field: FieldName, value: Content[FieldName]['value']) => void }) => <div className="metadata-table-wrap"><table className="metadata-table"><thead><tr><th scope="col">Export</th><th scope="col">Target</th><th scope="col">Title</th><th scope="col">Tags</th><th scope="col">Visibility</th><th scope="col">Status</th></tr></thead><tbody>{targets.map((target) => <tr key={target.target_key}><td><input type="checkbox" aria-label={`Select ${target.target_key} for export`} disabled={target.lifecycle !== 'active'} checked={exportKeys.includes(target.target_key)} onChange={(event) => setExportKeys(event.target.checked ? [...exportKeys, target.target_key] : exportKeys.filter((key) => key !== target.target_key))}/></td><th scope="row"><button onClick={() => select(target.target_key)}>{target.target_key}</button></th><td><input aria-label={`${target.target_key} title`} value={target.content.title.value} onChange={(event) => updateField(target.target_key, 'title', event.target.value)}/></td><td><input aria-label={`${target.target_key} tags`} value={target.content.tags.value.join(', ')} onChange={(event) => updateField(target.target_key, 'tags', splitComma(event.target.value))}/></td><td><select aria-label={`${target.target_key} visibility`} value={target.content.visibility.value} onChange={(event) => updateField(target.target_key, 'visibility', event.target.value as 'private' | 'unlisted' | 'public')}><option value="private">Private</option><option value="unlisted">Unlisted</option><option value="public">Public</option></select></td><td>{target.approval ? 'Approved' : 'Draft'}</td></tr>)}</tbody></table></div>

const MetadataDetail = ({ target, updateField, updateChapter, approve, unapprove }: { target: Target; updateField: (key: string, field: FieldName, value: Content[FieldName]['value']) => void; updateChapter: (key: string, trackId: string, value: string) => void; approve: () => void; unapprove: () => void }) => {
  const set = (field: FieldName, value: Content[FieldName]['value']) => updateField(target.target_key, field, value)
  return <div className="metadata-detail"><header><div><span className="eyebrow">{target.target.kind} · {target.lifecycle}</span><h2>{targetLabel(target)}</h2><code>{target.target_key}</code></div>{target.approval ? <button onClick={unapprove}>Remove approval</button> : <button onClick={approve}><Check size={15}/> Validate & approve</button>}</header><div className="metadata-form"><label>Title<input value={target.content.title.value} onChange={(event) => set('title', event.target.value)}/><small>{target.content.title.origin}</small></label><label>Visibility<select value={target.content.visibility.value} onChange={(event) => set('visibility', event.target.value as 'private' | 'unlisted' | 'public')}><option value="private">Private</option><option value="unlisted">Unlisted</option><option value="public">Public</option></select><small>{target.content.visibility.origin}</small></label><label className="wide">Description<textarea rows={8} value={target.content.description.value} onChange={(event) => set('description', event.target.value)}/><small>{target.content.description.origin} · placeholders remain visible until export resolution</small></label><label>Artist<input value={target.content.artist_name.value} onChange={(event) => set('artist_name', event.target.value)}/><small>{target.content.artist_name.origin}</small></label><label>Channel<input value={target.content.channel_name.value} onChange={(event) => set('channel_name', event.target.value)}/><small>{target.content.channel_name.origin}</small></label><label>Tags<input value={target.content.tags.value.join(', ')} onChange={(event) => set('tags', splitComma(event.target.value))}/></label><label>Hashtags<input value={target.content.hashtags.value.join(' ')} onChange={(event) => set('hashtags', splitLines(event.target.value.replace(/\s+/g, '\n')))}/></label><label className="wide">Pinned comment<textarea rows={3} value={target.content.pinned_comment.value ?? ''} onChange={(event) => set('pinned_comment', event.target.value || null)}/></label><label>Release Album plan ID<input value={target.content.release_album_plan_id.value ?? ''} onChange={(event) => set('release_album_plan_id', event.target.value || null)}/></label><label>Related compilation/video URL<input type="url" value={target.content.related_video_url.value ?? ''} onChange={(event) => set('related_video_url', event.target.value || null)}/></label><label className="wide">Credits (role | name)<textarea rows={3} value={target.content.credits.value.map((item) => `${item.role} | ${item.name}`).join('\n')} onChange={(event) => set('credits', splitLines(event.target.value).map((line) => { const [role, ...name] = line.split('|'); return { role: role.trim(), name: name.join('|').trim() } }).filter((item) => item.role && item.name))}/></label><label className="wide">Links (label | URL)<textarea rows={3} value={target.content.links.value.map((item) => `${item.label} | ${item.url}`).join('\n')} onChange={(event) => set('links', splitLines(event.target.value).map((line, index) => { const [label, ...url] = line.split('|'); return { key: `link-${index + 1}`, label: label.trim(), url: url.join('|').trim() } }).filter((item) => item.label && item.url))}/></label></div>{target.chapters && <section className="metadata-chapters"><h3>WU3A chapter timing</h3><p>Timing is authoritative and read-only. Labels are editable.</p>{target.chapters.entries.map((entry) => <label key={entry.track_id}><time>{formatTime(entry.start_seconds)}</time><input value={entry.label.value} onChange={(event) => updateChapter(target.target_key, entry.track_id, event.target.value)}/><small>{entry.track_id}</small></label>)}</section>}</div>
}

const formatTime = (seconds: number) => { const hours = Math.floor(seconds / 3600); const minutes = Math.floor(seconds % 3600 / 60); const rest = seconds % 60; return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}` : `${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}` }
