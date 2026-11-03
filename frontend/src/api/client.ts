import type { AlbumRead, CatalogResponse, CreationState, CreationStateDocument, InventoryScan, MetadataExportPreview, MetadataExportResult, MetadataReconcilePreview, MetadataValidation, ProjectDirectory, ProjectInventory, ProjectPreferences, ProjectRoot, ProjectSummary, StudioAlbum, ValidationReport, YouTubeMetadataState } from './types'

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly code = 'REQUEST_FAILED', readonly details: Record<string, unknown> = {}) { super(message) }
}

const json = async <T>(response: Response): Promise<T> => {
  const contentType = response.headers?.get?.('content-type')?.split(';', 1)[0]?.trim().toLowerCase() ?? ''
  const responseUrl = response.url || 'the requested API endpoint'
  const invalidResponse = (cause?: unknown) => new ApiError(
    contentType === 'text/html'
      ? `The API request returned HTML instead of JSON from ${responseUrl}. Restart the Vite development server so its /api proxy targets the running backend at http://127.0.0.1:8000.`
      : `The API response from ${responseUrl} was not valid JSON${contentType ? ` (Content-Type: ${contentType})` : ''}. Verify that the local backend and frontend proxy are running with the current configuration.`,
    response.status,
    'API_RESPONSE_INVALID',
    { response_url: response.url || null, content_type: contentType || null, http_status: response.status, cause: cause instanceof Error ? cause.message : null },
  )
  if (contentType && contentType !== 'application/json' && !contentType.endsWith('+json')) throw invalidResponse()
  if (!response.ok) {
    const body = (await response.json().catch((cause: unknown) => { throw invalidResponse(cause) })) as { error?: { code?: string; message?: string; details?: Record<string, unknown> }; detail?: string } | null
    throw new ApiError(body?.error?.message ?? `Request failed (${response.status})`, response.status, body?.error?.code, body?.error?.details)
  }
  try { return await response.json() as T }
  catch (cause) { throw invalidResponse(cause) }
}

export const loadBackendAlbums = async (signal?: AbortSignal): Promise<StudioAlbum[]> => {
  const catalog = await json<CatalogResponse>(await fetch('/api/v1/projects', { signal }))
  const available = catalog.projects.filter((project) => project.availability === 'available')
  return Promise.all(available.map(async (project) => {
    const [album, validation] = await Promise.all([
      json<AlbumRead>(await fetch(`/api/v1/projects/${encodeURIComponent(project.project_id)}/album`, { signal })),
      json<ValidationReport>(await fetch(`/api/v1/projects/${encodeURIComponent(project.project_id)}/validation`, { method: 'POST', signal })),
    ])
    return {
      projectId: project.project_id,
      sourceMode: 'backend' as const,
      title: album.album.title,
      artist: album.album.artist,
      channel: album.album.channel,
      artworkLabel: album.visual.cover ?? album.visual.background,
      profileId: album.render.profile_id,
      valid: validation.valid,
      tracks: album.tracks.map((track) => ({ ...track, durationSeconds: track.normalized_sample_count / 48_000 })),
    }
  }))
}
export const loadAlbum = async (projectId: string, signal?: AbortSignal) =>
  json<AlbumRead>(await fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/album`, { signal }))

export const audioUrl = (projectId: string, trackId: string): string =>
  `/api/v1/projects/${encodeURIComponent(projectId)}/tracks/${encodeURIComponent(trackId)}/audio`

export const loadRoots = async (signal?: AbortSignal) => json<{ roots: ProjectRoot[] }>(await fetch('/api/v1/project-roots', { signal }))
export const loadDirectories = async (rootId: string, parent = '', signal?: AbortSignal) => json<{ directories: ProjectDirectory[] }>(await fetch(`/api/v1/project-roots/${encodeURIComponent(rootId)}/directories?parent=${encodeURIComponent(parent)}`, { signal }))
export const loadCatalog = async (signal?: AbortSignal) => json<CatalogResponse>(await fetch('/api/v1/projects', { signal }))
export const registerProject = async (rootId: string, relativePath: string) => json<ProjectSummary>(await fetch('/api/v1/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ root_id: rootId, relative_path: relativePath }) }))
export const removeProject = async (projectId: string) => { const response = await fetch(`/api/v1/projects/${encodeURIComponent(projectId)}`, { method: 'DELETE' }); if (!response.ok) await json(response) }
export const relinkProject = async (projectId: string, rootId: string, relativePath: string) => json<ProjectSummary>(await fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/location`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ root_id: rootId, relative_path: relativePath }) }))
export const loadInventory = async (projectId: string, signal?: AbortSignal) => json<ProjectInventory>(await fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/inventory`, { signal }))
export const startInventoryScan = async (projectId: string, retryOf?: string) => json<InventoryScan>(await fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/inventory-scans`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ retry_of_scan_id: retryOf ?? null }) }))
export const loadInventoryScan = async (projectId: string, scanId: string, signal?: AbortSignal) => json<InventoryScan>(await fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/inventory-scans/${encodeURIComponent(scanId)}`, { signal }))
export const cancelInventoryScan = async (projectId: string, scanId: string) => json<InventoryScan>(await fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/inventory-scans/${encodeURIComponent(scanId)}`, { method: 'DELETE' }))
export const relinkAsset = async (projectId: string, assetId: string, relativePath: string) => json(await fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/location`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ relative_path: relativePath }) }))
export const assetAudioUrl = (projectId: string, assetId: string) => `/api/v1/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/audio`
export const assetImageUrl = (projectId: string, assetId: string) => `/api/v1/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/image`
export const assetThumbnailUrl = (projectId: string, assetId: string, variant: 'small' | 'large' = 'small') => `/api/v1/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/thumbnails/${variant}`
export const loadProjectPreferences = async (projectId: string, signal?: AbortSignal) => json<ProjectPreferences>(await fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/preferences`, { signal }))
const saveDocument = async <T extends { revision: number; save_id: string; state_digest: string }>(url: string, state: T, reload: () => Promise<T>): Promise<T> => {
  const saveId = crypto.randomUUID()
  try {
    return await json<T>(await fetch(url, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: state.revision, save_id: saveId, state }) }))
  } catch (cause) {
    if (!(cause instanceof ApiError) || cause.code !== 'COMMIT_INDETERMINATE') throw cause
    const latest = await reload()
    const candidateRevision = cause.details.candidate_revision
    const candidateDigest = cause.details.state_digest
    if (latest.save_id === saveId && latest.revision === candidateRevision && latest.state_digest === candidateDigest) return latest
    throw new ApiError('The save outcome could not be confirmed. Reload and compare before saving again.', 500, 'COMMIT_UNRESOLVED', cause.details)
  }
}
export const saveProjectPreferences = async (projectId: string, state: ProjectPreferences) => saveDocument(`/api/v1/projects/${encodeURIComponent(projectId)}/preferences`, state, () => loadProjectPreferences(projectId))
const editableCreationState = (state: CreationStateDocument): CreationState => {
  const version = (state as { contract_version?: unknown }).contract_version
  if (version !== 'wrld-creation-state/1.0' && version !== 'wrld-creation-state/2.0' && version !== 'wrld-creation-state/3.0' && version !== 'wrld-creation-state/4.0') {
    throw new ApiError(
      'This Creation document version is not supported by this application. Reload with a compatible version before editing.',
      409,
      'CREATION_STATE_VERSION_UNSUPPORTED',
      { contract_version: typeof version === 'string' ? version : null },
    )
  }
  return state as CreationState
}
export const loadCreationState = async (projectId: string, signal?: AbortSignal) => editableCreationState(await json<CreationStateDocument>(await fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/creation-state`, { signal })))
export const saveCreationState = async (projectId: string, state: CreationState) => saveDocument(`/api/v1/projects/${encodeURIComponent(projectId)}/creation-state`, state, () => loadCreationState(projectId))
const metadataUrl = (projectId: string) => `/api/v1/projects/${encodeURIComponent(projectId)}/youtube-metadata`
export const loadYouTubeMetadata = async (projectId: string, signal?: AbortSignal) => json<YouTubeMetadataState>(await fetch(metadataUrl(projectId), { signal }))
export const initializeYouTubeMetadata = async (projectId: string, creation: CreationState) => json<YouTubeMetadataState>(await fetch(`${metadataUrl(projectId)}/initialize`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ save_id: crypto.randomUUID(), creation_revision: creation.revision, creation_state_digest: creation.state_digest }) }))
export const saveYouTubeMetadata = async (projectId: string, state: YouTubeMetadataState) => saveDocument(metadataUrl(projectId), state, () => loadYouTubeMetadata(projectId))
export const validateYouTubeMetadata = async (projectId: string, state: YouTubeMetadataState, mode: MetadataValidation['mode'], targetKeys: string[] | null = null) => json<MetadataValidation>(await fetch(`${metadataUrl(projectId)}/validate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ state, mode, target_keys: targetKeys }) }))
export const previewYouTubeMetadataReconcile = async (projectId: string, state: YouTubeMetadataState) => json<MetadataReconcilePreview>(await fetch(`${metadataUrl(projectId)}/reconcile-preview`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: state.revision, refresh_fields: [], carry_chapter_labels: [] }) }))
export const reconcileYouTubeMetadata = async (projectId: string, state: YouTubeMetadataState, previewFingerprint: string) => json<YouTubeMetadataState>(await fetch(`${metadataUrl(projectId)}/reconcile`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: state.revision, save_id: crypto.randomUUID(), preview_fingerprint: previewFingerprint, refresh_fields: [], carry_chapter_labels: [] }) }))
export const previewYouTubeMetadataExport = async (projectId: string, state: YouTubeMetadataState, targetKeys: string[]) => json<MetadataExportPreview>(await fetch(`${metadataUrl(projectId)}/export-preview`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: state.revision, target_keys: targetKeys }) }))
export const exportYouTubeMetadata = async (projectId: string, state: YouTubeMetadataState, targetKeys: string[], preview: MetadataExportPreview, replaceExisting: boolean) => json<MetadataExportResult>(await fetch(`${metadataUrl(projectId)}/exports`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: state.revision, target_keys: targetKeys, preview_fingerprint: preview.preview_fingerprint, replace_existing: replaceExisting, expected_existing_sha256: replaceExisting ? preview.existing_sha256 : null }) }))
