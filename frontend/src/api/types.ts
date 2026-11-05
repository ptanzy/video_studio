import type { WRLDSessionImportHandoffV1 } from './generated/import-handoff-v1'
import type { WRLDProjectImportHandoffV2 } from './generated/import-handoff-v2'
import type { WRLDProjectPreferencesV1 } from './generated/project-preferences-v1'
import type { WRLDCreationStateV1, Album as CreationAlbum, Assignment as AlbumAssignment, Single as SingleDraft, Short as ShortDraft } from './generated/creation-state-v1'
import type { WRLDCreationStateV2, VisualTemplate, Album as CreationAlbumV2, Single as SingleDraftV2, Short as ShortDraftV2 } from './generated/creation-state-v2'
import type { WRLDCreationStateV3, VisualTemplateFamily, Album as CreationAlbumV3, Single as SingleDraftV3, Short as ShortDraftV3 } from './generated/creation-state-v3'
import type { WRLDCreationStateV4, Album as CreationAlbumV4, Single as SingleDraftV4, Short as ShortDraftV4 } from './generated/creation-state-v4'
import type { WRLDYouTubeMetadataEditorStateV1 } from './generated/youtube-metadata-editor-v1'
import type { WRLDPortableYouTubeMetadataV1 } from './generated/youtube-metadata-v1'
import type { WRLDPrivateProjectCatalogV2 } from './generated/project-catalog-v2'
import type { Asset as InventoryAssetTransport, WRLDProjectInventoryV1 } from './generated/project-inventory-v1'
import type { WRLDProjectScanStatusV1 } from './generated/project-scan-v1'
import type { WRLDCreationRenderRequestV1 } from './generated/creation-render-request-v1'
import type { WRLDCreationRenderPreflightV1 } from './generated/creation-render-preflight-v1'
import type { WRLDCreationRenderTargetsV1 } from './generated/creation-render-targets-v1'
import type { WRLDCreationRenderJobV1 } from './generated/creation-render-job-v1'
import type { WRLDCreationRenderResultV1 } from './generated/creation-render-result-v1'
import type { WRLDCreationRenderRecoveryRequestV1 } from './generated/creation-render-recovery-request-v1'
import type { WRLDCreationRenderRecoveryPreflightV1 } from './generated/creation-render-recovery-preflight-v1'

export type SourceMode = 'backend' | 'inventory' | 'demonstration'
export type YouTubeMetadataState = WRLDYouTubeMetadataEditorStateV1
export type YouTubeMetadataExport = WRLDPortableYouTubeMetadataV1
export type CreationRenderRequest = WRLDCreationRenderRequestV1
export type CreationRenderPreflight = WRLDCreationRenderPreflightV1
export type CreationRenderTargets = WRLDCreationRenderTargetsV1
export type CreationRenderJob = WRLDCreationRenderJobV1
export type CreationRenderResult = WRLDCreationRenderResultV1
export type CreationRenderRecoveryRequest = WRLDCreationRenderRecoveryRequestV1
export type CreationRenderRecoveryPreflight = WRLDCreationRenderRecoveryPreflightV1

export interface MetadataDiagnostic { code: string; severity: 'error' | 'warning'; target_key: string | null; field: string | null; message: string; details: Record<string, unknown> }
export interface MetadataValidation { contract_version: 'wrld-youtube-metadata-validation/1.0'; mode: 'draft' | 'approval' | 'export'; valid: boolean; target_fingerprints: Array<{ target_key: string; approval_fingerprint: string | null }>; diagnostics: MetadataDiagnostic[] }
export interface MetadataReconcilePreview { contract_version: 'wrld-youtube-metadata-reconcile-preview/1.0'; editor_revision: number; creation_revision: number; preview_fingerprint: string; changes: Array<{ kind: string; target_key: string; field: string | null }>; candidate: YouTubeMetadataState; diagnostics: MetadataDiagnostic[] }
export interface MetadataExportPreview { contract_version: 'wrld-youtube-metadata-export-preview/1.0'; editor_revision: number; eligible: boolean; preview_fingerprint: string; proposed_sha256: string; predicted_export_revision: number; existing_sha256: string | null; document: YouTubeMetadataExport; diagnostics: MetadataDiagnostic[] }
export interface MetadataExportResult { contract_version: 'wrld-youtube-metadata-export-result/1.0'; path: 'output/metadata/youtube_metadata.json'; sha256: string; byte_size: number; revision: number; reused: boolean; document: YouTubeMetadataExport }

export type ProjectSummary = WRLDPrivateProjectCatalogV2['projects'][number] & { availability: 'available' | 'unavailable' | 'removed' }

export interface ProjectRoot { root_id: string; label: string }
export interface ProjectDirectory { name: string; relative_path: string }
export type InventoryAsset = Omit<InventoryAssetTransport, 'media'> & {
  media: { duration_seconds?: number | null; audio_codec?: string | null; width?: number | null; height?: number | null }
}
export type ProjectInventory = Omit<WRLDProjectInventoryV1, 'assets'> & { assets: InventoryAsset[] }
export type InventoryScan = WRLDProjectScanStatusV1
export type ImportHandoff = WRLDSessionImportHandoffV1 | WRLDProjectImportHandoffV2
export type ProjectPreferences = WRLDProjectPreferencesV1
export interface AudioSourceIssue { draft_id: string; asset_id: string; relative_path: string; code: 'SOURCE_MISSING' | 'SOURCE_CHANGED' }
export interface VisualSourceIssue {
  code: 'VISUAL_SOURCE_REQUIRED' | 'VISUAL_SOURCE_MISSING' | 'VISUAL_SOURCE_CHANGED' | 'VISUAL_SOURCE_EXCLUDED' | 'VISUAL_SOURCE_UNSUPPORTED' | 'LEGACY_VISUAL_SETTINGS_UNMAPPED'
  visual_template_id: string | null
  asset_id: string | null
  relative_path: string | null
  expected_sha256: string | null
  observed_sha256: string | null
  affected_targets: Array<{ kind: 'album' | 'single' | 'short'; id: string; status: 'active' | 'archived' }>
}
export type CreationIssue = AudioSourceIssue | VisualSourceIssue
export type CreationStateV1 = WRLDCreationStateV1 & { issues?: CreationIssue[] }
export type CreationStateV2 = WRLDCreationStateV2 & { issues?: CreationIssue[] }
export type CreationStateV3 = WRLDCreationStateV3 & { issues?: CreationIssue[] }
export type CreationStateV4 = WRLDCreationStateV4 & { issues?: CreationIssue[] }
export type VisualCreationState = CreationStateV2 | CreationStateV3
export type EditableVisualCreationState = VisualCreationState | CreationStateV4
export type CreationState = CreationStateV1 | EditableVisualCreationState
export type CreationStateDocument = CreationState
export type CreationAlbumAny = CreationAlbum | CreationAlbumV2 | CreationAlbumV3 | CreationAlbumV4
export type SingleDraftAny = SingleDraft | SingleDraftV2 | SingleDraftV3 | SingleDraftV4
export type ShortDraftAny = ShortDraft | ShortDraftV2 | ShortDraftV3 | ShortDraftV4
export type { AlbumAssignment, CreationAlbum, CreationAlbumV2, CreationAlbumV3, CreationAlbumV4, ShortDraft, ShortDraftV2, ShortDraftV3, ShortDraftV4, SingleDraft, SingleDraftV2, SingleDraftV3, SingleDraftV4, VisualTemplate, VisualTemplateFamily }

export interface AlbumTrack {
  id: string
  number: number
  title: string
  audio: string
  normalized_sample_count: number
  audio_sha256: string
}

export interface AlbumRead {
  contract_version: 'wrld-album-read/1.0'
  project_id: string
  source_fingerprint: string
  manifest_format: string
  album: { id: string; title: string; artist: string; channel: string }
  visual: { background: string; cover?: string; thumbnail?: string }
  tracks: AlbumTrack[]
  render: { profile_id: string; effects: Record<string, unknown> }
}

export type CatalogResponse = Omit<WRLDPrivateProjectCatalogV2, 'revision' | 'projects'> & { revision: number; projects: ProjectSummary[] }

export interface ValidationReport {
  contract_version: string
  project_id: string
  valid: boolean
  source_fingerprint?: string
  errors: Array<{ code: string; message: string }>
  warnings: Array<{ code: string; message: string }>
}

export interface PrimaryShort {
  shortId: string
  start: number
  end: number
  approved: boolean
  reviewRequired: boolean
}

export interface EffectDraft {
  camera: boolean
  zoom: number
  bars: boolean
  barCount: number
  barOpacity: number
  progress: boolean
  tint: string
  tintIntensity: number
  positionX: number
  positionY: number
}

export interface TrackDraft {
  trackId: string
  short: PrimaryShort
  effects: EffectDraft
}

export interface StudioAlbum {
  projectId: string
  sourceMode: SourceMode
  title: string
  artist: string
  channel: string
  artworkLabel: string
  profileId: string
  valid: boolean
  tracks: Array<AlbumTrack & { durationSeconds: number }>
}

export interface ReviewWorkspace {
  projectId: string
  sourceMode: SourceMode
  name: string
  artworkLabel: string
  assets: InventoryAsset[]
  allAssets?: InventoryAsset[]
  excludedAssetIds?: string[]
  tracks: Array<AlbumTrack & { durationSeconds: number }>
}
