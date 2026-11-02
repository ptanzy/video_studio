import { ArrowRight, Eye, EyeOff, Files, FolderOpen, HelpCircle, Image as ImageIcon, ListFilter, Music2, RefreshCw, Search, Trash2, Video, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  assetAudioUrl, assetImageUrl, assetThumbnailUrl, cancelInventoryScan, loadCatalog,
  loadDirectories, loadInventory, loadInventoryScan, loadProjectPreferences, loadRoots,
  registerProject, relinkAsset, relinkProject, removeProject, saveProjectPreferences, startInventoryScan,
} from '../../api/client'
import type { InventoryScan, ProjectDirectory, ProjectInventory, ProjectPreferences, ProjectRoot, ProjectSummary, ReviewWorkspace } from '../../api/types'
import { useStudio } from '../../app/state'

type MediaKind = 'audio' | 'image' | 'video'
type InclusionFilter = 'included' | 'excluded' | 'all'
const MEDIA_KINDS: MediaKind[] = ['audio', 'image', 'video']
const terminal = new Set(['completed', 'failed', 'cancelled'])
const statusLabel = (scan: InventoryScan | null) => !scan ? 'Ready' : scan.status === 'queued' ? 'Waiting to scan' : scan.status === 'running' ? 'Scanning' : scan.status === 'completed' ? 'Ready' : scan.status === 'cancelled' ? 'Scan cancelled' : 'Needs attention'
const projectName = (project: ProjectSummary | undefined) => project?.album_id ?? project?.relative_path.split('/').at(-1) ?? 'Project'
const reviewWorkspace = (projectId: string, project: ProjectSummary | undefined, inventory: ProjectInventory, preferences: ProjectPreferences): ReviewWorkspace => {
  const excluded = new Set(preferences.excluded_asset_ids)
  const includedAssets = inventory.assets.filter((asset) => asset.presence === 'present' && !excluded.has(asset.asset_id))
  const audio = includedAssets.filter((asset) => asset.kind === 'audio' && asset.sha256)
  return {
    projectId, sourceMode: 'inventory', name: projectName(project),
    artworkLabel: includedAssets.find((asset) => asset.kind === 'image')?.relative_path ?? 'No image selected',
    assets: includedAssets, allAssets: inventory.assets, excludedAssetIds: [...excluded],
    tracks: audio.map((asset, index) => ({
      id: asset.asset_id, number: index + 1, title: asset.relative_path.split('/').at(-1) ?? asset.relative_path,
      audio: asset.relative_path, normalized_sample_count: Math.max(1, Math.round((asset.media.duration_seconds ?? 0) * 48_000)),
      audio_sha256: asset.sha256 ?? '', durationSeconds: asset.media.duration_seconds ?? 0,
    })),
  }
}
const FilterButton = ({ label, tooltip, active, mode, icon, onClick }: { label: string; tooltip: string; active: boolean; mode: 'radio' | 'toggle'; icon: ReactNode; onClick: () => void }) => { const tooltipId = `filter-tooltip-${label.toLocaleLowerCase('en-US').replace(/[^a-z0-9]+/g, '-')}`; return <span className="filter-control"><button type="button" className={active ? 'active' : ''} aria-label={label} aria-describedby={tooltipId} role={mode === 'radio' ? 'radio' : undefined} aria-checked={mode === 'radio' ? active : undefined} aria-pressed={mode === 'toggle' ? active : undefined} onClick={onClick}>{icon}</button><span id={tooltipId} role="tooltip">{tooltip}</span></span> }

export const ImportPage = () => {
  const { state, dispatch } = useStudio()
  const [roots, setRoots] = useState<ProjectRoot[]>([])
  const [rootId, setRootId] = useState('')
  const [parent, setParent] = useState('')
  const [directories, setDirectories] = useState<ProjectDirectory[]>([])
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [projectId, setProjectId] = useState('')
  const [inventory, setInventory] = useState<ProjectInventory | null>(null)
  const [preferences, setPreferences] = useState<ProjectPreferences | null>(null)
  const [scans, setScans] = useState<Record<string, InventoryScan>>({})
  const [mediaTypes, setMediaTypes] = useState<Set<MediaKind>>(() => new Set(MEDIA_KINDS))
  const [inclusionFilter, setInclusionFilter] = useState<InclusionFilter>('included')
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [assetLocations, setAssetLocations] = useState<Record<string, string>>({})
  const projectIdRef = useRef(projectId)
  projectIdRef.current = projectId
  const scan = scans[projectId] ?? null

  const act = async (work: () => Promise<void>) => {
    setError('')
    try { await work() } catch (cause: unknown) { setError(cause instanceof Error ? cause.message : 'The Import operation failed.') }
  }
  const refreshProjects = useCallback(async () => {
    const catalog = await loadCatalog()
    const available = catalog.projects.filter((item) => item.availability !== 'removed')
    dispatch({ type: 'project-catalog-refreshed', projectIds: available.map((item) => item.project_id) })
    setProjects(available)
    setProjectId((current) => available.some((item) => item.project_id === current) ? current : available[0]?.project_id ?? '')
  }, [dispatch])
  useEffect(() => {
    void Promise.all([loadRoots(), refreshProjects()]).then(([value]) => {
      setRoots(value.roots); setRootId(value.roots[0]?.root_id ?? '')
    }).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : 'Import initialization failed.'))
  }, [refreshProjects])
  useEffect(() => {
    if (!rootId) return
    void loadDirectories(rootId, parent).then((value) => setDirectories(value.directories)).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : 'Folder browsing failed.'))
  }, [rootId, parent])
  useEffect(() => {
    if (!projectId) { setInventory(null); setPreferences(null); return }
    const controller = new AbortController()
    setInventory(null); setPreferences(null); setError('')
    void Promise.all([loadInventory(projectId, controller.signal), loadProjectPreferences(projectId, controller.signal)]).then(([nextInventory, nextPreferences]) => {
      if (!controller.signal.aborted && projectIdRef.current === projectId) { setInventory(nextInventory); setPreferences(nextPreferences) }
    }).catch((cause: unknown) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Project media could not be loaded.') })
    return () => controller.abort()
  }, [projectId])
  useEffect(() => {
    if (!scan || terminal.has(scan.status)) return
    const controller = new AbortController()
    const timer = window.setInterval(() => void loadInventoryScan(scan.project_id, scan.scan_id, controller.signal).then((value) => {
      if (controller.signal.aborted) return
      setScans((current) => ({ ...current, [value.project_id]: value }))
      if (value.status === 'completed') void loadInventory(value.project_id, controller.signal).then((next) => {
        if (!controller.signal.aborted && projectIdRef.current === value.project_id) setInventory(next)
      })
    }).catch((cause: unknown) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Scan status could not be refreshed.') }), 400)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [scan])

  const excluded = useMemo(() => new Set(preferences?.excluded_asset_ids ?? []), [preferences])
  const assets = useMemo(() => (inventory?.assets ?? []).filter((asset) => {
    const isExcluded = excluded.has(asset.asset_id)
    return mediaTypes.has(asset.kind as MediaKind)
      && (inclusionFilter === 'all' || (inclusionFilter === 'excluded') === isExcluded)
      && asset.relative_path.toLocaleLowerCase().includes(query.toLocaleLowerCase())
  }), [inventory, excluded, mediaTypes, inclusionFilter, query])
  const selectedProject = projects.find((item) => item.project_id === projectId)
  const includedCount = (inventory?.assets ?? []).filter((item) => item.presence === 'present' && !excluded.has(item.asset_id)).length

  useEffect(() => {
    if (!projectId || !selectedProject || !inventory || !preferences) return
    if (inventory.project_id !== projectId || preferences.project_id !== projectId) return
    dispatch({ type: 'import-project-selected', album: reviewWorkspace(projectId, selectedProject, inventory, preferences) })
  }, [dispatch, inventory, preferences, projectId, selectedProject])

  const register = (relativePath: string) => act(async () => {
    const created = await registerProject(rootId, relativePath)
    await refreshProjects(); setProjectId(created.project_id)
  })
  const beginScan = () => act(async () => {
    if (projectId) {
      const value = await startInventoryScan(projectId, scan?.status === 'failed' ? scan.scan_id : undefined)
      setScans((current) => ({ ...current, [projectId]: value }))
    }
  })
  const toggleMediaType = (kind: MediaKind) => setMediaTypes((current) => {
    if (current.size === MEDIA_KINDS.length) return new Set([kind])
    const next = new Set(current)
    if (next.has(kind)) { if (next.size > 1) next.delete(kind) }
    else next.add(kind)
    return next
  })
  const setExcluded = (assetId: string, value: boolean) => act(async () => {
    if (!preferences) return
    const next = new Set(preferences.excluded_asset_ids)
    if (value) next.add(assetId); else next.delete(assetId)
    setPreferences(await saveProjectPreferences(projectId, { ...preferences, excluded_asset_ids: [...next].sort() }))
  })
  const handoff = () => {
    if (!projectId || !inventory || !preferences) return
    const workspace = reviewWorkspace(projectId, selectedProject, inventory, preferences)
    dispatch({ type: 'import-handoff', album: workspace, handoff: { contract_version: 'wrld-import-handoff/2.0', project_id: projectId, inventory_revision: inventory.inventory_revision, preferences_revision: preferences.revision } })
  }

  return <>
    <section className="page-heading"><div><span className="kicker">01 · IMPORT</span><h1>Import Media</h1><p>Choose a music folder to discover and inspect its assets. Files stay in their original location.</p></div><button className="secondary" onClick={() => void act(async () => { await refreshProjects(); const selected = projectIdRef.current; if (selected) { const [nextInventory, nextPreferences] = await Promise.all([loadInventory(selected), loadProjectPreferences(selected)]); if (projectIdRef.current === selected) { setInventory(nextInventory); setPreferences(nextPreferences) } } })}><RefreshCw size={16}/> Refresh</button></section>
    <div className={`mode-banner ${state.backendStatus === 'connected' ? 'real' : ''}`} role="status"><FolderOpen size={17}/><div><strong>{state.backendStatus === 'connected' ? 'Import backend connected' : state.backendStatus === 'demo' ? 'Demonstration dataset active' : 'Import backend unavailable'}</strong><span>{error || state.backendMessage}</span></div>{state.backendStatus === 'error' && <button onClick={() => dispatch({ type: 'enable-demo' })}>Use demonstration data</button>}</div>
    <div className="import-workspace">
      <section className="panel import-browser">
        <div className="panel-title"><div><span className="eyebrow">My Projects</span><h2>{projects.length ? `${projects.length} project${projects.length === 1 ? '' : 's'}` : 'No projects yet'}</h2></div><span className="help-control" tabIndex={0} role="note" aria-label="About projects"><HelpCircle size={15}/><span>Projects register folders in place. Removing one never deletes its files.</span></span></div>
        <div className="project-list">{projects.map((project) => <div key={project.project_id} className={project.project_id === projectId ? 'selected' : ''}><button onClick={() => setProjectId(project.project_id)}><strong>{projectName(project)}</strong><small>{project.availability === 'available' ? 'Ready' : 'Missing files'} · {project.inventory_revision ?? 0} scan revision</small></button><button aria-label={`Remove ${projectName(project)} from My Projects`} onClick={() => void act(async () => { if (window.confirm('Remove this project registration? Source files will not be deleted.')) { await removeProject(project.project_id); await refreshProjects() } })}><Trash2 size={14}/></button></div>)}</div>
        {!projects.length && <div className="empty-state"><strong>Add your first folder</strong><span>Choose a folder inside a configured Music Location. WRLD Studio will inventory it without copying media.</span></div>}
        <details className="folder-browser" open={!projects.length}><summary><FolderOpen size={15}/> Add Folder</summary>
          <p className="helper-copy"><strong>Music Locations</strong> are secure browse boundaries configured by the application. Adding a folder registers a project; it does not move or copy anything.</p>
          <div className="import-controls"><select aria-label="Music Location" value={rootId} onChange={(event) => { setRootId(event.target.value); setParent('') }}>{roots.map((root) => <option key={root.root_id} value={root.root_id}>{root.label}</option>)}</select><button onClick={() => void register(parent)} disabled={!rootId}>Add This Folder</button></div>
          {!roots.length && <div className="empty-state">No Music Locations are configured. Configure a trusted location before adding a project.</div>}
          <div className="path-row"><button disabled={!parent} onClick={() => setParent(parent.split('/').slice(0,-1).join('/'))}>Up</button><code>{parent || '/'}</code></div>
          <div className="directory-list">{directories.map((directory) => <button key={directory.relative_path} onClick={() => setParent(directory.relative_path)}><FolderOpen size={15}/>{directory.name}</button>)}</div>
        </details>
        {selectedProject?.availability === 'unavailable' && <details className="advanced-controls" open><summary>Locate Missing Folder</summary><p className="helper-copy">Choose the folder's new location inside a Music Location. The project identity and saved preferences are preserved.</p><button disabled={!projectId || !rootId} onClick={() => void act(async () => { await relinkProject(projectId, rootId, parent); await refreshProjects() })}>Use This Folder</button></details>}
      </section>
      <section className="panel asset-panel">
        <div className="asset-toolbar"><div><span className="eyebrow">Project Media</span><h2>{inventory ? `${includedCount} included · ${excluded.size} excluded` : 'Choose a project'}</h2></div><div><button onClick={() => void beginScan()} disabled={!projectId || Boolean(scan && !terminal.has(scan.status))} title={!projectId ? 'Choose a project first' : 'Discover new, changed, and missing files'}><RefreshCw size={15}/> Scan for Files</button>{scan && !terminal.has(scan.status) && <button onClick={() => void cancelInventoryScan(scan.project_id, scan.scan_id).then((value) => setScans((current) => ({ ...current, [value.project_id]: value })))}><X size={15}/> Cancel</button>}</div></div>
        {scan && <div className={`scan-status ${scan.status}`} role="status"><strong>{statusLabel(scan)}</strong> · {scan.visited_entries} entries · {scan.discovered_assets} media files {scan.error?.message}</div>}
        {!inventory?.assets.length && <div className="empty-state"><strong>No media found yet</strong><span>Run Scan for Files. Empty projects are valid and can still be opened in Review.</span></div>}
        <div className="asset-filters"><label className="asset-search"><Search size={14}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter project paths…"/></label><div className="filter-group" role="radiogroup" aria-label="Inclusion filter"><span className="filter-group-label">Inclusion</span><div><FilterButton label="All inclusion" tooltip="Show included and excluded assets" active={inclusionFilter === 'all'} mode="radio" icon={<ListFilter size={15}/>} onClick={() => setInclusionFilter('all')}/><FilterButton label="Included" tooltip="Show included assets only" active={inclusionFilter === 'included'} mode="radio" icon={<Eye size={15}/>} onClick={() => setInclusionFilter('included')}/><FilterButton label="Excluded" tooltip="Show excluded assets only" active={inclusionFilter === 'excluded'} mode="radio" icon={<EyeOff size={15}/>} onClick={() => setInclusionFilter('excluded')}/></div></div><div className="filter-divider" aria-hidden="true"/><div className="filter-group" role="group" aria-label="Media type filter"><span className="filter-group-label">Media type</span><div><FilterButton label="All media types" tooltip="Show audio, image, and video assets" active={mediaTypes.size === MEDIA_KINDS.length} mode="toggle" icon={<Files size={15}/>} onClick={() => setMediaTypes(new Set(MEDIA_KINDS))}/><FilterButton label="Audio" tooltip="Toggle audio assets" active={mediaTypes.has('audio')} mode="toggle" icon={<Music2 size={15}/>} onClick={() => toggleMediaType('audio')}/><FilterButton label="Image" tooltip="Toggle image assets" active={mediaTypes.has('image')} mode="toggle" icon={<ImageIcon size={15}/>} onClick={() => toggleMediaType('image')}/><FilterButton label="Video" tooltip="Toggle video assets" active={mediaTypes.has('video')} mode="toggle" icon={<Video size={15}/>} onClick={() => toggleMediaType('video')}/></div></div></div>
        <div className="asset-grid">{assets.map((asset) => {
          const isExcluded = excluded.has(asset.asset_id)
          return <article key={asset.asset_id} className={isExcluded ? 'excluded' : ''}>
            {asset.kind === 'image' && asset.presence === 'present' && asset.capabilities.thumbnail.status === 'supported' ? <a className="asset-image" href={assetImageUrl(projectId, asset.asset_id)} target="_blank" rel="noreferrer"><img src={assetThumbnailUrl(projectId, asset.asset_id)} alt={`Preview of ${asset.relative_path}`}/></a> : <div className="asset-placeholder">{asset.presence === 'missing' ? 'MISSING' : asset.kind.toUpperCase()}</div>}
            <strong title={asset.relative_path}>{asset.relative_path.split('/').at(-1)}</strong><small>{asset.media.audio_codec ?? (asset.media.width ? `${asset.media.width}×${asset.media.height}` : asset.probe_status)}</small>
            {asset.kind === 'audio' && asset.presence === 'present' && asset.capabilities.server_stream.status === 'supported' ? <audio controls preload="metadata" src={assetAudioUrl(projectId, asset.asset_id)}/> : asset.kind === 'audio' && asset.presence === 'present' && <span className="unsupported-note">Audition unavailable · {asset.capabilities.server_stream.reason}</span>}
            {asset.kind === 'image' && asset.presence === 'present' && asset.capabilities.inspection.status === 'supported' ? <a href={assetImageUrl(projectId, asset.asset_id)} target="_blank" rel="noreferrer">Inspect full image</a> : asset.kind === 'image' && asset.presence === 'present' && <span className="unsupported-note">Inspection unavailable · {asset.capabilities.inspection.reason}</span>}
            {asset.kind === 'video' && <span className="unsupported-note">Discovered only · video composition belongs to WU8</span>}
            {asset.presence === 'missing' && <div className="asset-relink"><span className="unsupported-note">The saved asset identity is retained. Enter its new project-relative path.</span><input aria-label={`New location for ${asset.relative_path}`} value={assetLocations[asset.asset_id] ?? ''} onChange={(event) => setAssetLocations((value) => ({ ...value, [asset.asset_id]: event.target.value }))} placeholder="folder/replacement.wav"/><button disabled={!assetLocations[asset.asset_id]} title={!assetLocations[asset.asset_id] ? 'Enter a project-relative replacement path first.' : 'Verify and relink this stable asset identity.'} onClick={() => void act(async () => { await relinkAsset(projectId, asset.asset_id, assetLocations[asset.asset_id]); setInventory(await loadInventory(projectId)); setAssetLocations((value) => ({ ...value, [asset.asset_id]: '' })) })}>Relink asset</button></div>}
            <button className="asset-inclusion" onClick={() => void setExcluded(asset.asset_id, !isExcluded)} aria-label={`${isExcluded ? 'Restore' : 'Exclude'} ${asset.relative_path}`} title="This changes only the project workspace; the source file is never deleted.">{isExcluded ? <Eye size={14}/> : <EyeOff size={14}/>} {isExcluded ? 'Restore' : 'Exclude'}</button>
          </article>
        })}</div>
        <div className="handoff-bar" role="region" aria-label="Review handoff"><div className="handoff-summary" aria-live="polite"><strong>{projectId ? projectName(selectedProject) : 'No project selected'}</strong><span>{includedCount} included · {excluded.size} excluded · {statusLabel(scan)}</span><small>Exclusions remain reversible.</small></div><button className="primary" disabled={!projectId || !inventory || !preferences} onClick={handoff}>Open in Review <ArrowRight size={16}/></button></div>
      </section>
    </div>
  </>
}
