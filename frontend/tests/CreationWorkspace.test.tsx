import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { StrictMode, useState } from 'react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CreationWorkspace } from '../src/features/review/CreationWorkspace'
import { EditorWorkspace } from '../src/features/review/EditorWorkspace'
import type { CreationState, CreationStateV2, CreationStateV3, CreationStateV4, ReviewWorkspace, VisualTemplate } from '../src/api/types'
import { StudioProvider, useStudio } from '../src/app/state'

const support = { status: 'supported' as const, reason: 'test' }
const capabilities = { server_stream: support, browser_audition: support, thumbnail: support, inspection: support, preview: support, render: support }
const asset = { asset_id: 'asset-a', relative_path: 'music/song.wav', kind: 'audio' as const, presence: 'present' as const, byte_length: 10, modified_ns: 1, sha256: 'a'.repeat(64), verification_state: 'verified' as const, probe_status: 'ok' as const, media: { duration_seconds: 90, audio_codec: 'pcm_s16le' }, capabilities, diagnostics: [] }
const workspace: ReviewWorkspace = { projectId: 'project-1', sourceMode: 'inventory', name: 'Project', artworkLabel: '', assets: [asset], tracks: [{ id: 'asset-a', number: 1, title: 'song.wav', audio: 'music/song.wav', normalized_sample_count: 90 * 48_000, audio_sha256: 'a'.repeat(64), durationSeconds: 90 }] }
const initial: CreationState = { contract_version: 'wrld-creation-state/1.0', project_id: 'project-1', revision: 1, save_id: 'initial', preferred_short_duration_seconds: 45, albums: [], singles: [], shorts: [], state_digest: '0'.repeat(64), issues: [] }
const GuardProbe = () => {
  const { state, pendingGuard, requestGuarded, saveAndContinue, discardAndContinue, cancelGuard } = useStudio()
  const [navigated, setNavigated] = useState(false)
  return <div><span data-testid="review-tab">{state.reviewTab}</span><span data-testid="editor-target">{state.editorTarget?.id ?? ''}</span><button onClick={() => requestGuarded(() => setNavigated(true))}>Navigate elsewhere</button>{pendingGuard && <div role="dialog" aria-label="Unsaved Creation changes"><button onClick={cancelGuard}>Cancel navigation</button><button onClick={discardAndContinue}>Discard and continue</button><button onClick={() => void saveAndContinue()}>Save and continue</button></div>}{navigated && <span>Navigation completed</span>}</div>
}
const show = (currentWorkspace = workspace) => render(<StudioProvider><CreationWorkspace workspace={currentWorkspace}/><GuardProbe/></StudioProvider>)

const backend = (startingState: CreationState = initial, manifestAudio?: string[]) => {
  let stored = structuredClone(startingState)
  const request = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/album')) {
      if (!manifestAudio) return { ok: false, status: 404, json: async () => ({ error: { code: 'ALBUM_UNAVAILABLE', message: 'No recognized manifest.' } }) } as Response
      return { ok: true, status: 200, json: async () => ({ tracks: manifestAudio.map((audio, index) => ({ id: `track-${index}`, number: index + 1, title: audio, audio, normalized_sample_count: 48_000, audio_sha256: 'f'.repeat(64) })) }) } as Response
    }
    if (init?.method === 'PUT') {
      const body = JSON.parse(String(init.body)) as { state: CreationState }
      stored = { ...body.state, revision: stored.revision + 1, issues: [] }
    }
    return { ok: true, status: 200, json: async () => structuredClone(stored) } as Response
  })
  vi.stubGlobal('fetch', request)
  return { request, get: () => stored }
}

afterEach(() => vi.restoreAllMocks())

describe('Creation workspace', () => {
  it('populates new albums in natural order and preserves an explicit empty alternative', async () => {
    const track10 = { ...asset, asset_id: 'asset-10', relative_path: 'music/track10.wav', sha256: '1'.repeat(64) }
    const bonus = { ...asset, asset_id: 'asset-bonus', relative_path: 'music/bonus.wav', sha256: '2'.repeat(64) }
    const track2 = { ...asset, asset_id: 'asset-2', relative_path: 'music/track2.wav', sha256: '3'.repeat(64) }
    const orderedWorkspace: ReviewWorkspace = { ...workspace, assets: [track10, bonus, track2], tracks: [] }
    const service = backend(); const user = userEvent.setup(); show(orderedWorkspace)
    await screen.findByText('Albums, Singles & Shorts')
    await user.click(screen.getByRole('button', { name: /^Add Album$/i }))
    const albums = screen.getByText('Albums').closest('section')!
    await waitFor(() => expect(within(albums).getAllByRole('button', { name: /Play .*\.wav/i })).toHaveLength(3))
    await user.click(screen.getByRole('button', { name: /Save Creation/i }))
    await waitFor(() => expect(service.get().albums).toHaveLength(1))
    expect(service.get().albums[0].assignments.map((item) => item.asset_id)).toEqual(['asset-bonus', 'asset-2', 'asset-10'])
    await user.click(screen.getByRole('button', { name: /Create Empty Album/i }))
    await waitFor(() => expect(screen.getAllByLabelText('Album label')).toHaveLength(2))
    await user.click(screen.getByRole('button', { name: /Save Creation/i }))
    await waitFor(() => expect(service.get().albums).toHaveLength(2))
    expect(service.get().albums[1].assignments).toEqual([])
  })

  it('prefers manifest order and appends unmatched included audio in natural order', async () => {
    const track10 = { ...asset, asset_id: 'asset-10', relative_path: 'music/track10.wav', sha256: '1'.repeat(64) }
    const bonus = { ...asset, asset_id: 'asset-bonus', relative_path: 'music/bonus.wav', sha256: '2'.repeat(64) }
    const track2 = { ...asset, asset_id: 'asset-2', relative_path: 'music/track2.wav', sha256: '3'.repeat(64) }
    const orderedWorkspace: ReviewWorkspace = { ...workspace, assets: [track2, bonus, track10], tracks: [] }
    const service = backend(initial, ['music/track10.wav', 'music/track2.wav']); const user = userEvent.setup(); show(orderedWorkspace)
    await screen.findByText('Albums, Singles & Shorts')
    await user.click(screen.getByRole('button', { name: /^Add Album$/i }))
    await screen.findByDisplayValue('Album 1')
    await user.click(screen.getByRole('button', { name: /Save Creation/i }))
    await waitFor(() => expect(service.get().albums).toHaveLength(1))
    expect(service.get().albums[0].assignments.map((item) => item.asset_id)).toEqual(['asset-10', 'asset-2', 'asset-bonus'])
  })

  it('preserves intentional duplicate album assignments with stable independent identities', async () => {
    const service = backend(); const user = userEvent.setup()
    show()
    await screen.findByText('Albums, Singles & Shorts')
    await user.click(screen.getByRole('button', { name: /Add Album/i }))
    await user.click(screen.getByRole('button', { name: /Add track/i }))
    expect(screen.getAllByText(/Repeated recording/)).toHaveLength(2)
    await user.click(screen.getByRole('button', { name: /Save Creation/i }))
    await waitFor(() => expect(service.get().albums[0].assignments).toHaveLength(2))
    const ids = service.get().albums[0].assignments.map((item) => item.assignment_id)
    expect(new Set(ids).size).toBe(2)
    expect(service.get().albums[0].assignments.map((item) => item.asset_id)).toEqual(['asset-a', 'asset-a'])
    const occurrences = screen.getAllByRole('button', { name: /next occurrence/i })
    await user.click(occurrences[0])
    expect(occurrences[1].closest('li')).toHaveClass('highlighted')
  })

  it('guards unsaved album ordering, assignments, and Short edits and can save before navigation', async () => {
    const service = backend(); const user = userEvent.setup(); show()
    await screen.findByText('Albums, Singles & Shorts')
    await user.click(screen.getByRole('button', { name: /Create Empty Album/i }))
    await user.click(screen.getByRole('button', { name: /Add track/i }))
    await user.click(screen.getByRole('button', { name: /Add track/i }))
    const moveEarlier = screen.getAllByRole('button', { name: /Move track up/i })
    await user.click(moveEarlier[1])
    const shorts = screen.getByText('Shorts').closest('section')!
    await user.click(within(shorts).getByRole('button', { name: 'Increase Shorts for song.wav' }))
    await user.click(within(shorts).getByText('Edit drafts'))
    fireEvent.change(within(shorts).getByLabelText(/Duration for short-/i), { target: { value: '35' } })
    await user.click(screen.getByRole('button', { name: /Navigate elsewhere/i }))
    expect(screen.getByRole('dialog', { name: /Unsaved Creation changes/i })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Cancel navigation/i }))
    expect(screen.queryByText('Navigation completed')).not.toBeInTheDocument()
    expect(within(shorts).getByLabelText(/Duration for short-/i)).toHaveValue(35)
    await user.click(screen.getByRole('button', { name: /Navigate elsewhere/i }))
    await user.click(screen.getByRole('button', { name: /Save and continue/i }))
    await screen.findByText('Navigation completed')
    expect(service.get().albums[0].assignments).toHaveLength(2)
    expect(service.get().shorts[0].sample_count).toBe(35 * 48_000)
  })

  it('creates independent Single and Short drafts, archives customized work, and exposes no fake analyzer result', async () => {
    backend(); const user = userEvent.setup(); const confirmation = vi.spyOn(window, 'confirm').mockReturnValue(true)
    show()
    await screen.findByText('Albums, Singles & Shorts')
    const singles = screen.getByText('Singles').closest('section')!
    const shorts = screen.getByText('Shorts').closest('section')!
    await user.click(within(singles).getByRole('button', { name: 'Increase Singles for song.wav' }))
    await user.click(within(singles).getByRole('button', { name: /Increase Singles/i }))
    expect(within(singles).getByText('2 active · 0 archived')).toBeInTheDocument()
    await user.click(within(singles).getByRole('button', { name: 'Decrease Singles for song.wav' }))
    await user.click(within(singles).getByRole('button', { name: 'Decrease Singles for song.wav' }))
    expect(within(singles).getByText('0 active · 2 archived')).toBeInTheDocument()
    await user.click(within(singles).getByRole('button', { name: 'Increase Singles for song.wav' }))
    expect(within(singles).getByText('1 active · 1 archived')).toBeInTheDocument()
    await user.click(within(shorts).getByRole('button', { name: 'Increase Shorts for song.wav' }))
    expect(within(shorts).getByRole('button', { name: /Suggest Shorts/i })).toBeDisabled()
    expect(within(shorts).getByText(/Analyzer recommendations unavailable/i)).toBeInTheDocument()
    await user.click(within(shorts).getByText('Edit drafts'))
    const duration = within(shorts).getByLabelText(/Duration for short-/i)
    expect(within(shorts).getByRole('button', { name: /Explain This Selection/i })).toBeDisabled()
    fireEvent.change(duration, { target: { value: '35' } })
    await user.click(within(shorts).getByRole('button', { name: /Decrease Shorts/i }))
    expect(confirmation).toHaveBeenCalled()
    expect(within(shorts).getByText('0 active · 1 archived')).toBeInTheDocument()
    await user.click(within(shorts).getByText('Edit drafts'))
    await user.click(within(shorts).getByRole('button', { name: /Restore short-/i }))
    expect(within(shorts).getByText('1 active · 0 archived')).toBeInTheDocument()
  })

  it('adds only genuinely missing Singles and preserves archived work idempotently', async () => {
    const secondAsset = { ...asset, asset_id: 'asset-b', relative_path: 'music/second.wav', sha256: 'b'.repeat(64) }
    const missingAsset = { ...asset, asset_id: 'asset-missing', relative_path: 'music/missing.wav', presence: 'missing' as const, sha256: 'c'.repeat(64) }
    const multiWorkspace: ReviewWorkspace = { ...workspace, assets: [asset, secondAsset, missingAsset] }
    const archived: CreationState = { ...initial, singles: [{ single_id: 'single-archived', asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), status: 'archived', customized: true, approved: true, settings: { label: 'Keep me' } }] }
    const service = backend(archived); const user = userEvent.setup(); show(multiWorkspace)
    await screen.findByText('Albums, Singles & Shorts')
    await user.click(screen.getByRole('button', { name: 'Add Missing Singles' }))
    expect(screen.getByText('1 Single added · 1 recording already represented.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add Missing Singles' })).toBeDisabled()
    const singles = screen.getByText('Singles').closest('section')!
    expect(within(singles).getByText('0 active · 1 archived')).toBeInTheDocument()
    expect(within(singles).getByText('1 active · 0 archived')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save Creation' }))
    await waitFor(() => expect(service.get().singles).toHaveLength(2))
    expect(service.get().singles.find((item) => item.single_id === 'single-archived')).toMatchObject({ status: 'archived', customized: true, approved: true, settings: { label: 'Keep me' } })
    expect(service.get().singles.filter((item) => item.asset_id === 'asset-b')).toHaveLength(1)
  })

  it('applies shared-selection bulk changes atomically and confirms protected removals once', async () => {
    const secondAsset = { ...asset, asset_id: 'asset-b', relative_path: 'music/second.wav', sha256: 'b'.repeat(64) }
    const multiWorkspace: ReviewWorkspace = { ...workspace, assets: [asset, secondAsset] }
    const populated: CreationState = { ...initial,
      singles: [
        { single_id: 'single-a', asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), status: 'active', customized: false, approved: false, settings: {} },
        { single_id: 'single-b', asset_id: 'asset-b', expected_sha256: 'b'.repeat(64), status: 'archived', customized: true, approved: true, settings: {} },
      ],
      shorts: [
        { short_id: 'short-a', asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), status: 'active', start_sample: 0, sample_count: 45 * 48_000, origin: 'manual', review_required: false, customized: false, approved: false, settings: {} },
        { short_id: 'short-b', asset_id: 'asset-b', expected_sha256: 'b'.repeat(64), status: 'active', start_sample: 0, sample_count: 45 * 48_000, origin: 'manual', review_required: false, customized: true, approved: true, settings: {} },
      ],
    }
    backend(populated); const user = userEvent.setup(); const confirmation = vi.spyOn(window, 'confirm').mockReturnValue(true); show(multiWorkspace)
    await screen.findByText('Albums, Singles & Shorts')
    const singles = screen.getByText('Singles').closest('section')!
    const shorts = screen.getByText('Shorts').closest('section')!
    expect(within(singles).getByText('2 of 2 selected')).toBeInTheDocument()
    expect(within(shorts).getByText('2 of 2 selected')).toBeInTheDocument()
    await user.click(within(singles).getByRole('button', { name: 'Clear' }))
    expect(within(singles).getByText('0 of 2 selected')).toBeInTheDocument()
    expect(within(shorts).getByText('2 of 2 selected')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Increase all selected Singles' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Increase all selected Shorts' })).toBeEnabled()
    await user.click(within(singles).getByRole('button', { name: 'Select All' }))

    await user.click(screen.getByRole('button', { name: 'Increase all selected Singles' }))
    expect(screen.getByText('Singles: 1 created · 1 restored.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Undo' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: 'Undo' }))
    expect(screen.getByRole('button', { name: 'Undo' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Save Creation' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Decrease all selected Shorts' }))
    expect(confirmation).toHaveBeenCalledTimes(1)
    expect(screen.getByText('Shorts: 2 archived · 0 skipped.')).toBeInTheDocument()
    expect(within(shorts).getAllByText('0 active · 1 archived')).toHaveLength(2)
    await user.click(screen.getByRole('button', { name: 'Undo' }))
    expect(within(shorts).getAllByText('1 active · 0 archived')).toHaveLength(2)
    expect(screen.getByRole('button', { name: 'Undo' })).toBeDisabled()
  })

  it('uses independent section selections without dirtying Creation or rendering duplicate selection controls', async () => {
    const secondAsset = { ...asset, asset_id: 'asset-b', relative_path: 'music/second.wav', sha256: 'b'.repeat(64) }
    backend(); const user = userEvent.setup(); const view = show({ ...workspace, assets: [asset, secondAsset] })
    await screen.findByText('Albums, Singles & Shorts')
    const singles = screen.getByText('Singles').closest('section')!
    const shorts = screen.getByText('Shorts').closest('section')!
    expect(screen.queryByText(/Bulk recording selection/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Bulk selected/i)).not.toBeInTheDocument()
    expect(within(singles).getAllByRole('checkbox')).toHaveLength(2)
    expect(within(shorts).getAllByRole('checkbox')).toHaveLength(2)
    await user.click(within(singles).getByRole('checkbox', { name: 'Select song.wav for Singles bulk changes' }))
    expect(within(singles).getByText('1 of 2 selected')).toBeInTheDocument()
    expect(within(shorts).getByText('2 of 2 selected')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save Creation' })).toBeDisabled()
    view.rerender(<StudioProvider><CreationWorkspace workspace={{ ...workspace, projectId: 'project-2', assets: [secondAsset], tracks: [] }}/><GuardProbe/></StudioProvider>)
    await waitFor(() => expect(screen.getAllByText('1 of 1 selected')).toHaveLength(2))
  })

  it('deletes empty and populated Albums atomically while preserving drafts and shared templates', async () => {
    const populated: CreationStateV2 = {
      contract_version: 'wrld-creation-state/2.0', project_id: 'project-1', revision: 2, save_id: 'v2', preferred_short_duration_seconds: 45,
      visual_templates: [{ visual_template_id: 'visual-shared', label: 'Shared', canvas: { aspect_ratio: '16:9' }, background_image: null, geometry: { fit_mode: 'contain', focal_x: 0.5, focal_y: 0.5 }, camera: { mode: 'static', max_zoom: 1.04 }, visualizer: { enabled: false, bar_count: 24, opacity: 0.65 }, progress: { enabled: false }, color_treatment: { mode: 'none' } }],
      albums: [
        { album_plan_id: 'album-filled', label: 'Filled Album', status: 'active', visual_template_id: 'visual-shared', assignments: [{ assignment_id: 'assignment-a', asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), duplicate_acknowledged: false }] },
        { album_plan_id: 'album-empty', label: 'Empty Album', status: 'active', visual_template_id: null, assignments: [] },
      ],
      singles: [{ single_id: 'single-a', asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), status: 'active', customized: false, approved: true, settings: {}, visual_template_id: 'visual-shared' }],
      shorts: [], state_digest: '1'.repeat(64), issues: [],
    }
    const service = backend(populated); const user = userEvent.setup(); const confirmation = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true); show()
    await screen.findByText('Albums, Singles & Shorts')
    await user.click(screen.getByRole('button', { name: 'Delete Filled Album' }))
    expect(screen.getByDisplayValue('Filled Album')).toBeInTheDocument()
    expect(confirmation).toHaveBeenCalledWith(expect.stringContaining('1 track assignment'))
    await user.click(screen.getByRole('button', { name: 'Delete Empty Album' }))
    expect(screen.queryByDisplayValue('Empty Album')).not.toBeInTheDocument()
    expect(confirmation).toHaveBeenCalledTimes(1)
    await user.click(screen.getByRole('button', { name: 'Delete Filled Album' }))
    expect(screen.queryByLabelText('Album label')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Undo' }))
    expect(screen.getByDisplayValue('Filled Album')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Redo' }))
    expect(screen.queryByLabelText('Album label')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save Creation' }))
    await waitFor(() => expect(service.get().albums).toEqual([]))
    expect(service.get().singles).toEqual(populated.singles)
    expect((service.get() as CreationStateV2).visual_templates).toEqual(populated.visual_templates)
    cleanup(); show()
    await screen.findByText('0 album plans')
    expect(screen.queryByLabelText('Album label')).not.toBeInTheDocument()
  })

  it('preserves historical excluded Album assignments with filenames and limits new assignment choices to included audio', async () => {
    const excludedAsset = { ...asset, asset_id: 'asset-b', relative_path: 'music/excluded.wav', sha256: 'b'.repeat(64) }
    const historical: CreationState = { ...initial, albums: [{ album_plan_id: 'album-old', label: 'Historical', status: 'active', assignments: [{ assignment_id: 'assignment-b', asset_id: 'asset-b', expected_sha256: 'b'.repeat(64), duplicate_acknowledged: false }] }] }
    const excludedWorkspace: ReviewWorkspace = { ...workspace, allAssets: [asset, excludedAsset], excludedAssetIds: ['asset-b'] }
    const service = backend(historical); const user = userEvent.setup(); const view = show(excludedWorkspace)
    await screen.findByText('Albums, Singles & Shorts')
    expect(screen.getByText('excluded.wav')).toBeInTheDocument()
    expect(screen.getByText('Excluded from Import')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Restore in Import' })).toBeInTheDocument()
    const select = screen.getByRole('combobox', { name: 'Recording for Historical' })
    expect(within(select).getAllByRole('option').map((item) => item.textContent)).toEqual(['song.wav'])
    await user.click(screen.getByRole('button', { name: /^Add Album$/i }))
    expect(screen.getAllByLabelText('Album label')).toHaveLength(2)
    expect(screen.getAllByText('excluded.wav')).toHaveLength(1)
    expect(service.get().albums).toHaveLength(1)

    const includedWorkspace: ReviewWorkspace = { ...excludedWorkspace, assets: [asset, excludedAsset], excludedAssetIds: [] }
    view.rerender(<StudioProvider><CreationWorkspace workspace={includedWorkspace}/><GuardProbe/></StudioProvider>)
    await waitFor(() => expect(screen.queryByText('Excluded from Import')).not.toBeInTheDocument())
    const historicalAssignments = screen.getByDisplayValue('Historical').closest('article')!.querySelector('.assignment-list') as HTMLElement
    expect(within(historicalAssignments).getAllByText('excluded.wav')).toHaveLength(1)
  })

  it('keeps bulk draft operations compatible with Creation v2 template references', async () => {
    const migrated: CreationState = {
      contract_version: 'wrld-creation-state/2.0', project_id: 'project-1', revision: 2, save_id: 'upgrade', preferred_short_duration_seconds: 45,
      visual_templates: [], albums: [], singles: [], shorts: [], state_digest: '1'.repeat(64), issues: [],
    }
    const service = backend(migrated); const user = userEvent.setup(); show()
    await screen.findByText('Albums, Singles & Shorts')
    await user.click(screen.getByRole('button', { name: 'Increase all selected Singles' }))
    await user.click(screen.getByRole('button', { name: 'Increase all selected Shorts' }))
    await user.click(screen.getByRole('button', { name: 'Save Creation' }))
    await waitFor(() => expect(service.get().revision).toBe(3))
    expect(service.get().contract_version).toBe('wrld-creation-state/2.0')
    expect(service.get().singles[0]).toMatchObject({ asset_id: 'asset-a', visual_template_id: null })
    expect(service.get().shorts[0]).toMatchObject({ asset_id: 'asset-a', visual_template_id: null })
  })

  it('preserves the complete v3 family registry while existing Creation operations add v3 targets', async () => {
    const template = (visualTemplateId: string, aspectRatio: '16:9' | '9:16'): VisualTemplate => ({
      visual_template_id: visualTemplateId, label: visualTemplateId, canvas: { aspect_ratio: aspectRatio }, background_image: null,
      geometry: { fit_mode: 'contain', focal_x: 0.5, focal_y: 0.5 }, camera: { mode: 'static', max_zoom: 1.04 },
      visualizer: { enabled: false, bar_count: 24, opacity: 0.65 }, progress: { enabled: false }, color_treatment: { mode: 'none' },
    })
    const starting: CreationStateV3 = {
      contract_version: 'wrld-creation-state/3.0', project_id: 'project-1', revision: 3, save_id: 'v3', preferred_short_duration_seconds: 45,
      visual_templates: [template('family-album', '16:9'), template('family-single', '16:9'), template('family-short', '9:16')],
      visual_template_families: [{ visual_template_family_id: 'family-stable', name: 'Stable family', members: { album_visual_template_id: 'family-album', single_visual_template_id: 'family-single', short_visual_template_id: 'family-short' } }],
      albums: [], singles: [], shorts: [], state_digest: '3'.repeat(64), issues: [],
    }
    const originalTemplates = structuredClone(starting.visual_templates)
    const originalFamilies = structuredClone(starting.visual_template_families)
    const service = backend(starting); const user = userEvent.setup(); show()
    await screen.findByText('Albums, Singles & Shorts')
    await user.click(screen.getByRole('button', { name: 'Add Missing Singles' }))
    await user.click(screen.getByRole('button', { name: 'Increase all selected Shorts' }))
    await user.click(screen.getByRole('button', { name: /^Add Album$/i }))
    await user.click(screen.getByRole('button', { name: 'Save Creation' }))
    await waitFor(() => expect(service.get().revision).toBe(4))
    const saved = service.get()
    if (saved.contract_version !== 'wrld-creation-state/3.0') throw new Error('wrong stored contract')
    expect(saved.visual_template_families).toEqual(originalFamilies)
    expect(saved.visual_templates).toEqual(originalTemplates)
    expect(saved.albums[0].visual_template_id).toBeNull()
    expect(saved.singles[0].visual_template_id).toBeNull()
    expect(saved.shorts[0].visual_template_id).toBeNull()
  })

  it('clamps near-end ranges and permits the whole source when audio is shorter than five seconds', async () => {
    const longState: CreationState = { ...initial, shorts: [{ short_id: 'short-long', asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), status: 'active', start_sample: 0, sample_count: 45 * 48_000, origin: 'manual', review_required: false, customized: true, approved: false, settings: {} }] }
    backend(longState); const user = userEvent.setup(); show()
    await screen.findByText('Albums, Singles & Shorts')
    const longSection = screen.getByText('Shorts').closest('section')!
    await user.click(within(longSection).getByText('Edit drafts'))
    fireEvent.change(within(longSection).getByLabelText('Start for short-long'), { target: { value: '89' } })
    expect(within(longSection).getByLabelText('Start for short-long')).toHaveValue(85)
    expect(within(longSection).getByLabelText('Duration for short-long')).toHaveValue(5)
  })

  it('uses the complete source as the valid minimum for sub-five-second audio', async () => {
    const shortAsset = { ...asset, asset_id: 'asset-short', relative_path: 'music/short.wav', sha256: 'c'.repeat(64), media: { ...asset.media, duration_seconds: 4 } }
    const shortWorkspace: ReviewWorkspace = { ...workspace, assets: [shortAsset], tracks: [{ ...workspace.tracks[0], id: 'asset-short', title: 'short.wav', audio: 'music/short.wav', audio_sha256: 'c'.repeat(64), normalized_sample_count: 4 * 48_000, durationSeconds: 4 }] }
    const shortState: CreationState = { ...initial, shorts: [{ short_id: 'short-whole', asset_id: 'asset-short', expected_sha256: 'c'.repeat(64), status: 'active', start_sample: 0, sample_count: 4 * 48_000, origin: 'manual_required', review_required: true, customized: false, approved: false, settings: {} }] }
    backend(shortState); const user = userEvent.setup(); show(shortWorkspace)
    await screen.findByText('Albums, Singles & Shorts')
    const section = screen.getByText('Shorts').closest('section')!
    await user.click(within(section).getByText('Edit drafts'))
    const duration = within(section).getByLabelText('Duration for short-whole')
    expect(duration).toHaveAttribute('min', '4')
    expect(duration).toHaveAttribute('max', '4')
    fireEvent.change(duration, { target: { value: '1' } })
    expect(duration).toHaveValue(4)
  })

  it('identifies changed and missing sources and explicitly accepts a changed fingerprint', async () => {
    const affected: CreationState = { ...initial, singles: [{ single_id: 'single-old', asset_id: 'asset-a', expected_sha256: 'b'.repeat(64), status: 'active', customized: true, approved: true, settings: {} }], issues: [
      { draft_id: 'single-old', asset_id: 'asset-a', relative_path: 'music/song.wav', code: 'SOURCE_CHANGED' },
      { draft_id: 'short-missing', asset_id: 'asset-missing', relative_path: 'music/missing.wav', code: 'SOURCE_MISSING' },
    ] }
    const service = backend(affected); const user = userEvent.setup(); vi.spyOn(window, 'confirm').mockReturnValue(true); show()
    const warnings = (await screen.findByText('Creation warnings (2)')).closest('details')!
    expect(warnings).not.toHaveAttribute('open')
    await user.click(within(warnings).getByText('Creation warnings (2)'))
    expect(within(warnings).getByText('missing.wav')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Relink in Import/i })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Accept changed source/i }))
    expect(screen.getByText('Creation warnings (1)')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Save Creation/i }))
    await waitFor(() => expect(service.get().singles[0].expected_sha256).toBe('a'.repeat(64)))
    expect(service.get().singles[0].approved).toBe(false)
  })

  it('groups visual warnings behind a collapsed keyboard-accessible disclosure with human labels and Editor recovery', async () => {
    const affected: CreationState = {
      contract_version: 'wrld-creation-state/2.0', project_id: 'project-1', revision: 2, save_id: 'v2', preferred_short_duration_seconds: 45,
      visual_templates: [{ visual_template_id: 'visual-a', label: 'Portrait', canvas: { aspect_ratio: '9:16' }, background_image: null, geometry: { fit_mode: 'contain', focal_x: 0.5, focal_y: 0.5 }, camera: { mode: 'static', max_zoom: 1.04 }, visualizer: { enabled: false, bar_count: 24, opacity: 0.65 }, progress: { enabled: false }, color_treatment: { mode: 'none' } }],
      albums: [], singles: [], shorts: [{ short_id: 'short-visual', asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), status: 'active', start_sample: 0, sample_count: 45 * 48_000, origin: 'manual', review_required: false, customized: true, approved: false, settings: {}, visual_template_id: 'visual-a' }], state_digest: '1'.repeat(64),
      issues: [{ code: 'VISUAL_SOURCE_REQUIRED', visual_template_id: 'visual-a', asset_id: null, relative_path: null, expected_sha256: null, observed_sha256: null, affected_targets: [{ kind: 'short', id: 'short-visual', status: 'active' }] }],
    }
    backend(affected); const user = userEvent.setup()
    const WarningNavigation = () => { const { state } = useStudio(); return state.reviewTab === 'editor' ? <EditorWorkspace workspace={workspace}/> : <><CreationWorkspace workspace={workspace}/><GuardProbe/></> }
    render(<StudioProvider><WarningNavigation/></StudioProvider>)
    const disclosure = (await screen.findByText('Creation warnings (1)')).closest('details')!
    expect(disclosure).not.toHaveAttribute('open')
    disclosure.querySelector('summary')!.focus()
    await user.keyboard('{Enter}')
    expect(disclosure).toHaveAttribute('open')
    expect(within(disclosure).getByText('1 Short needs a background')).toBeInTheDocument()
    expect(within(disclosure).getByText('song.wav')).toBeInTheDocument()
    expect(within(disclosure).getByText(/short-visual · visual-a/)).toBeInTheDocument()
    await user.click(within(disclosure).getByRole('button', { name: 'Review in Editor' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Shorts' })).toHaveAttribute('aria-current', 'page'))
    expect(screen.getByText('short · short-visual')).toBeInTheDocument()
  })

  it('shares one audio preview, stops excerpts at their boundary, and never dirties Creation', async () => {
    const previewState: CreationState = { ...initial,
      singles: [{ single_id: 'single-preview', asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), status: 'active', customized: false, approved: false, settings: {} }],
      shorts: [{ short_id: 'short-preview', asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), status: 'active', start_sample: 10 * 48_000, sample_count: 10 * 48_000, origin: 'manual', review_required: false, customized: true, approved: false, settings: {} }],
    }
    backend(previewState); const user = userEvent.setup(); show()
    await screen.findByText('Albums, Singles & Shorts')
    const singles = screen.getByText('Singles').closest('section')!
    const shorts = screen.getByText('Shorts').closest('section')!
    const play = vi.mocked(HTMLMediaElement.prototype.play)
    const pause = vi.mocked(HTMLMediaElement.prototype.pause)
    play.mockClear(); pause.mockClear()

    await user.click(within(singles).getByRole('button', { name: 'Play song.wav' }))
    await within(singles).findByRole('button', { name: 'Pause song.wav' })
    await user.click(within(shorts).getByRole('button', { name: 'Play song.wav' }))
    await within(shorts).findByRole('button', { name: 'Pause song.wav' })
    expect(within(singles).getByRole('button', { name: 'Play song.wav' })).toBeInTheDocument()
    expect(pause).toHaveBeenCalled()

    await user.click(within(shorts).getByText('Edit drafts'))
    await user.click(within(shorts).getByRole('button', { name: 'Preview excerpt short-preview' }))
    await within(shorts).findByRole('button', { name: 'Pause excerpt short-preview' })
    const media = play.mock.contexts.at(-1) as HTMLMediaElement
    media.currentTime = 20
    media.dispatchEvent(new Event('timeupdate'))
    await within(shorts).findByRole('button', { name: 'Preview excerpt short-preview' })
    expect(screen.getByRole('button', { name: /Save Creation/i })).toBeDisabled()
  })

  it('creates schema-valid composition-owned v4 Albums, Singles, and Shorts without assigning templates', async () => {
    const starting: CreationStateV4 = { contract_version: 'wrld-creation-state/4.0', project_id: 'project-1', revision: 4, save_id: 'v4', preferred_short_duration_seconds: 45, visual_templates: [], visual_template_families: [], albums: [], singles: [], shorts: [], state_digest: '4'.repeat(64), issues: [] }
    const service = backend(starting); const user = userEvent.setup(); show()
    await screen.findByText('Albums, Singles & Shorts')
    await user.click(screen.getByRole('button', { name: /^Add Album$/i }))
    const singles = screen.getByText('Singles').closest('section')!
    const shorts = screen.getByText('Shorts').closest('section')!
    await user.click(within(singles).getByRole('button', { name: 'Increase Singles for song.wav' }))
    await user.click(within(shorts).getByRole('button', { name: 'Increase Shorts for song.wav' }))
    await user.click(screen.getByRole('button', { name: /Save Creation/i }))
    await waitFor(() => expect(service.get().revision).toBe(5))
    const stored = service.get() as CreationStateV4
    expect(stored.albums[0]).toMatchObject({ source_visual_template_id: null, visual_configuration: { canvas: { aspect_ratio: '16:9' }, background_image: null } })
    expect(stored.singles[0]).toMatchObject({ source_visual_template_id: null, visual_configuration: { canvas: { aspect_ratio: '16:9' }, background_image: null } })
    expect(stored.shorts[0]).toMatchObject({ source_visual_template_id: null, visual_configuration: { canvas: { aspect_ratio: '9:16' }, background_image: null } })
    expect(stored.albums[0]).not.toHaveProperty('visual_template_id')
    expect(stored.singles[0]).not.toHaveProperty('visual_template_id')
    expect(stored.shorts[0]).not.toHaveProperty('visual_template_id')
  })

  it('hides expected Strict Mode cancellation and retries a genuine load failure', async () => {
    let requests = 0
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (!String(input).endsWith('/creation-state')) return Promise.resolve({ ok: false, status: 404, json: async () => ({ error: { message: 'Unavailable' } }) } as Response)
      requests += 1
      if (requests === 1) return new Promise<Response>((_resolve, reject) => init?.signal?.addEventListener('abort', () => reject(new DOMException('signal is aborted without reason', 'AbortError'))))
      return Promise.resolve({ ok: true, status: 200, json: async () => structuredClone(initial) } as Response)
    }))
    render(<StrictMode><StudioProvider><CreationWorkspace workspace={workspace}/></StudioProvider></StrictMode>)
    await screen.findByText('Albums, Singles & Shorts')
    expect(screen.queryByText(/signal is aborted/i)).not.toBeInTheDocument()

    cleanup()
    let retryRequests = 0
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (!String(input).endsWith('/creation-state')) return { ok: false, status: 404, json: async () => ({ error: { message: 'Unavailable' } }) } as Response
      retryRequests += 1
      if (retryRequests === 1) return { ok: false, status: 500, json: async () => ({ error: { message: 'Temporary load failure.' } }) } as Response
      return { ok: true, status: 200, json: async () => structuredClone(initial) } as Response
    }))
    show()
    expect(await screen.findByText('Creation workspace could not be loaded.')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Temporary load failure.')
    await userEvent.setup().click(screen.getByRole('button', { name: 'Retry' }))
    await screen.findByText('Albums, Singles & Shorts')
    expect(screen.queryByText('Temporary load failure.')).not.toBeInTheDocument()
  })
})
