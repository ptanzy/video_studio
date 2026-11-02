import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CreationState, CreationStateV2, CreationStateV3, ReviewWorkspace, VisualTemplate } from '../src/api/types'
import { StudioProvider } from '../src/app/state'
import { EditorWorkspace } from '../src/features/review/EditorWorkspace'

const support = { status: 'supported' as const, reason: 'test' }
const capabilities = { server_stream: support, browser_audition: support, thumbnail: support, inspection: support, preview: support, render: support }
const workspace: ReviewWorkspace = {
  projectId: 'project-1', sourceMode: 'inventory', name: 'Project', artworkLabel: '',
  assets: [
    { asset_id: 'asset-a', relative_path: 'song.wav', kind: 'audio', presence: 'present', byte_length: 10, modified_ns: 1, sha256: 'a'.repeat(64), verification_state: 'verified', probe_status: 'ok', media: { duration_seconds: 90, audio_codec: 'pcm_s16le' }, capabilities, diagnostics: [] },
    { asset_id: 'image-a', relative_path: 'art/cover.png', kind: 'image', presence: 'present', byte_length: 20, modified_ns: 2, sha256: 'c'.repeat(64), verification_state: 'verified', probe_status: 'ok', media: { width: 1200, height: 1200 }, capabilities, diagnostics: [] },
  ],
  tracks: [{ id: 'asset-a', number: 1, title: 'Song', audio: 'song.wav', audio_sha256: 'a'.repeat(64), normalized_sample_count: 90 * 48_000, durationSeconds: 90 }],
}
const v1 = (): CreationState => ({
  contract_version: 'wrld-creation-state/1.0', project_id: 'project-1', revision: 1, save_id: 'initial', preferred_short_duration_seconds: 45,
  albums: [], singles: [],
  shorts: [{ short_id: 'short-stable', asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), status: 'active', start_sample: 0, sample_count: 45 * 48_000, origin: 'manual', review_required: false, customized: true, approved: true, settings: { caption: 'preserve' } }],
  state_digest: '0'.repeat(64), issues: [],
})
const portraitTemplate = (): VisualTemplate => ({
  visual_template_id: 'visual-portrait', label: 'Portrait', canvas: { aspect_ratio: '9:16' }, background_image: null,
  geometry: { fit_mode: 'contain', focal_x: 0.5, focal_y: 0.5 }, camera: { mode: 'bounded', max_zoom: 1.04 },
  visualizer: { enabled: true, bar_count: 24, opacity: 0.65 }, progress: { enabled: true },
  color_treatment: { mode: 'custom', hex: '#416E9D', intensity: 0.18 },
})
const landscapeTemplate = (): VisualTemplate => ({
  visual_template_id: 'visual-landscape', label: 'Landscape', canvas: { aspect_ratio: '16:9' }, background_image: null,
  geometry: { fit_mode: 'contain', focal_x: 0.5, focal_y: 0.5 }, camera: { mode: 'static', max_zoom: 1.04 },
  visualizer: { enabled: false, bar_count: 24, opacity: 0.65 }, progress: { enabled: false }, color_treatment: { mode: 'none' },
})
const v2 = (): CreationStateV2 => ({
  contract_version: 'wrld-creation-state/2.0', project_id: 'project-1', revision: 2, save_id: 'upgrade', preferred_short_duration_seconds: 45,
  visual_templates: [portraitTemplate(), landscapeTemplate()],
  albums: [{ album_plan_id: 'album-stable', label: 'Album plan', status: 'active', assignments: [{ assignment_id: 'assignment-stable', asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), duplicate_acknowledged: false }], visual_template_id: 'visual-landscape' }],
  singles: [
    { single_id: 'single-a', asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), status: 'active', customized: false, approved: true, settings: {}, visual_template_id: 'visual-landscape' },
    { single_id: 'single-b', asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), status: 'archived', customized: true, approved: true, settings: { label: 'archived' }, visual_template_id: 'visual-landscape' },
  ],
  shorts: [{ short_id: 'short-stable', asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), status: 'active', start_sample: 0, sample_count: 45 * 48_000, origin: 'manual', review_required: false, customized: true, approved: true, settings: { caption: 'preserve' }, visual_template_id: 'visual-portrait' }],
  state_digest: '1'.repeat(64), issues: [],
})
const v3 = (): CreationStateV3 => {
  const base = v2()
  const member = (source: VisualTemplate, visualTemplateId: string, label: string, aspectRatio: '16:9' | '9:16') => ({ ...structuredClone(source), visual_template_id: visualTemplateId, label, canvas: { aspect_ratio: aspectRatio } })
  const templates = [
    member(landscapeTemplate(), 'family-a-album', 'Midnight Album', '16:9'),
    member(landscapeTemplate(), 'family-a-single', 'Midnight Single', '16:9'),
    member(portraitTemplate(), 'family-a-short', 'Midnight Short', '9:16'),
    member(landscapeTemplate(), 'family-b-album', 'Midnight Alternate Album', '16:9'),
    member(landscapeTemplate(), 'family-b-single', 'Midnight Alternate Single', '16:9'),
    member(portraitTemplate(), 'family-b-short', 'Midnight Alternate Short', '9:16'),
    member(landscapeTemplate(), 'standalone-landscape', 'Standalone Landscape', '16:9'),
    member(portraitTemplate(), 'standalone-portrait', 'Standalone Portrait', '9:16'),
  ]
  return {
    ...base,
    contract_version: 'wrld-creation-state/3.0',
    visual_templates: templates,
    visual_template_families: [
      { visual_template_family_id: 'family-a', name: 'Midnight', members: { album_visual_template_id: 'family-a-album', single_visual_template_id: 'family-a-single', short_visual_template_id: 'family-a-short' } },
      { visual_template_family_id: 'family-b', name: 'Midnight', members: { album_visual_template_id: 'family-b-album', single_visual_template_id: 'family-b-single', short_visual_template_id: 'family-b-short' } },
    ],
    albums: base.albums.map((item) => ({ ...item, visual_template_id: 'family-a-album' })),
    singles: base.singles.map((item) => ({ ...item, visual_template_id: 'family-a-single' })),
    shorts: base.shorts.map((item) => ({ ...item, visual_template_id: 'family-a-short' })),
  }
}
const response = (status: number, body: unknown) => ({ ok: status >= 200 && status < 300, status, json: async () => body }) as Response

afterEach(() => vi.restoreAllMocks())

describe('template-based Editor persistence', () => {
  it('disables empty and archived-only categories and selects the first active category', async () => {
    const state = v2()
    state.albums[0].status = 'archived'
    state.singles = Array.from({ length: 12 }, (_, index) => ({ ...state.singles[0], single_id: `single-${index + 1}` }))
    state.shorts = Array.from({ length: 24 }, (_, index) => ({ ...state.shorts[0], short_id: `short-${index + 1}` }))
    vi.stubGlobal('fetch', vi.fn(async () => response(200, structuredClone(state))))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    const albums = await screen.findByRole('button', { name: 'Albums' })
    const singles = screen.getByRole('button', { name: 'Singles' })
    expect(albums).toHaveAttribute('aria-disabled', 'true')
    expect(albums).toHaveAccessibleDescription('Item Disabled. There are no Albums selected.')
    await waitFor(() => expect(singles).toHaveAttribute('aria-current', 'page'))
    albums.focus()
    expect(screen.getByRole('tooltip')).toHaveTextContent('Item Disabled. There are no Albums selected.')
    await user.keyboard('{Enter}')
    await user.keyboard(' ')
    expect(singles).toHaveAttribute('aria-current', 'page')
    await user.click(albums)
    expect(singles).toHaveAttribute('aria-current', 'page')
  })

  it('shows a Creation recovery empty state when every category is archived or empty', async () => {
    const state = v2()
    state.albums[0].status = 'archived'; state.singles.forEach((item) => { item.status = 'archived' }); state.shorts[0].status = 'archived'
    vi.stubGlobal('fetch', vi.fn(async () => response(200, structuredClone(state))))
    render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    expect(await screen.findByText('No active Creation outputs')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open Creation' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Shorts' })).toHaveAttribute('aria-disabled', 'true')
  })

  it('reconciles the selected category after a conflict reload removes its final active target', async () => {
    const latest = v2()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        latest.albums[0].status = 'archived'; latest.revision = 3
        return response(409, { error: { code: 'REVISION_CONFLICT', message: 'A newer Creation revision exists.', details: { current_revision: 3 } } })
      }
      return response(200, structuredClone(latest))
    }))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await screen.findByText('album-stable')
    fireEvent.change(screen.getByLabelText('Template label'), { target: { value: 'Conflict draft' } })
    await user.click(screen.getByRole('button', { name: /Save editor draft/i }))
    await user.click(await screen.findByRole('button', { name: 'Reload server state' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Albums' })).toHaveAttribute('aria-disabled', 'true'))
    expect(screen.getByRole('button', { name: 'Singles' })).toHaveAttribute('aria-current', 'page')
  })

  it('collapses and groups warnings while preserving exact target navigation and local resolution', async () => {
    const state = v2()
    state.issues = [{
      code: 'VISUAL_SOURCE_REQUIRED', visual_template_id: 'visual-portrait', asset_id: null, relative_path: null,
      expected_sha256: null, observed_sha256: null, affected_targets: [{ kind: 'short', id: 'short-stable', status: 'active' }],
    }]
    vi.stubGlobal('fetch', vi.fn(async () => response(200, structuredClone(state))))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    const warnings = (await screen.findByText('Creation warnings (1)')).closest('details')
    expect(warnings).not.toHaveAttribute('open')
    await user.click(screen.getByText('Creation warnings (1)'))
    expect(screen.getByText('1 Short needs a background.')).toBeVisible()
    await user.click(screen.getByText('1 Short needs a background.'))
    await user.click(screen.getByRole('button', { name: 'Edit dependency' }))
    expect(screen.getByRole('button', { name: 'Shorts' })).toHaveAttribute('aria-current', 'page')
    await user.selectOptions(screen.getByLabelText('Background image'), 'image-a')
    expect(screen.queryByText('Creation warnings (1)')).not.toBeInTheDocument()
  })

  it('offers the sole included image only for a newly created template', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response(200, v2())))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await screen.findByText('album-stable')
    expect(screen.queryByRole('button', { name: 'Use only included image' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /New template/i }))
    await user.click(screen.getByRole('button', { name: 'Use only included image' }))
    expect(screen.getByLabelText('Background image')).toHaveValue('image-a')
  })

  it.each([
    ['zero', { ...workspace, assets: workspace.assets.filter((item) => item.kind !== 'image') }],
    ['multiple', { ...workspace, assets: [...workspace.assets, { ...workspace.assets[1], asset_id: 'image-b', relative_path: 'art/second.png', sha256: 'd'.repeat(64) }] }],
  ])('does not suggest an image when %s eligible images are available', async (_label, candidateWorkspace) => {
    vi.stubGlobal('fetch', vi.fn(async () => response(200, v2())))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={candidateWorkspace}/></StudioProvider>)
    await screen.findByText('album-stable')
    await user.click(screen.getByRole('button', { name: /New template/i }))
    expect(screen.queryByRole('button', { name: 'Use only included image' })).not.toBeInTheDocument()
  })

  it('bulk-assigns one shared template atomically, preserves no-ops and excludes archived targets', async () => {
    let stored: CreationState = v2()
    if (stored.contract_version !== 'wrld-creation-state/2.0') throw new Error('wrong fixture')
    const secondTemplate = { ...structuredClone(stored.visual_templates[0]), visual_template_id: 'visual-portrait-2', label: 'Portrait 2' }
    stored.visual_templates.push(secondTemplate)
    stored.shorts.push(
      { ...structuredClone(stored.shorts[0]), short_id: 'short-second', visual_template_id: 'visual-portrait-2', customized: false, approved: true },
      { ...structuredClone(stored.shorts[0]), short_id: 'short-archived', status: 'archived', visual_template_id: 'visual-portrait-2', customized: false, approved: true },
    )
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const request = JSON.parse(String(init.body)) as { state: CreationState }
        stored = { ...request.state, revision: stored.revision + 1, state_digest: '8'.repeat(64), issues: [] }
      }
      return response(200, structuredClone(stored))
    }))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await user.click(await screen.findByRole('button', { name: 'Shorts' }))
    await user.click(screen.getByRole('button', { name: 'Assign to…' }))
    expect(screen.getByText(/Existing consumers \(1\)/i)).toBeInTheDocument()
    expect(screen.getByText('2 active outputs are excluded because this 9:16 template is incompatible.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'All active Shorts' }))
    expect(screen.getByText('1 output will change.')).toBeInTheDocument()
    expect(screen.getByText('1 no-op assignment will be preserved.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Apply to 1' }))
    expect(screen.getByRole('button', { name: 'Undo' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: 'Undo' }))
    expect(screen.getByRole('button', { name: 'Redo' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: 'Redo' }))
    await user.click(screen.getByRole('button', { name: /Save editor draft/i }))
    await waitFor(() => expect(stored.revision).toBe(3))
    if (stored.contract_version !== 'wrld-creation-state/2.0') throw new Error('wrong stored contract')
    expect(stored.shorts.find((item) => item.short_id === 'short-second')).toMatchObject({ visual_template_id: 'visual-portrait', customized: true, approved: false })
    expect(stored.shorts.find((item) => item.short_id === 'short-stable')).toMatchObject({ visual_template_id: 'visual-portrait', approved: true })
    expect(stored.shorts.find((item) => item.short_id === 'short-archived')).toMatchObject({ visual_template_id: 'visual-portrait-2', approved: true })
  })

  it('bulk-assigns a compatible landscape template to active Singles only', async () => {
    let stored: CreationState = v2()
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const request = JSON.parse(String(init.body)) as { state: CreationState }
        stored = { ...request.state, revision: stored.revision + 1, state_digest: '7'.repeat(64), issues: [] }
      }
      return response(200, structuredClone(stored))
    }))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await screen.findByText('album-stable')
    await user.click(screen.getByRole('button', { name: /New template/i }))
    await user.click(screen.getByRole('button', { name: 'Assign to…' }))
    await user.click(screen.getByRole('button', { name: 'All active Singles' }))
    expect(screen.getByText('1 active output is excluded because this 16:9 template is incompatible.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Apply to 1' }))
    await user.click(screen.getByRole('button', { name: /Save editor draft/i }))
    await waitFor(() => expect(stored.revision).toBe(3))
    if (stored.contract_version !== 'wrld-creation-state/2.0') throw new Error('wrong stored contract')
    expect(stored.singles[0]).toMatchObject({ customized: true, approved: false })
    expect(stored.singles[1]).toMatchObject({ status: 'archived', visual_template_id: 'visual-landscape', approved: true })
  })

  it('requires an explicit revision-safe upgrade and preserves stable Short work', async () => {
    let stored = v1()
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const request = JSON.parse(String(init.body)) as { save_id: string; state: CreationState }
        stored = { ...request.state, revision: 2, save_id: request.save_id, state_digest: 'd'.repeat(64), issues: [] }
      }
      return response(200, structuredClone(stored))
    }))
    const user = userEvent.setup()
    render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    expect(await screen.findByText(/Upgrade required for visual templates/i)).toBeInTheDocument()
    expect(stored.contract_version).toBe('wrld-creation-state/1.0')
    await user.click(screen.getByRole('button', { name: 'Upgrade Creation document' }))
    await screen.findByRole('navigation', { name: 'Composition category' })
    expect(stored.contract_version).toBe('wrld-creation-state/2.0')
    if (stored.contract_version !== 'wrld-creation-state/2.0') throw new Error('upgrade failed')
    expect(stored.shorts[0]).toMatchObject({ short_id: 'short-stable', approved: true, settings: { caption: 'preserve' } })
    expect(stored.visual_templates[0]).toMatchObject({ camera: { mode: 'bounded', max_zoom: 1.04 }, progress: { enabled: true } })
    await user.click(screen.getByRole('button', { name: 'Shorts' }))
    expect(await screen.findByText('short-stable')).toBeInTheDocument()
  })

  it('edits typed visual settings, previews the real project image, and survives a fresh mount', async () => {
    let stored: CreationState = v2()
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const request = JSON.parse(String(init.body)) as { save_id: string; state: CreationState }
        stored = { ...request.state, revision: stored.revision + 1, save_id: request.save_id, state_digest: 'e'.repeat(64), issues: [] }
      }
      return response(200, structuredClone(stored))
    }))
    const user = userEvent.setup(); const first = render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await user.click(await screen.findByRole('button', { name: 'Shorts' }))
    const play = vi.mocked(HTMLMediaElement.prototype.play)
    play.mockClear()
    await user.click(screen.getByRole('button', { name: 'Play song.wav · Short 1' }))
    await screen.findByRole('button', { name: 'Pause song.wav · Short 1' })
    const media = play.mock.contexts.at(-1) as HTMLMediaElement
    media.currentTime = 22.5
    media.dispatchEvent(new Event('timeupdate'))
    await waitFor(() => expect(document.querySelector('.composition-canvas .preview-progress span')).toHaveStyle({ width: '50%' }))
    media.currentTime = 45
    media.dispatchEvent(new Event('timeupdate'))
    await screen.findByRole('button', { name: 'Play song.wav · Short 1' })
    fireEvent.change(screen.getByLabelText('Tint intensity'), { target: { value: '0.31' } })
    await user.selectOptions(screen.getByLabelText('Background image'), 'image-a')
    expect(screen.getByRole('img', { name: /Selected background art\/cover.png/i })).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Background fit'), 'cover')
    fireEvent.change(screen.getByLabelText('Focal X'), { target: { value: '0.25' } })
    const previewImage = document.querySelector<HTMLImageElement>('.composition-canvas > img')
    expect(previewImage).toHaveStyle({ objectFit: 'cover', objectPosition: '25% 50%' })
    expect(screen.getByText(/Approximate browser preview/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Save editor draft/i }))
    await waitFor(() => expect(stored.revision).toBe(3))
    if (stored.contract_version !== 'wrld-creation-state/2.0') throw new Error('wrong stored contract')
    expect(stored.shorts[0].short_id).toBe('short-stable')
    expect(stored.shorts[0].approved).toBe(false)
    expect(stored.visual_templates[0].background_image).toEqual({ asset_id: 'image-a', expected_sha256: 'c'.repeat(64) })
    expect(stored.visual_templates[0].geometry).toMatchObject({ fit_mode: 'cover', focal_x: 0.25, focal_y: 0.5 })
    expect(stored.visual_templates[0].color_treatment).toMatchObject({ mode: 'custom', intensity: 0.31 })
    first.unmount()
    render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await user.click(await screen.findByRole('button', { name: 'Shorts' }))
    expect(screen.getByLabelText('Tint intensity')).toHaveValue('0.31')
    expect(screen.getByLabelText('Background image')).toHaveValue('image-a')
  })

  it('stops the prior audio preview when the selected composition changes', async () => {
    const state = v2()
    state.shorts.push({ ...structuredClone(state.shorts[0]), short_id: 'short-second' })
    vi.stubGlobal('fetch', vi.fn(async () => response(200, structuredClone(state))))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await user.click(await screen.findByRole('button', { name: 'Shorts' }))
    const pause = vi.mocked(HTMLMediaElement.prototype.pause)
    pause.mockClear()
    await user.click(screen.getByRole('button', { name: 'Play song.wav · Short 1' }))
    await screen.findByRole('button', { name: 'Pause song.wav · Short 1' })
    await user.click(screen.getByRole('button', { name: /song.wav · Short 2/ }))
    await waitFor(() => expect(pause).toHaveBeenCalled())
    expect(screen.getByRole('button', { name: 'Play song.wav · Short 2' })).toBeInTheDocument()
  })

  it('confirms shared edits, includes archived consumers, and Customize copy detaches one target', async () => {
    let stored: CreationState = v2()
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const request = JSON.parse(String(init.body)) as { state: CreationState }
        stored = { ...request.state, revision: stored.revision + 1, state_digest: 'f'.repeat(64), issues: [] }
      }
      return response(200, structuredClone(stored))
    }))
    const confirmation = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValue(true)
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    expect(await screen.findByText('album-stable')).toBeInTheDocument()
    expect(screen.getByLabelText('Album track')).toHaveValue('assignment-stable')
    await user.click(await screen.findByRole('button', { name: 'Singles' }))
    expect(screen.getByText(/3 target\(s\) use this template/i)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Maximum zoom'), { target: { value: '1.05' } })
    expect(confirmation).toHaveBeenCalledWith(expect.stringContaining('Single single-b (archived)'))
    expect(screen.getByLabelText('Maximum zoom')).toHaveValue('1.04')
    fireEvent.change(screen.getByLabelText('Maximum zoom'), { target: { value: '1.05' } })
    expect(screen.getByLabelText('Maximum zoom')).toHaveValue('1.05')
    await user.click(screen.getByRole('button', { name: /Customize copy/i }))
    fireEvent.change(screen.getByLabelText('Focal X'), { target: { value: '0.2' } })
    await user.click(screen.getByRole('button', { name: /Save editor draft/i }))
    await waitFor(() => expect(stored.revision).toBe(3))
    if (stored.contract_version !== 'wrld-creation-state/2.0') throw new Error('wrong stored contract')
    const storedV2 = stored as CreationStateV2
    expect(storedV2.visual_templates).toHaveLength(3)
    expect(storedV2.singles[0].visual_template_id).not.toBe('visual-landscape')
    expect(storedV2.singles[1].visual_template_id).toBe('visual-landscape')
    const copy = storedV2.visual_templates.find((item) => item.visual_template_id === storedV2.singles[0].visual_template_id)
    expect(copy?.geometry.focal_x).toBe(0.2)
    expect(storedV2.visual_templates.find((item) => item.visual_template_id === 'visual-landscape')?.geometry.focal_x).toBe(0.5)
  })

  it('accepts a changed image as one undoable change and invalidates every linked approval', async () => {
    const changed = v2()
    changed.visual_templates[0].background_image = { asset_id: 'image-a', expected_sha256: 'b'.repeat(64) }
    changed.issues = [{
      code: 'VISUAL_SOURCE_CHANGED', visual_template_id: 'visual-portrait', asset_id: 'image-a', relative_path: 'art/cover.png',
      expected_sha256: 'b'.repeat(64), observed_sha256: 'c'.repeat(64),
      affected_targets: [{ kind: 'short', id: 'short-stable', status: 'active' }],
    }]
    let stored: CreationState = changed
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const request = JSON.parse(String(init.body)) as { state: CreationState }
        stored = { ...request.state, revision: stored.revision + 1, state_digest: '9'.repeat(64), issues: [] }
      }
      return response(200, structuredClone(stored))
    }))
    const confirmation = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await user.click(await screen.findByText('Creation warnings (1)'))
    await user.click(screen.getByText('1 Short has a changed background.'))
    await user.click(screen.getByRole('button', { name: 'Accept changed image' }))
    expect(confirmation).toHaveBeenCalledWith(expect.stringContaining('clear linked Single/Short approvals'))
    expect(screen.getByRole('button', { name: 'Undo' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: /Save editor draft/i }))
    await waitFor(() => expect(stored.revision).toBe(3))
    if (stored.contract_version !== 'wrld-creation-state/2.0') throw new Error('wrong stored contract')
    expect(stored.visual_templates[0].background_image?.expected_sha256).toBe('c'.repeat(64))
    expect(stored.shorts[0]).toMatchObject({ approved: false, customized: true })
  })

  it('keeps dirty typed state and offers reload when a concurrent revision wins', async () => {
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => init?.method === 'PUT'
      ? response(409, { error: { code: 'REVISION_CONFLICT', message: 'A newer Creation revision exists.', details: { current_revision: 3 } } })
      : response(200, v2())))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await user.click(await screen.findByRole('button', { name: 'Shorts' }))
    fireEvent.change(screen.getByLabelText('Tint intensity'), { target: { value: '0.27' } })
    await user.click(screen.getByRole('button', { name: /Save editor draft/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/newer Creation revision/i)
    expect(screen.getByRole('button', { name: /Reload server state/i })).toBeInTheDocument()
    expect(screen.getByLabelText('Tint intensity')).toHaveValue('0.27')
  })

  it('displays duplicate-named families by stable identity and resolves the explicit member for each output type', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response(200, v3())))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await screen.findByText('album-stable')
    let summary = document.querySelector('.assigned-template-summary')!
    expect(summary).toHaveTextContent('FamilyMidnight')
    expect(summary).toHaveTextContent('VersionAlbum — 16:9')
    expect(summary).toHaveTextContent('TemplateMidnight Album')
    const versions = screen.getByLabelText('Midnight family versions')
    expect(versions).toHaveTextContent('Album16:9 · Midnight AlbumCurrent')
    expect(versions).toHaveTextContent('Single16:9 · Midnight Single')
    expect(versions).toHaveTextContent('Short9:16 · Midnight Short')
    const albumOptions = Array.from((screen.getByLabelText('Assigned visual template') as HTMLSelectElement).options)
    expect(albumOptions.map((item) => item.value)).toEqual(expect.arrayContaining(['family-a-album', 'family-b-album', 'standalone-landscape']))
    expect(albumOptions.map((item) => item.value)).not.toContain('family-a-single')
    expect(albumOptions.filter((item) => item.text.includes('Midnight')).map((item) => item.text)).toEqual(expect.arrayContaining([expect.stringContaining('family-a'), expect.stringContaining('family-b')]))

    await user.click(screen.getByRole('button', { name: 'Singles' }))
    summary = document.querySelector('.assigned-template-summary')!
    expect(summary).toHaveTextContent('VersionSingle — 16:9')
    expect((screen.getByLabelText('Assigned visual template') as HTMLSelectElement).options.namedItem('family-a-album')).toBeNull()

    await user.click(screen.getByRole('button', { name: 'Shorts' }))
    summary = document.querySelector('.assigned-template-summary')!
    expect(summary).toHaveTextContent('VersionShort — 9:16')
    expect(screen.getByLabelText('Assigned visual template')).toHaveValue('family-a-short')
  })

  it('assigns only the current family role, keeps archived targets unchanged, and preserves the registry through undo, redo, and Save', async () => {
    let stored: CreationState = v3()
    const originalFamilies = structuredClone((stored as CreationStateV3).visual_template_families)
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const request = JSON.parse(String(init.body)) as { state: CreationState }
        stored = { ...request.state, revision: stored.revision + 1, state_digest: '6'.repeat(64), issues: [] }
      }
      return response(200, structuredClone(stored))
    }))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await user.click(await screen.findByRole('button', { name: 'Singles' }))
    const select = screen.getByLabelText('Assigned visual template') as HTMLSelectElement
    expect(Array.from(select.options).map((item) => item.value)).not.toContain('family-b-album')
    await user.selectOptions(select, 'family-b-single')
    expect(screen.getByRole('button', { name: 'Undo' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: 'Undo' }))
    expect(select).toHaveValue('family-a-single')
    await user.click(screen.getByRole('button', { name: 'Redo' }))
    expect(select).toHaveValue('family-b-single')
    await user.click(screen.getByRole('button', { name: /Save editor draft/i }))
    await waitFor(() => expect(stored.revision).toBe(3))
    if (stored.contract_version !== 'wrld-creation-state/3.0') throw new Error('wrong stored contract')
    expect(stored.visual_template_families).toEqual(originalFamilies)
    expect(stored.singles[0]).toMatchObject({ visual_template_id: 'family-b-single', customized: true, approved: false })
    expect(stored.singles[1]).toMatchObject({ status: 'archived', visual_template_id: 'family-a-single', approved: true })
    expect(stored.albums[0].visual_template_id).toBe('family-a-album')
    await user.selectOptions(screen.getByLabelText('Assigned visual template'), 'standalone-landscape')
    expect(document.querySelector('.assigned-template-summary')).toHaveTextContent('StandaloneStandalone Landscape')
    await user.click(screen.getByRole('button', { name: /Save editor draft/i }))
    await waitFor(() => expect(stored.revision).toBe(4))
    if (stored.contract_version !== 'wrld-creation-state/3.0') throw new Error('wrong stored contract')
    expect(stored.visual_template_families).toEqual(originalFamilies)
    expect(stored.singles[0].visual_template_id).toBe('standalone-landscape')
  })

  it('edits only the selected concrete family member and excludes cross-role bulk assignment', async () => {
    let stored: CreationState = v3()
    const original = structuredClone(stored as CreationStateV3)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const request = JSON.parse(String(init.body)) as { state: CreationState }
        stored = { ...request.state, revision: stored.revision + 1, state_digest: '5'.repeat(64), issues: [] }
      }
      return response(200, structuredClone(stored))
    }))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await screen.findByText('album-stable')
    await user.click(screen.getByRole('button', { name: 'Assign to…' }))
    expect(screen.queryByRole('button', { name: 'All active Singles' })).not.toBeInTheDocument()
    expect(screen.getByText('2 active outputs are excluded because this Album family member is role-specific.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Shorts' }))
    fireEvent.change(screen.getByLabelText('Tint intensity'), { target: { value: '0.33' } })
    await user.click(screen.getByRole('button', { name: /Save editor draft/i }))
    await waitFor(() => expect(stored.revision).toBe(3))
    if (stored.contract_version !== 'wrld-creation-state/3.0') throw new Error('wrong stored contract')
    expect(stored.visual_template_families).toEqual(original.visual_template_families)
    expect(stored.visual_templates.find((item) => item.visual_template_id === 'family-a-album')).toEqual(original.visual_templates.find((item) => item.visual_template_id === 'family-a-album'))
    expect(stored.visual_templates.find((item) => item.visual_template_id === 'family-a-single')).toEqual(original.visual_templates.find((item) => item.visual_template_id === 'family-a-single'))
    expect(stored.visual_templates.find((item) => item.visual_template_id === 'family-a-short')?.color_treatment).toMatchObject({ intensity: 0.33 })
  })

  it('reports an invalid family reference without crashing or offering it for assignment', async () => {
    const invalid = v3()
    invalid.visual_template_families[0].members.short_visual_template_id = 'missing-short-member'
    invalid.shorts[0].visual_template_id = 'missing-short-member'
    vi.stubGlobal('fetch', vi.fn(async () => response(200, invalid)))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await user.click(await screen.findByRole('button', { name: 'Shorts' }))
    expect(screen.getByRole('alert')).toHaveTextContent('missing Short member missing-short-member')
    expect(screen.getByLabelText('Assigned visual template')).toHaveValue('missing-short-member')
    expect(screen.getByRole('option', { name: /Unavailable template/ })).toBeDisabled()
  })

  it('creates a scratch family as one undoable change and retains its pending IDs after a revision conflict', async () => {
    const stored = v3()
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => init?.method === 'PUT'
      ? response(409, { error: { code: 'REVISION_CONFLICT', message: 'A newer Creation revision exists.', details: { current_revision: 4 } } })
      : response(200, structuredClone(stored))))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await screen.findByText('album-stable')
    await user.click(screen.getByRole('button', { name: 'Create Template Family' }))
    await user.type(screen.getByLabelText('New family name'), 'New family')
    await user.click(screen.getByRole('button', { name: 'Create family' }))
    const select = screen.getByLabelText('Assigned visual template') as HTMLSelectElement
    const created = Array.from(select.options).find((item) => item.text.includes('New family — Album'))!
    expect(created.value).toMatch(/^visual-template-/)
    const pendingId = created.value
    await user.click(screen.getByRole('button', { name: 'Undo' }))
    expect(Array.from(select.options).map((item) => item.value)).not.toContain(pendingId)
    await user.click(screen.getByRole('button', { name: 'Redo' }))
    expect(Array.from(select.options).map((item) => item.value)).toContain(pendingId)
    await user.click(screen.getByRole('button', { name: /Save editor draft/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('newer Creation revision')
    expect(Array.from((screen.getByLabelText('Assigned visual template') as HTMLSelectElement).options).map((item) => item.value)).toContain(pendingId)
  })

  it('creates a family from the explicitly selected standalone template without reassigning the current composition', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response(200, v3())))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await screen.findByText('album-stable')
    expect(screen.getByLabelText('Assigned visual template')).toHaveValue('family-a-album')
    await user.click(screen.getByRole('button', { name: 'Create Template Family' }))
    await user.type(screen.getByLabelText('New family name'), 'Standalone seed')
    await user.selectOptions(screen.getByLabelText('Family starting point'), 'standalone-landscape')
    await user.click(screen.getByRole('button', { name: 'Create family' }))
    const select = screen.getByLabelText('Assigned visual template') as HTMLSelectElement
    expect(select).toHaveValue('family-a-album')
    const seeded = Array.from(select.options).find((item) => item.text.includes('Standalone seed — Album'))
    expect(seeded?.value).toBe('standalone-landscape')
    expect(screen.getByRole('button', { name: 'Undo' })).toBeEnabled()
  })

  it('synchronizes one edited configuration across all family members atomically and invalidates active and archived approvals', async () => {
    let stored: CreationState = v3()
    const original = structuredClone(stored as CreationStateV3)
    const confirmation = vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const request = JSON.parse(String(init.body)) as { state: CreationState }
        stored = { ...request.state, revision: stored.revision + 1, state_digest: '4'.repeat(64), issues: [] }
      }
      return response(200, structuredClone(stored))
    }))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await user.click(await screen.findByRole('button', { name: 'Shorts' }))
    await user.click(screen.getByRole('radio', { name: /All Three Types/i }))
    expect(screen.getByText('Selected: All Three Types')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Background image'), 'image-a')
    expect(confirmation).toHaveBeenCalledWith(expect.stringContaining('1 archived consumers'))
    expect(screen.getByRole('button', { name: 'Undo' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: 'Undo' }))
    expect(screen.getByLabelText('Background image')).toHaveValue('')
    await user.click(screen.getByRole('button', { name: 'Redo' }))
    expect(screen.getByLabelText('Background image')).toHaveValue('image-a')
    await user.click(screen.getByRole('button', { name: /Save editor draft/i }))
    await waitFor(() => expect(stored.revision).toBe(3))
    if (stored.contract_version !== 'wrld-creation-state/3.0') throw new Error('wrong stored contract')
    const saved = stored as CreationStateV3
    const ids = ['family-a-album', 'family-a-single', 'family-a-short']
    const members = ids.map((id) => saved.visual_templates.find((item) => item.visual_template_id === id)!)
    members.forEach((item) => expect(item).toMatchObject({ background_image: { asset_id: 'image-a', expected_sha256: 'c'.repeat(64) }, camera: original.visual_templates.find((candidate) => candidate.visual_template_id === 'family-a-short')!.camera, visualizer: original.visual_templates.find((candidate) => candidate.visual_template_id === 'family-a-short')!.visualizer, progress: original.visual_templates.find((candidate) => candidate.visual_template_id === 'family-a-short')!.progress }))
    expect(members.map((item) => item.canvas.aspect_ratio)).toEqual(['16:9', '16:9', '9:16'])
    expect(saved.singles.map((item) => ({ status: item.status, approved: item.approved, customized: item.customized }))).toEqual([{ status: 'active', approved: false, customized: true }, { status: 'archived', approved: false, customized: true }])
    expect(saved.shorts[0]).toMatchObject({ approved: false, customized: true })
  })

  it('customizes only the selected composition while preserving its source family and unrelated consumers', async () => {
    let stored: CreationState = v3()
    const originalFamily = structuredClone((stored as CreationStateV3).visual_template_families)
    const originalSingle = structuredClone((stored as CreationStateV3).visual_templates.find((item) => item.visual_template_id === 'family-a-single'))
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const request = JSON.parse(String(init.body)) as { state: CreationState }
        stored = { ...request.state, revision: stored.revision + 1, state_digest: '2'.repeat(64), issues: [] }
      }
      return response(200, structuredClone(stored))
    }))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await user.click(await screen.findByRole('button', { name: 'Singles' }))
    await user.click(screen.getByRole('button', { name: /This Composition Only/i }))
    expect(document.querySelector('.assigned-template-summary')).toHaveTextContent('StandaloneMidnight Single copy')
    expect(screen.getByRole('button', { name: /Save editor draft/i })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: /Save editor draft/i }))
    await waitFor(() => expect(stored.revision).toBe(3))
    if (stored.contract_version !== 'wrld-creation-state/3.0') throw new Error('wrong stored contract')
    const copyId = stored.singles[0].visual_template_id
    expect(stored.singles[0]).toMatchObject({ approved: true, customized: false })
    expect(stored.visual_template_families).toEqual(originalFamily)
    fireEvent.change(screen.getByLabelText('Maximum zoom'), { target: { value: '1.05' } })
    await user.click(screen.getByRole('button', { name: /Save editor draft/i }))
    await waitFor(() => expect(stored.revision).toBe(4))
    if (stored.contract_version !== 'wrld-creation-state/3.0') throw new Error('wrong stored contract')
    expect(stored.visual_template_families).toEqual(originalFamily)
    expect(stored.visual_templates.find((item) => item.visual_template_id === 'family-a-single')).toEqual(originalSingle)
    expect(stored.singles[0]).toMatchObject({ approved: false, customized: true })
    expect(stored.singles[0].visual_template_id).toBe(copyId)
    expect(stored.singles[1]).toMatchObject({ visual_template_id: 'family-a-single', approved: true, customized: true })
  })

  it('retains a pending composition-only copy identity when Save conflicts', async () => {
    const stored = v3()
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => init?.method === 'PUT'
      ? response(409, { error: { code: 'REVISION_CONFLICT', message: 'A newer Creation revision exists.', details: { current_revision: 9 } } })
      : response(200, structuredClone(stored))))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await user.click(await screen.findByRole('button', { name: 'Singles' }))
    await user.click(screen.getByRole('button', { name: /This Composition Only/i }))
    const pendingId = (screen.getByLabelText('Assigned visual template') as HTMLSelectElement).value
    expect(pendingId).toMatch(/^visual-template-/)
    await user.click(screen.getByRole('button', { name: /Save editor draft/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('newer Creation revision')
    expect(screen.getByLabelText('Assigned visual template')).toHaveValue(pendingId)
  })

  it('renames and ungroups a family as atomic undoable operations without changing references or approvals', async () => {
    let stored: CreationState = v3()
    const original = structuredClone(stored as CreationStateV3)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const request = JSON.parse(String(init.body)) as { state: CreationState }
        stored = { ...request.state, revision: stored.revision + 1, state_digest: '7'.repeat(64), issues: [] }
      }
      return response(200, structuredClone(stored))
    }))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await screen.findByText('album-stable')
    const name = screen.getByLabelText('Managed family name')
    await waitFor(() => expect(name).toHaveValue('Midnight'))
    await user.clear(name); await user.type(name, 'Renamed family')
    await user.click(screen.getByRole('button', { name: 'Rename Family' }))
    expect(screen.getByRole('button', { name: 'Undo' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: 'Undo' }))
    expect(screen.getByLabelText('Managed family name')).toHaveValue('Midnight')
    await user.click(screen.getByRole('button', { name: 'Redo' }))
    expect(screen.getByLabelText('Managed family name')).toHaveValue('Renamed family')
    await user.click(screen.getByRole('button', { name: 'Remove Family Grouping' }))
    await user.click(screen.getByRole('button', { name: /Save editor draft/i }))
    await waitFor(() => expect(stored.revision).toBe(3))
    if (stored.contract_version !== 'wrld-creation-state/3.0') throw new Error('wrong stored contract')
    expect(stored.visual_template_families.some((item) => item.visual_template_family_id === 'family-a')).toBe(false)
    expect(stored.visual_templates).toEqual(original.visual_templates)
    expect(stored.albums).toEqual(original.albums)
    expect(stored.singles).toEqual(original.singles)
    expect(stored.shorts).toEqual(original.shorts)
  })

  it('deletes an unused family with undo/redo and refuses active or archived family consumers', async () => {
    let stored: CreationState = v3()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const request = JSON.parse(String(init.body)) as { state: CreationState }
        stored = { ...request.state, revision: stored.revision + 1, state_digest: '8'.repeat(64), issues: [] }
      }
      return response(200, structuredClone(stored))
    }))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await screen.findByText('album-stable')
    await user.selectOptions(screen.getByLabelText('Managed template family'), 'family-a')
    await user.click(screen.getByRole('button', { name: 'Delete Unused Family' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('active or archived')
    await user.selectOptions(screen.getByLabelText('Managed template family'), 'family-b')
    await user.click(screen.getByRole('button', { name: 'Delete Unused Family' }))
    expect(screen.getByRole('button', { name: 'Undo' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: 'Undo' }))
    expect(screen.getByLabelText('Managed template family')).toHaveValue('family-a')
    await user.selectOptions(screen.getByLabelText('Managed template family'), 'family-b')
    await user.click(screen.getByRole('button', { name: 'Delete Unused Family' }))
    await user.click(screen.getByRole('button', { name: /Save editor draft/i }))
    await waitFor(() => expect(stored.revision).toBe(3))
    if (stored.contract_version !== 'wrld-creation-state/3.0') throw new Error('wrong stored contract')
    expect(stored.visual_template_families.map((item) => item.visual_template_family_id)).toEqual(['family-a'])
    expect(stored.visual_templates.map((item) => item.visual_template_id)).not.toEqual(expect.arrayContaining(['family-b-album', 'family-b-single', 'family-b-short']))
  })

  it('keeps v2 editable while explaining that family workflows require v3', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response(200, v2())))
    render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await screen.findByText('album-stable')
    expect(screen.getByText(/Template families require Creation v3/i)).toBeInTheDocument()
    expect(screen.getByLabelText('Template label')).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Create Template Family' })).not.toBeInTheDocument()
  })
})
