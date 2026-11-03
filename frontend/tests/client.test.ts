import { afterEach, describe, expect, it, vi } from 'vitest'
import { loadCatalog, loadCreationState, saveCreationState } from '../src/api/client'
import type { CreationState, CreationStateV3, CreationStateV4 } from '../src/api/types'

const state = (): CreationState => ({ contract_version: 'wrld-creation-state/1.0', project_id: 'project-1', revision: 1, save_id: 'old', preferred_short_duration_seconds: 45, albums: [], singles: [], shorts: [], state_digest: '0'.repeat(64), issues: [] })
const response = (status: number, body: unknown) => ({ ok: status >= 200 && status < 300, status, json: async () => body }) as Response

afterEach(() => vi.restoreAllMocks())

describe('revision-safe save reconciliation', () => {
  it.each([
    ['v1', state()],
    ['v2', { ...state(), contract_version: 'wrld-creation-state/2.0', visual_templates: [] }],
    ['v3', { ...state(), contract_version: 'wrld-creation-state/3.0', visual_templates: [], visual_template_families: [] }],
  ] as const)('loads %s without migrating or changing its generation', async (_label, document) => {
    vi.stubGlobal('fetch', vi.fn(async () => response(200, document)))
    const loaded = await loadCreationState('project-1')
    expect(loaded.contract_version).toBe(document.contract_version)
  })

  it('loads v4 natively without migrating, downgrading, or stripping composition-owned settings', async () => {
    const v4: CreationStateV4 = { ...state(), contract_version: 'wrld-creation-state/4.0', visual_templates: [], visual_template_families: [], albums: [], singles: [], shorts: [] }
    const snapshot = structuredClone(v4)
    vi.stubGlobal('fetch', vi.fn(async () => response(200, v4)))
    await expect(loadCreationState('project-1')).resolves.toEqual(v4)
    expect(v4).toEqual(snapshot)
  })

  it('continues to reject unknown future Creation generations safely', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response(200, { ...state(), contract_version: 'wrld-creation-state/5.0' })))
    await expect(loadCreationState('project-1')).rejects.toMatchObject({ code: 'CREATION_STATE_VERSION_UNSUPPORTED', details: { contract_version: 'wrld-creation-state/5.0' } })
  })

  it('saves and reloads v3 without stripping its family registry', async () => {
    const v3: CreationStateV3 = { ...state(), contract_version: 'wrld-creation-state/3.0', visual_templates: [], visual_template_families: [{ visual_template_family_id: 'family-a', name: 'Duplicate-safe family', members: { album_visual_template_id: 'album-a', single_visual_template_id: 'single-a', short_visual_template_id: 'short-a' } }], albums: [], singles: [], shorts: [] }
    let latest = structuredClone(v3)
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const request = JSON.parse(String(init.body)) as { save_id: string; state: CreationStateV3 }
        latest = { ...request.state, revision: 2, save_id: request.save_id, state_digest: 'f'.repeat(64) }
      }
      return response(200, structuredClone(latest))
    }))
    const saved = await saveCreationState('project-1', v3)
    expect(saved.contract_version).toBe('wrld-creation-state/3.0')
    expect((saved as CreationStateV3).visual_template_families).toEqual(v3.visual_template_families)
  })

  it('saves and reloads v4 without stripping owned visuals, provenance, or families', async () => {
    const configuration = { canvas: { aspect_ratio: '9:16' as const }, background_image: null, geometry: { fit_mode: 'contain' as const, focal_x: 0.5, focal_y: 0.5 }, camera: { mode: 'static' as const, max_zoom: 1.04 }, visualizer: { enabled: false, bar_count: 24, opacity: 0.65 }, progress: { enabled: false }, color_treatment: { mode: 'none' as const } }
    const v4: CreationStateV4 = { ...state(), contract_version: 'wrld-creation-state/4.0', visual_templates: [], visual_template_families: [], albums: [], singles: [], shorts: [{ short_id: 'short-a', asset_id: 'asset-a', expected_sha256: 'a'.repeat(64), status: 'active', start_sample: 0, sample_count: 2_160_000, origin: 'manual', review_required: false, customized: true, approved: true, settings: { legacy: true }, visual_configuration: configuration, source_visual_template_id: 'historical-template' }] }
    let latest = structuredClone(v4)
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const request = JSON.parse(String(init.body)) as { save_id: string; state: CreationStateV4 }
        latest = { ...request.state, revision: 2, save_id: request.save_id, state_digest: 'f'.repeat(64) }
      }
      return response(200, structuredClone(latest))
    }))
    await expect(saveCreationState('project-1', v4)).resolves.toMatchObject({ contract_version: 'wrld-creation-state/4.0', shorts: [{ visual_configuration: configuration, source_visual_template_id: 'historical-template', approved: true }] })
  })

  it('preserves the pending v3 registry when an optimistic revision conflict wins', async () => {
    const pending: CreationStateV3 = { ...state(), contract_version: 'wrld-creation-state/3.0', visual_templates: [], visual_template_families: [], albums: [], singles: [], shorts: [] }
    const snapshot = structuredClone(pending)
    vi.stubGlobal('fetch', vi.fn(async () => response(409, { error: { code: 'REVISION_CONFLICT', message: 'A newer revision exists.', details: { current_revision: 4 } } })))
    await expect(saveCreationState('project-1', pending)).rejects.toMatchObject({ code: 'REVISION_CONFLICT', status: 409 })
    expect(pending).toEqual(snapshot)
  })

  it('confirms an indeterminate commit by save identity, candidate revision, and digest', async () => {
    let latest = state()
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const request = JSON.parse(String(init.body)) as { save_id: string }
        latest = { ...latest, revision: 2, save_id: request.save_id, state_digest: 'd'.repeat(64) }
        return response(500, { error: { code: 'COMMIT_INDETERMINATE', message: 'Outcome unknown.', details: { candidate_revision: 2, save_id: request.save_id, state_digest: 'd'.repeat(64) } } })
      }
      return response(200, latest)
    }))
    await expect(saveCreationState('project-1', state())).resolves.toEqual(latest)
  })

  it('reports an unresolved indeterminate commit without retrying the write', async () => {
    const request = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => init?.method === 'PUT'
      ? response(500, { error: { code: 'COMMIT_INDETERMINATE', message: 'Outcome unknown.', details: { candidate_revision: 2, state_digest: 'd'.repeat(64) } } })
      : response(200, state()))
    vi.stubGlobal('fetch', request)
    await expect(saveCreationState('project-1', state())).rejects.toMatchObject({ code: 'COMMIT_UNRESOLVED' })
    expect(request.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(1)
  })

  it('preserves a structured revision conflict for explicit UI recovery', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response(409, { error: { code: 'REVISION_CONFLICT', message: 'A newer revision exists.', details: { current_revision: 2 } } })))
    await expect(saveCreationState('project-1', state())).rejects.toMatchObject({ code: 'REVISION_CONFLICT', status: 409 })
  })
})

describe('API response diagnostics', () => {
  it('reports Vite HTML fallback as a proxy/backend configuration error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<!doctype html><title>WRLD</title>', { status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8' } })))
    await expect(loadCatalog()).rejects.toMatchObject({
      code: 'API_RESPONSE_INVALID',
      status: 200,
      details: { content_type: 'text/html', http_status: 200 },
    })
    await expect(loadCatalog()).rejects.toThrow(/returned HTML instead of JSON.*Restart the Vite development server/i)
  })

  it('reports malformed JSON without fabricating an empty catalog', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{not-json', { status: 200, headers: { 'Content-Type': 'application/json' } })))
    await expect(loadCatalog()).rejects.toMatchObject({ code: 'API_RESPONSE_INVALID', status: 200 })
  })
})
