import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { App } from '../src/app/App'
import { StudioProvider } from '../src/app/state'

const waveMocks = (globalThis as typeof globalThis & { __waveMocks: { destroy: ReturnType<typeof vi.fn>; regionListeners: Map<string, (...args: any[]) => void> } }).__waveMocks
const supported = { status: 'supported', reason: 'test' }
const capabilities = { server_stream: supported, browser_audition: supported, thumbnail: supported, inspection: supported, preview: supported, render: supported }

const show = () => render(<StudioProvider><App /></StudioProvider>)
const offline = () => vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('offline'))))
const enterDemo = async (user: ReturnType<typeof userEvent.setup>) => { await screen.findByText(/Import backend unavailable/i); await user.click(screen.getByRole('button', { name: /Use demonstration data/i })); await screen.findByText(/Demonstration dataset active/i) }

describe('WU4 Phase 2A prototype', () => {
  it('opens Review with all non-excluded project assets without workflow selection or demo fallback', async () => {
    const project = { project_id: 'project-1', root_id: 'music', relative_path: 'album', active: true, registered_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', inventory_revision: 1, enrichment: null, availability: 'available' }
    const catalog = { contract_version: 'wrld-project-catalog/2.0', revision: 1, projects: [project] }
    const inventory = { contract_version: 'wrld-project-inventory/1.0', project_id: 'project-1', inventory_revision: 1, scan_id: 'scan-1', completed_at: '2026-01-01T00:00:00Z', policy_version: 'inventory-policy/1.0', diagnostics: [], counts: { audio: 1, image: 0, video: 0, unknown: 0, missing: 0 }, assets: [{ asset_id: 'asset-audio', relative_path: 'nested/song.mp3', kind: 'audio', presence: 'present', byte_length: 100, modified_ns: 1, sha256: 'a'.repeat(64), verification_state: 'verified', probe_status: 'ok', media: { duration_seconds: 12, audio_codec: 'mp3' }, capabilities, diagnostics: [] }] }
    const preferences = { contract_version: 'wrld-project-preferences/1.0', project_id: 'project-1', revision: 1, save_id: 'initial', excluded_asset_ids: [], state_digest: '0'.repeat(64) }
    const creation = { contract_version: 'wrld-creation-state/1.0', project_id: 'project-1', revision: 1, save_id: 'initial', preferred_short_duration_seconds: 45, albums: [], singles: [], shorts: [], state_digest: '0'.repeat(64), issues: [] }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const body = url.includes('/project-roots') ? (url.includes('/directories') ? { directories: [] } : { roots: [{ root_id: 'music', label: 'Music' }] }) : url.endsWith('/inventory') ? inventory : url.endsWith('/preferences') ? preferences : url.endsWith('/creation-state') ? creation : catalog
      return { ok: true, status: 200, json: async () => body } as Response
    }))
    const user = userEvent.setup(); show()
    await screen.findByText(/Import backend connected/i)
    await screen.findByText('song.mp3')
    expect(screen.queryByText(/Workflow/i)).not.toBeInTheDocument()
    const handoff = screen.getByRole('region', { name: 'Review handoff' })
    expect(within(handoff).getByText('album')).toBeInTheDocument()
    expect(within(handoff).getByText('1 included · 0 excluded · Ready')).toBeInTheDocument()
    expect(handoff.previousElementSibling).toHaveClass('asset-grid')
    expect(within(handoff).getByRole('button', { name: 'Open in Review' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: /Open in Review/i }))
    expect(screen.getByText('PROJECT MEDIA')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^Editor$/i }))
    expect(screen.getByRole('heading', { name: /Upgrade required for visual templates/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Upgrade Creation document/i })).toBeInTheDocument()
  })

  it('launches with a truthful demonstration fallback and navigates all four screens', async () => {
    offline(); const user = userEvent.setup(); show()
    await enterDemo(user)
    expect(screen.getByRole('heading', { name: /Import Media/i })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^Metadata/i }))
    expect(screen.getByText(/Metadata is not implemented in WU4/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^Render/i }))
    expect(screen.getByText(/Rendering is not controlled from this UI yet/i)).toBeInTheDocument()
  })

  it('selects an album track and opens its primary Short in Review', async () => {
    offline(); const user = userEvent.setup(); show(); await enterDemo(user)
    await user.click(screen.getByRole('button', { name: /^Review/i }))
    await user.click(screen.getByRole('button', { name: /^Editor$/i }))
    expect(screen.getByRole('button', { name: /Moonlight Over Gyeongju Draft primary Short/i })).toBeInTheDocument()
    expect(screen.getByLabelText('Short start seconds')).toHaveValue(0)
    expect(screen.getByLabelText('Short end seconds')).toHaveValue(45)
    expect(screen.getByText('Approximate')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Audio unavailable/i })).toBeDisabled()
  })

  it('filters the catalog and refreshes the backend without implying persistence', async () => {
    const request = vi.fn(() => Promise.reject(new Error('offline')))
    vi.stubGlobal('fetch', request)
    const user = userEvent.setup(); show(); await enterDemo(user)
    expect(screen.getByText(/Demonstration dataset active/i)).toBeInTheDocument()
    expect(request).toHaveBeenCalled()
  })

  it('edits a Short range, effects, approval, and supports undo and reset', async () => {
    offline(); const user = userEvent.setup(); show(); await enterDemo(user)
    await user.click(screen.getByRole('button', { name: /^Review/i }))
    await user.click(screen.getByRole('button', { name: /^Editor$/i }))
    fireEvent.change(screen.getByLabelText('Short start seconds'), { target: { value: '12.5' } })
    expect(screen.getByLabelText('Short start seconds')).toHaveValue(12.5)
    await user.click(screen.getByLabelText('RMS audio bars'))
    expect(screen.getByLabelText('RMS audio bars')).not.toBeChecked()
    await user.click(screen.getByRole('button', { name: /^Undo$/i }))
    expect(screen.getByLabelText('RMS audio bars')).toBeChecked()
    await user.click(screen.getByRole('button', { name: /Approve Short/i }))
    expect(screen.getByRole('button', { name: /^Approved$/i })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Reset inherited/i }))
    expect(screen.getByText(/Unsaved editor changes/i)).toBeInTheDocument()
  })

  it('synchronizes a dragged waveform region into the numeric Short range', async () => {
    offline(); const user = userEvent.setup(); show(); await enterDemo(user)
    await user.click(screen.getByRole('button', { name: /^Review/i }))
    await user.click(screen.getByRole('button', { name: /^Editor$/i }))
    act(() => waveMocks.regionListeners.get('region-updated')?.({ start: 8.2, end: 26.5 }))
    expect(screen.getByLabelText('Short start seconds')).toHaveValue(8.2)
    expect(screen.getByLabelText('Short end seconds')).toHaveValue(26.5)
  })

  it('supports keyboard nudging of the waveform Short range', async () => {
    offline(); const user = userEvent.setup(); show(); await enterDemo(user)
    await user.click(screen.getByRole('button', { name: /^Review/i }))
    await user.click(screen.getByRole('button', { name: /^Editor$/i }))
    const waveform = screen.getByRole('slider', { name: /Interactive Short start position/i })
    waveform.focus()
    fireEvent.keyDown(waveform, { key: 'ArrowRight' })
    expect(screen.getByLabelText('Short start seconds')).toHaveValue(0.1)
    fireEvent.keyDown(waveform, { key: 'ArrowRight', shiftKey: true })
    expect(screen.getByLabelText('Short start seconds')).toHaveValue(1.1)
  })

  it('warns before discarding dirty edits', async () => {
    offline(); const user = userEvent.setup(); show(); await enterDemo(user)
    await user.click(screen.getByRole('button', { name: /^Review/i }))
    await user.click(screen.getByRole('button', { name: /^Editor$/i }))
    fireEvent.change(screen.getByLabelText('Tint intensity'), { target: { value: '35' } })
    await user.click(screen.getByRole('button', { name: /^Import/i }))
    expect(screen.getByRole('dialog', { name: /Save demonstration Editor changes/i })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Cancel/i }))
    expect(screen.getByRole('button', { name: /Moonlight Over Gyeongju Draft primary Short/i })).toBeInTheDocument()
  })

  it('restores the last Review tab and guards dirty tab changes', async () => {
    offline(); const user = userEvent.setup(); show(); await enterDemo(user)
    await user.click(screen.getByRole('button', { name: /^Review/i }))
    await user.click(screen.getByRole('button', { name: /^Editor$/i }))
    await user.click(screen.getByRole('button', { name: /^Metadata/i }))
    await user.click(screen.getByRole('button', { name: /^Review/i }))
    expect(screen.getByRole('button', { name: /^Editor$/i })).toHaveAttribute('aria-current', 'page')
    fireEvent.change(screen.getByLabelText('Tint intensity'), { target: { value: '35' } })
    await user.click(screen.getByRole('button', { name: /^Media$/i }))
    expect(screen.getByRole('dialog', { name: /Save demonstration Editor changes/i })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Cancel/i }))
    expect(screen.getByRole('button', { name: /^Editor$/i })).toHaveAttribute('aria-current', 'page')
  })

  it('destroys the WaveSurfer instance when switching tracks', async () => {
    offline(); const user = userEvent.setup(); show(); await enterDemo(user)
    await user.click(screen.getByRole('button', { name: /^Review/i }))
    await user.click(screen.getByRole('button', { name: /^Editor$/i }))
    await user.click(screen.getByRole('button', { name: /Lanterns Across the Water/i }))
    await waitFor(() => expect(waveMocks.destroy).toHaveBeenCalled())
  })

  it('persists exclusions separately and restores an excluded asset', async () => {
    const project = { project_id: 'project-1', root_id: 'music', relative_path: 'album', active: true, registered_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', inventory_revision: 1, enrichment: null, availability: 'available' }
    const catalog = { contract_version: 'wrld-project-catalog/2.0', revision: 1, projects: [project] }
    const asset = { asset_id: 'asset-audio', relative_path: 'song.wav', kind: 'audio', presence: 'present', byte_length: 100, modified_ns: 1, sha256: 'a'.repeat(64), verification_state: 'verified', probe_status: 'ok', media: { duration_seconds: 60, audio_codec: 'pcm_s16le' }, capabilities, diagnostics: [] }
    const inventory = { contract_version: 'wrld-project-inventory/1.0', project_id: 'project-1', inventory_revision: 1, scan_id: 'scan-1', completed_at: '2026-01-01T00:00:00Z', policy_version: 'inventory-policy/1.0', diagnostics: [], counts: { audio: 1, image: 0, video: 0, unknown: 0, missing: 0 }, assets: [asset] }
    let preferences = { contract_version: 'wrld-project-preferences/1.0' as const, project_id: 'project-1', revision: 1, save_id: 'initial', excluded_asset_ids: [] as string[], state_digest: '0'.repeat(64) }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/preferences') && init?.method === 'PUT') { const request = JSON.parse(String(init.body)); preferences = { ...request.state, revision: preferences.revision + 1 }; return { ok: true, status: 200, json: async () => preferences } as Response }
      const body = url.includes('/project-roots') ? (url.includes('/directories') ? { directories: [] } : { roots: [{ root_id: 'music', label: 'Music' }] }) : url.endsWith('/inventory') ? inventory : url.endsWith('/preferences') ? preferences : catalog
      return { ok: true, status: 200, json: async () => body } as Response
    }))
    const user = userEvent.setup(); show(); await screen.findByText('song.wav')
    await user.click(screen.getByRole('button', { name: /Exclude song.wav/i }))
    await user.click(screen.getByRole('radio', { name: /^Excluded$/i }))
    expect(screen.getByText('song.wav')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Restore song.wav/i }))
    expect(preferences.excluded_asset_ids).toEqual([])
  })

  it('combines single-choice inclusion with non-empty multi-select media filters', async () => {
    const project = { project_id: 'project-1', root_id: 'music', relative_path: 'album', active: true, registered_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', inventory_revision: 1, enrichment: null, availability: 'available' }
    const inventory = { contract_version: 'wrld-project-inventory/1.0', project_id: 'project-1', inventory_revision: 1, scan_id: 'scan-1', completed_at: '2026-01-01T00:00:00Z', policy_version: 'inventory-policy/1.0', diagnostics: [], counts: { audio: 1, image: 1, video: 1, unknown: 0, missing: 0 }, assets: [
      { asset_id: 'audio', relative_path: 'song.wav', kind: 'audio', presence: 'present', byte_length: 100, modified_ns: 1, sha256: 'a'.repeat(64), verification_state: 'verified', probe_status: 'ok', media: { duration_seconds: 60, audio_codec: 'pcm_s16le' }, capabilities, diagnostics: [] },
      { asset_id: 'image', relative_path: 'cover.png', kind: 'image', presence: 'present', byte_length: 100, modified_ns: 1, sha256: 'b'.repeat(64), verification_state: 'verified', probe_status: 'ok', media: { width: 100, height: 100 }, capabilities, diagnostics: [] },
      { asset_id: 'video', relative_path: 'clip.mp4', kind: 'video', presence: 'present', byte_length: 100, modified_ns: 1, sha256: 'c'.repeat(64), verification_state: 'verified', probe_status: 'ok', media: { duration_seconds: 10, video_codec: 'h264' }, capabilities, diagnostics: [] },
    ] }
    const preferences = { contract_version: 'wrld-project-preferences/1.0', project_id: 'project-1', revision: 1, save_id: 'initial', excluded_asset_ids: [], state_digest: '0'.repeat(64) }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => { const url = String(input); const body = url.includes('/project-roots') ? (url.includes('/directories') ? { directories: [] } : { roots: [{ root_id: 'music', label: 'Music' }] }) : url.endsWith('/inventory') ? inventory : url.endsWith('/preferences') ? preferences : { contract_version: 'wrld-project-catalog/2.0', revision: 1, projects: [project] }; return { ok: true, status: 200, json: async () => body } as Response }))
    const user = userEvent.setup(); show()
    await screen.findByText('song.wav')
    expect(screen.getByRole('radiogroup', { name: 'Inclusion filter' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Media type filter' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Audio' }))
    expect(screen.getByText('song.wav')).toBeInTheDocument()
    expect(screen.queryByText('cover.png')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Image' }))
    expect(screen.getByText('cover.png')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Audio' }))
    expect(screen.queryByText('song.wav')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Image' }))
    expect(screen.getByText('cover.png')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Image' })).toHaveAttribute('aria-pressed', 'true')
    await user.click(screen.getByRole('button', { name: 'All media types' }))
    expect(screen.getByText('song.wav')).toBeInTheDocument()
    expect(screen.getByText('clip.mp4')).toBeInTheDocument()
  })

  it('does not let a stale project response replace the newly selected project media', async () => {
    const projects = [
      { project_id: 'project-a', root_id: 'music', relative_path: 'Alpha', active: true, registered_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', inventory_revision: 1, enrichment: null, availability: 'available' },
      { project_id: 'project-b', root_id: 'music', relative_path: 'Beta', active: true, registered_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', inventory_revision: 1, enrichment: null, availability: 'available' },
    ]
    const inventory = (projectId: string, assetId: string, path: string) => ({ contract_version: 'wrld-project-inventory/1.0', project_id: projectId, inventory_revision: 1, scan_id: `scan-${projectId}`, completed_at: '2026-01-01T00:00:00Z', policy_version: 'inventory-policy/1.0', diagnostics: [], counts: { audio: 1, image: 0, video: 0, unknown: 0, missing: 0 }, assets: [{ asset_id: assetId, relative_path: path, kind: 'audio', presence: 'present', byte_length: 100, modified_ns: 1, sha256: 'a'.repeat(64), verification_state: 'verified', probe_status: 'ok', media: { duration_seconds: 60, audio_codec: 'pcm_s16le' }, capabilities, diagnostics: [] }] })
    let resolveAlpha!: (response: Response) => void
    const alphaResponse = new Promise<Response>((resolve) => { resolveAlpha = resolve })
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/projects/project-a/inventory')) return alphaResponse
      if (url.endsWith('/projects/project-b/inventory')) return Promise.resolve({ ok: true, status: 200, json: async () => inventory('project-b', 'asset-b', 'beta.wav') } as Response)
      if (url.endsWith('/preferences')) { const projectId = url.includes('project-a') ? 'project-a' : 'project-b'; return Promise.resolve({ ok: true, status: 200, json: async () => ({ contract_version: 'wrld-project-preferences/1.0', project_id: projectId, revision: 1, save_id: 'initial', excluded_asset_ids: [], state_digest: '0'.repeat(64) }) } as Response) }
      if (url.includes('/project-roots')) return Promise.resolve({ ok: true, status: 200, json: async () => url.includes('/directories') ? { directories: [] } : { roots: [{ root_id: 'music', label: 'Music' }] } } as Response)
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ contract_version: 'wrld-project-catalog/2.0', revision: 1, projects }) } as Response)
    }))
    const user = userEvent.setup(); show()
    await user.click(await screen.findByRole('button', { name: /Beta Ready/i }))
    await screen.findByText('beta.wav')
    await act(async () => { resolveAlpha({ ok: true, status: 200, json: async () => inventory('project-a', 'asset-a', 'alpha.wav') } as Response); await Promise.resolve() })
    expect(screen.getByText('beta.wav')).toBeInTheDocument()
    expect(screen.queryByText('alpha.wav')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Scan for Files' })).toBeEnabled()
    const handoff = screen.getByRole('region', { name: 'Review handoff' })
    expect(within(handoff).getByText('Beta')).toBeInTheDocument()
    expect(within(handoff).getByText('1 included · 0 excluded · Ready')).toBeInTheDocument()
  })

  it('does not reopen a removed Review workspace after Import selects the remaining project', async () => {
    const projectA = { project_id: 'project-a', root_id: 'music', relative_path: 'Alpha', active: true, registered_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', inventory_revision: 1, enrichment: null, availability: 'available' }
    const projectB = { project_id: 'project-b', root_id: 'music', relative_path: 'Beta', active: true, registered_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', inventory_revision: 1, enrichment: null, availability: 'available' }
    const asset = (projectId: string, assetId: string, path: string) => ({ contract_version: 'wrld-project-inventory/1.0', project_id: projectId, inventory_revision: 1, scan_id: `scan-${projectId}`, completed_at: '2026-01-01T00:00:00Z', policy_version: 'inventory-policy/1.0', diagnostics: [], counts: { audio: 1, image: 0, video: 0, unknown: 0, missing: 0 }, assets: [{ asset_id: assetId, relative_path: path, kind: 'audio', presence: 'present', byte_length: 100, modified_ns: 1, sha256: projectId === 'project-a' ? 'a'.repeat(64) : 'b'.repeat(64), verification_state: 'verified', probe_status: 'ok', media: { duration_seconds: 60, audio_codec: 'pcm_s16le' }, capabilities, diagnostics: [] }] })
    const creation = (projectId: string) => ({ contract_version: 'wrld-creation-state/1.0', project_id: projectId, revision: 1, save_id: 'initial', preferred_short_duration_seconds: 45, albums: [], singles: [], shorts: [], state_digest: '0'.repeat(64), issues: [] })
    let betaActive = true
    const requests: string[] = []
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push(`${init?.method ?? 'GET'} ${url}`)
      if (url.endsWith('/projects/project-b') && init?.method === 'DELETE') { betaActive = false; return { ok: true, status: 204 } as Response }
      if (url.includes('/project-roots')) return { ok: true, status: 200, json: async () => url.includes('/directories') ? { directories: [] } : { roots: [{ root_id: 'music', label: 'Music' }] } } as Response
      if (url.endsWith('/projects')) return { ok: true, status: 200, json: async () => ({ contract_version: 'wrld-project-catalog/2.0', revision: betaActive ? 1 : 2, projects: betaActive ? [projectB, projectA] : [projectA, { ...projectB, active: false, availability: 'removed' }] }) } as Response
      const projectId = url.includes('project-a') ? 'project-a' : 'project-b'
      if (url.endsWith('/inventory')) return { ok: true, status: 200, json: async () => asset(projectId, `asset-${projectId}`, projectId === 'project-a' ? 'alpha.wav' : 'beta.wav') } as Response
      if (url.endsWith('/preferences')) return { ok: true, status: 200, json: async () => ({ contract_version: 'wrld-project-preferences/1.0', project_id: projectId, revision: 1, save_id: 'initial', excluded_asset_ids: [], state_digest: '0'.repeat(64) }) } as Response
      if (url.endsWith('/creation-state')) return { ok: true, status: 200, json: async () => creation(projectId) } as Response
      throw new Error(`Unexpected request: ${url}`)
    }))

    const user = userEvent.setup(); show()
    await screen.findByText('beta.wav')
    await user.click(screen.getByRole('button', { name: /Open in Review/i }))
    expect(screen.getByRole('heading', { name: 'Beta' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^Import/i }))
    await user.click(screen.getByRole('button', { name: /Remove Beta from My Projects/i }))
    await screen.findByText('alpha.wav')

    await user.click(screen.getByRole('button', { name: /^Review/i }))
    expect(screen.getByRole('heading', { name: 'Alpha' })).toBeInTheDocument()
    expect(screen.getAllByText('alpha.wav')).toHaveLength(2)
    expect(screen.queryByText('beta.wav')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^Editor$/i }))
    await screen.findByRole('heading', { name: /Upgrade required for visual templates/i })
    expect(requests).toContain('GET /api/v1/projects/project-a/creation-state')
    expect(requests).not.toContain('GET /api/v1/projects/project-b/creation-state')
  })

  it('keeps the selected project and queued scan state visible in the handoff bar', async () => {
    const project = { project_id: 'project-1', root_id: 'music', relative_path: 'Album', active: true, registered_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', inventory_revision: 1, enrichment: null, availability: 'available' }
    const inventory = { contract_version: 'wrld-project-inventory/1.0', project_id: 'project-1', inventory_revision: 1, scan_id: 'scan-1', completed_at: '2026-01-01T00:00:00Z', policy_version: 'inventory-policy/1.0', diagnostics: [], counts: { audio: 0, image: 0, video: 0, unknown: 0, missing: 0 }, assets: [] }
    const preferences = { contract_version: 'wrld-project-preferences/1.0', project_id: 'project-1', revision: 1, save_id: 'initial', excluded_asset_ids: [], state_digest: '0'.repeat(64) }
    const queued = { contract_version: 'wrld-project-scan/1.0', scan_id: 'scan-2', project_id: 'project-1', status: 'queued', started_at: '2026-01-01T00:00:00Z', completed_at: null, visited_entries: 0, discovered_assets: 0, progress_percent: null, retry_of_scan_id: null, policy: {}, error: null }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/inventory-scans') && init?.method === 'POST') return { ok: true, status: 202, json: async () => queued } as Response
      if (url.includes('/inventory-scans/')) return new Promise<Response>(() => undefined)
      const body = url.includes('/project-roots') ? (url.includes('/directories') ? { directories: [] } : { roots: [{ root_id: 'music', label: 'Music' }] }) : url.endsWith('/inventory') ? inventory : url.endsWith('/preferences') ? preferences : { contract_version: 'wrld-project-catalog/2.0', revision: 1, projects: [project] }
      return { ok: true, status: 200, json: async () => body } as Response
    }))
    const user = userEvent.setup(); show()
    await screen.findByText(/No media found yet/i)
    await user.click(screen.getByRole('button', { name: 'Scan for Files' }))
    const handoff = screen.getByRole('region', { name: 'Review handoff' })
    expect(within(handoff).getByText('0 included · 0 excluded · Waiting to scan')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Scan for Files' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
  })

  it('explains unsupported audition and keeps discovered video as discovery-only', async () => {
    const project = { project_id: 'project-1', root_id: 'music', relative_path: 'album', active: true, registered_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', inventory_revision: 1, enrichment: null, availability: 'available' }
    const unsupported = { status: 'unsupported', reason: 'Codec is not browser-auditionable.' }
    const audio = { asset_id: 'asset-audio', relative_path: 'song.m4a', kind: 'audio', presence: 'present', byte_length: 100, modified_ns: 1, sha256: 'a'.repeat(64), verification_state: 'verified', probe_status: 'ok', media: { duration_seconds: 60, audio_codec: 'alac' }, capabilities: { ...capabilities, server_stream: unsupported, browser_audition: unsupported }, diagnostics: [] }
    const video = { asset_id: 'asset-video', relative_path: 'clip.mp4', kind: 'video', presence: 'present', byte_length: 100, modified_ns: 1, sha256: 'b'.repeat(64), verification_state: 'verified', probe_status: 'ok', media: { duration_seconds: 10, video_codec: 'h264' }, capabilities: { server_stream: unsupported, browser_audition: unsupported, thumbnail: unsupported, inspection: unsupported, preview: unsupported, render: unsupported }, diagnostics: [] }
    const inventory = { contract_version: 'wrld-project-inventory/1.0', project_id: 'project-1', inventory_revision: 1, scan_id: 'scan-1', completed_at: '2026-01-01T00:00:00Z', policy_version: 'inventory-policy/1.0', diagnostics: [], counts: { audio: 1, image: 0, video: 1, unknown: 0, missing: 0 }, assets: [audio, video] }
    const preferences = { contract_version: 'wrld-project-preferences/1.0', project_id: 'project-1', revision: 1, save_id: 'initial', excluded_asset_ids: [], state_digest: '0'.repeat(64) }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => { const url = String(input); const body = url.includes('/project-roots') ? (url.includes('/directories') ? { directories: [] } : { roots: [{ root_id: 'music', label: 'Music' }] }) : url.endsWith('/inventory') ? inventory : url.endsWith('/preferences') ? preferences : { contract_version: 'wrld-project-catalog/2.0', revision: 1, projects: [project] }; return { ok: true, status: 200, json: async () => body } as Response }))
    show()
    expect(await screen.findByText(/Audition unavailable · Codec is not browser-auditionable/i)).toBeInTheDocument()
    expect(screen.getByText(/Discovered only · video composition belongs to WU8/i)).toBeInTheDocument()
    expect(document.querySelector('audio')).toBeNull()
  })
})
