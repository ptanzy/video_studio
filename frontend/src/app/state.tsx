/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useMemo, useReducer, useRef, useState, type Dispatch, type ReactNode } from 'react'
import type { EffectDraft, ImportHandoff, ReviewWorkspace, StudioAlbum, TrackDraft } from '../api/types'
import { DEMO_ALBUMS } from './demo'

export type Route = 'import' | 'review' | 'metadata' | 'render'
export type ReviewTab = 'media' | 'creation' | 'editor'
export type EditorTarget = { projectId: string; kind: 'album' | 'single' | 'short'; id: string }

interface Snapshot { drafts: Record<string, TrackDraft> }
interface History { past: Snapshot[]; future: Snapshot[] }
export interface StudioState {
  route: Route
  reviewTab: ReviewTab
  albums: ReviewWorkspace[]
  selectedAlbumId: string
  selectedTrackId: string
  drafts: Record<string, TrackDraft>
  savedDrafts: Record<string, TrackDraft>
  history: History
  backendStatus: 'loading' | 'connected' | 'demo' | 'error'
  backendMessage: string
  leaveTarget: Route | null
  importHandoff: ImportHandoff | null
  editorTarget: EditorTarget | null
}

type Action =
  | { type: 'backend-loading' }
  | { type: 'backend-loaded'; albums: ReviewWorkspace[] }
  | { type: 'backend-error'; message: string }
  | { type: 'project-catalog-refreshed'; projectIds: string[] }
  | { type: 'import-project-selected'; album: ReviewWorkspace }
  | { type: 'import-handoff'; album: ReviewWorkspace; handoff: ImportHandoff }
  | { type: 'enable-demo' }
  | { type: 'select-album'; albumId: string }
  | { type: 'select-track'; trackId: string }
  | { type: 'select-review-tab'; tab: ReviewTab }
  | { type: 'open-editor-target'; target: EditorTarget }
  | { type: 'consume-editor-target' }
  | { type: 'navigate'; route: Route }
  | { type: 'request-navigation'; route: Route }
  | { type: 'cancel-navigation' }
  | { type: 'discard-and-navigate' }
  | { type: 'set-range'; start: number; end: number }
  | { type: 'set-effect'; key: keyof EffectDraft; value: boolean | number | string }
  | { type: 'approve' }
  | { type: 'reset-effects' }
  | { type: 'undo' }
  | { type: 'redo' }
  | { type: 'mark-saved' }
  | { type: 'discard-edits' }

const defaults: EffectDraft = {
  camera: true, zoom: 1.04, bars: true, barCount: 24, barOpacity: 0.65,
  progress: true, tint: '#416E9D', tintIntensity: 18, positionX: 50, positionY: 50,
}

const draftFor = (album: ReviewWorkspace, trackId: string): TrackDraft => {
  const track = album.tracks.find((item) => item.id === trackId) ?? album.tracks[0]
  const length = Math.min(45, track.durationSeconds)
  return {
    trackId: track.id,
    short: { shortId: `demo-primary-${track.id}`, start: 0, end: length, approved: false, reviewRequired: length < 5 },
    effects: { ...defaults },
  }
}

const workspaceFromAlbum = (album: StudioAlbum): ReviewWorkspace => ({
  projectId: album.projectId,
  sourceMode: album.sourceMode,
  name: album.title,
  artworkLabel: album.artworkLabel,
  assets: [],
  tracks: album.tracks,
})
const draftsFor = (albums: ReviewWorkspace[]) => Object.fromEntries(albums.flatMap((album) => album.tracks.map((track) => [track.id, draftFor(album, track.id)])))
const initial: StudioState = {
  route: 'import', reviewTab: 'media', albums: [], selectedAlbumId: '', selectedTrackId: '', drafts: {},
  savedDrafts: {}, history: { past: [], future: [] },
  backendStatus: 'loading', backendMessage: 'Checking the local Phase 1 API…', leaveTarget: null, importHandoff: null, editorTarget: null,
}

const activeDraft = (state: StudioState) => state.drafts[state.selectedTrackId]
const dirty = (state: StudioState) => JSON.stringify(state.drafts) !== JSON.stringify(state.savedDrafts)
const withEdit = (state: StudioState, draft: TrackDraft, invalidateApproval = true): StudioState => ({
  ...state,
  drafts: { ...state.drafts, [state.selectedTrackId]: { ...draft, short: { ...draft.short, approved: invalidateApproval ? false : draft.short.approved } } },
  history: { past: [...state.history.past.slice(-39), { drafts: structuredClone(state.drafts) }], future: [] },
})

const reducer = (state: StudioState, action: Action): StudioState => {
  switch (action.type) {
    case 'backend-loading': return { ...state, backendStatus: 'loading', backendMessage: 'Checking the local Phase 1 API…' }
    case 'backend-loaded': {
      if (!action.albums.length) return { ...state, backendStatus: 'connected', backendMessage: 'Connected. Register or scan a project to begin.' }
      const added = draftsFor(action.albums)
      return { ...state, albums: action.albums, selectedAlbumId: action.albums[0].projectId, selectedTrackId: action.albums[0].tracks[0].id, drafts: added, savedDrafts: structuredClone(added), history: { past: [], future: [] }, backendStatus: 'connected', backendMessage: 'Using registered Phase 1 projects.' }
    }
    case 'backend-error': return { ...state, backendStatus: 'error', backendMessage: action.message }
    case 'project-catalog-refreshed': {
      const available = new Set(action.projectIds)
      const albums = state.albums.filter((item) => available.has(item.projectId))
      const selected = albums.find((item) => item.projectId === state.selectedAlbumId) ?? albums[0]
      const projectChanged = (selected?.projectId ?? '') !== state.selectedAlbumId
      const selectedTrackId = selected?.tracks.some((item) => item.id === state.selectedTrackId)
        ? state.selectedTrackId
        : selected?.tracks[0]?.id ?? ''
      return {
        ...state,
        albums,
        selectedAlbumId: selected?.projectId ?? '',
        selectedTrackId,
        reviewTab: projectChanged ? 'media' : state.reviewTab,
        editorTarget: projectChanged ? null : state.editorTarget,
        importHandoff: state.importHandoff && available.has(state.importHandoff.project_id) ? state.importHandoff : null,
      }
    }
    case 'import-project-selected': {
      const sameProject = action.album.projectId === state.selectedAlbumId
      const drafts = draftsFor([action.album])
      const selectedTrackId = sameProject && action.album.tracks.some((item) => item.id === state.selectedTrackId)
        ? state.selectedTrackId
        : action.album.tracks[0]?.id ?? ''
      return {
        ...state,
        albums: [action.album],
        selectedAlbumId: action.album.projectId,
        selectedTrackId,
        reviewTab: sameProject ? state.reviewTab : 'media',
        drafts,
        savedDrafts: structuredClone(drafts),
        history: { past: [], future: [] },
        backendStatus: 'connected',
        backendMessage: 'Selected Import project is ready in Review.',
        importHandoff: sameProject ? state.importHandoff : null,
        editorTarget: sameProject ? state.editorTarget : null,
      }
    }
    case 'enable-demo': {
      const albums = DEMO_ALBUMS.map(workspaceFromAlbum)
      const drafts = draftsFor(albums)
      return { ...state, reviewTab: 'media', albums, selectedAlbumId: albums[0].projectId, selectedTrackId: albums[0].tracks[0].id, drafts, savedDrafts: structuredClone(drafts), history: { past: [], future: [] }, backendStatus: 'demo', backendMessage: 'Demonstration mode was explicitly enabled; no project files are being used.', editorTarget: null }
    }
    case 'import-handoff': {
      const drafts = draftsFor([action.album])
      const legacy = action.handoff.contract_version === 'wrld-import-handoff/1.0'
      return { ...state, reviewTab: 'media', albums: [action.album], selectedAlbumId: action.album.projectId, selectedTrackId: action.album.tracks[0]?.id ?? '', drafts, savedDrafts: structuredClone(drafts), history: { past: [], future: [] }, route: 'review', backendStatus: 'connected', backendMessage: legacy ? 'Legacy v1 session handoff loaded for compatibility. Its workflow and ordering are session context only; durable Creation state remains authoritative.' : 'Project Import handoff loaded from current inventory and preferences.', importHandoff: action.handoff, editorTarget: null }
    }
    case 'select-album': {
      const album = state.albums.find((item) => item.projectId === action.albumId)
      return album ? { ...state, reviewTab: action.albumId === state.selectedAlbumId ? state.reviewTab : 'media', selectedAlbumId: action.albumId, selectedTrackId: album.tracks[0]?.id ?? '', editorTarget: action.albumId === state.selectedAlbumId ? state.editorTarget : null } : state
    }
    case 'select-track': return { ...state, selectedTrackId: action.trackId }
    case 'select-review-tab': return { ...state, reviewTab: action.tab }
    case 'open-editor-target': return { ...state, reviewTab: 'editor', editorTarget: action.target }
    case 'consume-editor-target': return { ...state, editorTarget: null }
    case 'navigate': return { ...state, route: action.route, leaveTarget: null }
    case 'request-navigation': return dirty(state) && state.route === 'review' ? { ...state, leaveTarget: action.route } : { ...state, route: action.route }
    case 'cancel-navigation': return { ...state, leaveTarget: null }
    case 'discard-and-navigate': return { ...state, drafts: structuredClone(state.savedDrafts), route: state.leaveTarget ?? state.route, leaveTarget: null, history: { past: [], future: [] } }
    case 'set-range': {
      const current = activeDraft(state)
      return withEdit(state, { ...current, short: { ...current.short, start: action.start, end: action.end } })
    }
    case 'set-effect': {
      const current = activeDraft(state)
      return withEdit(state, { ...current, effects: { ...current.effects, [action.key]: action.value } })
    }
    case 'approve': {
      const current = activeDraft(state)
      if (current.short.reviewRequired) return state
      return withEdit(state, { ...current, short: { ...current.short, approved: !current.short.approved } }, false)
    }
    case 'reset-effects': {
      const current = activeDraft(state)
      return withEdit(state, { ...current, effects: { ...defaults } })
    }
    case 'undo': {
      const previous = state.history.past.at(-1)
      if (!previous) return state
      return { ...state, drafts: structuredClone(previous.drafts), history: { past: state.history.past.slice(0, -1), future: [{ drafts: structuredClone(state.drafts) }, ...state.history.future] } }
    }
    case 'redo': {
      const next = state.history.future[0]
      if (!next) return state
      return { ...state, drafts: structuredClone(next.drafts), history: { past: [...state.history.past, { drafts: structuredClone(state.drafts) }], future: state.history.future.slice(1) } }
    }
    case 'mark-saved': return { ...state, savedDrafts: structuredClone(state.drafts), history: { past: [], future: [] } }
    case 'discard-edits': return { ...state, drafts: structuredClone(state.savedDrafts), history: { past: [], future: [] } }
  }
}

export interface GuardHandle { dirty: boolean; save: () => Promise<boolean>; discard: () => void; label: string }
interface StudioContextValue {
  state: StudioState
  dispatch: Dispatch<Action>
  dirty: boolean
  pendingGuard: boolean
  registerGuard: (handle: GuardHandle) => () => void
  requestGuarded: (action: () => void) => void
  saveAndContinue: () => Promise<void>
  discardAndContinue: () => void
  cancelGuard: () => void
  guardLabel: string
}
const Context = createContext<StudioContextValue | null>(null)
export const StudioProvider = ({ children }: { children: ReactNode }) => {
  const [state, dispatch] = useReducer(reducer, initial)
  const [guard, setGuard] = useState<(GuardHandle & { token: number }) | null>(null)
  const [pendingAction, setPendingAction] = useState<(() => void) | null>(null)
  const token = useRef(0)
  const registerGuard = useCallback((handle: GuardHandle) => {
    const current = ++token.current
    setGuard({ ...handle, token: current })
    return () => setGuard((value) => value?.token === current ? null : value)
  }, [])
  const requestGuarded = useCallback((action: () => void) => {
    if (guard?.dirty) setPendingAction(() => action)
    else action()
  }, [guard])
  const saveAndContinue = useCallback(async () => {
    if (!pendingAction || !guard) return
    if (await guard.save()) { const action = pendingAction; setPendingAction(null); action() }
  }, [guard, pendingAction])
  const discardAndContinue = useCallback(() => {
    if (!pendingAction) return
    guard?.discard(); const action = pendingAction; setPendingAction(null); action()
  }, [guard, pendingAction])
  const cancelGuard = useCallback(() => setPendingAction(null), [])
  const value = useMemo(() => ({
    state, dispatch, dirty: dirty(state) || Boolean(guard?.dirty), pendingGuard: Boolean(pendingAction),
    registerGuard, requestGuarded, saveAndContinue, discardAndContinue, cancelGuard,
    guardLabel: guard?.label ?? 'Review',
  }), [state, guard, pendingAction, registerGuard, requestGuarded, saveAndContinue, discardAndContinue, cancelGuard])
  return <Context.Provider value={value}>{children}</Context.Provider>
}
export const useStudio = () => {
  const value = useContext(Context)
  if (!value) throw new Error('Studio context is unavailable')
  return value
}
