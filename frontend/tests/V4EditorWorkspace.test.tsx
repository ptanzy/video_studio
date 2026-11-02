import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CreationStateV3, CreationStateV4, ReviewWorkspace, VisualTemplate } from '../src/api/types'
import { StudioProvider } from '../src/app/state'
import { EditorWorkspace } from '../src/features/review/EditorWorkspace'
import { configurationFromTemplate } from '../src/features/review/creationV4'

const support = { status: 'supported' as const, reason: 'test' }
const capabilities = { server_stream: support, browser_audition: support, thumbnail: support, inspection: support, preview: support, render: support }
const workspace: ReviewWorkspace = {
  projectId: 'project-1', sourceMode: 'inventory', name: 'Project', artworkLabel: '',
  assets: [
    { asset_id: 'audio-a', relative_path: 'song.wav', kind: 'audio', presence: 'present', byte_length: 10, modified_ns: 1, sha256: 'a'.repeat(64), verification_state: 'verified', probe_status: 'ok', media: { duration_seconds: 90 }, capabilities, diagnostics: [] },
    { asset_id: 'image-a', relative_path: 'cover.png', kind: 'image', presence: 'present', byte_length: 10, modified_ns: 1, sha256: 'b'.repeat(64), verification_state: 'verified', probe_status: 'ok', media: { width: 1000, height: 1000 }, capabilities, diagnostics: [] },
  ], tracks: [],
}
const template = (id: string, label: string, aspect: '16:9' | '9:16', focal = 0.5): VisualTemplate => ({
  visual_template_id: id, label, canvas: { aspect_ratio: aspect }, background_image: null,
  geometry: { fit_mode: 'contain', focal_x: focal, focal_y: 0.5 }, camera: { mode: 'static', max_zoom: 1.04 },
  visualizer: { enabled: false, bar_count: 24, opacity: 0.65 }, progress: { enabled: false }, color_treatment: { mode: 'none' },
})
const v4 = (): CreationStateV4 => {
  const album = template('family-album', 'Family album', '16:9')
  const single = template('family-single', 'Family single', '16:9')
  const short = template('family-short', 'Family short', '9:16')
  const standalone = template('standalone-short', 'Standalone short', '9:16', 0.25)
  return {
    contract_version: 'wrld-creation-state/4.0', project_id: 'project-1', revision: 4, save_id: 'save-4', preferred_short_duration_seconds: 45,
    visual_templates: [album, single, short, standalone], visual_template_families: [{ visual_template_family_id: 'family-a', name: 'Family A', members: { album_visual_template_id: album.visual_template_id, single_visual_template_id: single.visual_template_id, short_visual_template_id: short.visual_template_id } }],
    albums: [{ album_plan_id: 'album-a', label: 'Album A', status: 'active', assignments: [], visual_configuration: configurationFromTemplate(album), source_visual_template_id: album.visual_template_id }],
    singles: [{ single_id: 'single-a', asset_id: 'audio-a', expected_sha256: 'a'.repeat(64), status: 'active', customized: false, approved: true, settings: {}, visual_configuration: configurationFromTemplate(single), source_visual_template_id: single.visual_template_id }],
    shorts: [
      { short_id: 'short-a', asset_id: 'audio-a', expected_sha256: 'a'.repeat(64), status: 'active', start_sample: 0, sample_count: 2_160_000, origin: 'manual', review_required: false, customized: false, approved: true, settings: {}, visual_configuration: configurationFromTemplate(short), source_visual_template_id: short.visual_template_id },
      { short_id: 'short-b', asset_id: 'audio-a', expected_sha256: 'a'.repeat(64), status: 'active', start_sample: 0, sample_count: 2_160_000, origin: 'manual', review_required: false, customized: false, approved: true, settings: {}, visual_configuration: configurationFromTemplate(short), source_visual_template_id: short.visual_template_id },
    ], state_digest: '0'.repeat(64), issues: [],
  }
}
const v3 = (): CreationStateV3 => {
  const source = v4()
  const legacy = (item: object, templateId: string | null) => { const value = structuredClone(item) as Record<string, unknown>; delete value.visual_configuration; delete value.source_visual_template_id; value.visual_template_id = templateId; return value }
  return {
    contract_version: 'wrld-creation-state/3.0', project_id: source.project_id, revision: 3, save_id: 'save-3', preferred_short_duration_seconds: 45,
    visual_templates: source.visual_templates, visual_template_families: source.visual_template_families,
    albums: source.albums.map((item) => legacy(item, item.source_visual_template_id)) as unknown as CreationStateV3['albums'],
    singles: source.singles.map((item) => legacy(item, item.source_visual_template_id)) as unknown as CreationStateV3['singles'],
    shorts: source.shorts.map((item) => legacy(item, item.source_visual_template_id)) as unknown as CreationStateV3['shorts'],
    state_digest: '0'.repeat(64), issues: [],
  }
}
const response = (status: number, body: unknown) => ({ ok: status >= 200 && status < 300, status, json: async () => body }) as Response

afterEach(() => vi.restoreAllMocks())

describe('Creation v4 Editor workflow', () => {
  it('edits and saves one Short without changing another Short or its reusable template', async () => {
    let stored = v4(); const originalTemplate = structuredClone(stored.visual_templates.find((item) => item.visual_template_id === 'family-short'))
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const request = JSON.parse(String(init.body)) as { state: CreationStateV4; save_id: string }
        stored = { ...request.state, revision: 5, save_id: request.save_id, state_digest: '5'.repeat(64) }
      }
      return response(200, structuredClone(stored))
    }))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await user.click(await screen.findByRole('button', { name: 'Shorts' }))
    expect(screen.queryByText(/shared pixel changes/i)).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Composition focal X'), { target: { value: '0.8' } })
    await user.click(screen.getByRole('button', { name: 'Undo' }))
    expect(screen.getByLabelText('Composition focal X')).toHaveValue(0.5)
    await user.click(screen.getByRole('button', { name: 'Redo' }))
    expect(screen.getByLabelText('Composition focal X')).toHaveValue(0.8)
    await user.click(screen.getByRole('button', { name: /Save editor draft/i }))
    await waitFor(() => expect(stored.revision).toBe(5))
    expect(stored.shorts[0]).toMatchObject({ approved: false, customized: true, visual_configuration: { geometry: { focal_x: 0.8 } } })
    expect(stored.shorts[1]).toMatchObject({ approved: true, customized: false, visual_configuration: { geometry: { focal_x: 0.5 } } })
    expect(stored.visual_templates.find((item) => item.visual_template_id === 'family-short')).toEqual(originalTemplate)
  })

  it('keeps selection separate from Apply and copies a standalone template only after confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.stubGlobal('fetch', vi.fn(async () => response(200, v4())))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await user.click(await screen.findByRole('button', { name: 'Shorts' }))
    await user.selectOptions(screen.getByLabelText('Template to apply'), 'standalone-short')
    expect(screen.getByLabelText('Composition focal X')).toHaveValue(0.5)
    await user.click(screen.getByRole('button', { name: 'Apply Template' }))
    expect(screen.getByLabelText('Composition focal X')).toHaveValue(0.25)
    expect(screen.getAllByText('standalone-short').length).toBeGreaterThan(0)
  })

  it('rejects Apply when a template depends on an unavailable project image', async () => {
    const state = v4(); state.visual_templates.find((item) => item.visual_template_id === 'standalone-short')!.background_image = { asset_id: 'missing-image', expected_sha256: 'f'.repeat(64) }
    vi.stubGlobal('fetch', vi.fn(async () => response(200, state)))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await user.click(await screen.findByRole('button', { name: 'Shorts' }))
    await user.selectOptions(screen.getByLabelText('Template to apply'), 'standalone-short')
    await user.click(screen.getByRole('button', { name: 'Apply Template' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/not a currently included, present, supported project image/i)
    expect(screen.getByLabelText('Composition focal X')).toHaveValue(0.5)
  })

  it('exposes a searchable family/standalone library and independent template controls', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response(200, v4())))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await screen.findByText('Template Library')
    await user.type(screen.getByLabelText('Search template library'), 'Standalone short')
    await user.click(screen.getByRole('button', { name: /Standalone short/i }))
    expect(screen.getByText('Editing reusable template preset')).toBeInTheDocument()
    expect(screen.getByLabelText('Template focal X')).toHaveValue(0.25)
    expect(screen.getByText(/Composition visuals will not change/i)).toBeInTheDocument()
  })

  it('preserves pending v4 edits after an optimistic revision conflict', async () => {
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => init?.method === 'PUT'
      ? response(409, { error: { code: 'REVISION_CONFLICT', message: 'A newer revision exists.', details: { current_revision: 5 } } })
      : response(200, v4())))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await user.click(await screen.findByRole('button', { name: 'Shorts' }))
    fireEvent.change(screen.getByLabelText('Composition focal X'), { target: { value: '0.9' } })
    await user.click(screen.getByRole('button', { name: /Save editor draft/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('A newer revision exists.')
    expect(screen.getByLabelText('Composition focal X')).toHaveValue(0.9)
    expect(screen.getByRole('button', { name: /Save editor draft/i })).toBeEnabled()
  })
})

describe('Creation v3 explicit upgrade UI', () => {
  it('shows a complete preflight and upgrades only after explicit confirmation and Save', async () => {
    let stored: CreationStateV3 | CreationStateV4 = v3()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const request = JSON.parse(String(init.body)) as { state: CreationStateV4; save_id: string }
        stored = { ...request.state, revision: 4, save_id: request.save_id, state_digest: '4'.repeat(64) }
      }
      return response(200, structuredClone(stored))
    }))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await user.click(await screen.findByText('Creation v4 upgrade available'))
    expect(screen.getByText(/Upgrade copies each resolved template/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Upgrade to Creation v4' }))
    await waitFor(() => expect(stored.contract_version).toBe('wrld-creation-state/4.0'))
    expect(await screen.findByText('Composition-owned Editor · Creation v4')).toBeInTheDocument()
  })

  it('blocks lossless migration and offers separate compatible-template remediation for null references', async () => {
    const state = v3(); state.shorts[0].visual_template_id = null
    vi.stubGlobal('fetch', vi.fn(async () => response(200, structuredClone(state))))
    const user = userEvent.setup(); render(<StudioProvider><EditorWorkspace workspace={workspace}/></StudioProvider>)
    await user.click(await screen.findByText('Creation v4 upgrade available'))
    expect(screen.getByText(/No authoritative visual settings/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upgrade to Creation v4' })).toBeDisabled()
    expect(screen.getByLabelText('Remediation template for short:short-a')).toBeInTheDocument()
  })
})
