import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { YouTubeMetadataState } from '../src/api/types'
import { StudioProvider, useStudio } from '../src/app/state'
import { MetadataWorkspace } from '../src/features/metadata/MetadataWorkspace'

const sha = 'a'.repeat(64)
const response = (status: number, body: unknown) => ({ ok: status >= 200 && status < 300, status, json: async () => body }) as Response
const metadata = (): YouTubeMetadataState => ({
  contract_version: 'wrld-youtube-metadata-editor/1.0', project_id: 'project-1', revision: 1, save_id: 'initial', generation_version: 'wrld-youtube-metadata-draft/1.0',
  creation_basis: { contract_version: 'wrld-creation-state/4.0', revision: 3, state_digest: sha }, state_digest: sha,
  targets: [{
    target_key: 'single:single-1', target: { kind: 'single', single_id: 'single-1' }, lifecycle: 'active',
    basis: { creation_target_fingerprint: sha, source_metadata_fingerprint: sha, chapter_source_fingerprint: null }, chapters: null, approval: null,
    content: {
      title: { value: 'First Light', origin: 'generated', source_fingerprint: sha }, description: { value: 'First Light', origin: 'generated', source_fingerprint: sha },
      tags: { value: [], origin: 'generated', source_fingerprint: sha }, hashtags: { value: [], origin: 'generated', source_fingerprint: sha },
      artist_name: { value: 'WRLD', origin: 'supplied', source_fingerprint: sha }, channel_name: { value: 'WRLD', origin: 'supplied', source_fingerprint: sha },
      credits: { value: [], origin: 'generated', source_fingerprint: sha }, links: { value: [], origin: 'generated', source_fingerprint: sha },
      visibility: { value: 'private', origin: 'generated', source_fingerprint: null }, pinned_comment: { value: null, origin: 'generated', source_fingerprint: null },
      release_album_plan_id: { value: null, origin: 'generated', source_fingerprint: sha }, related_video_url: { value: null, origin: 'generated', source_fingerprint: null },
    },
  }],
})

const Bootstrap = () => {
  const { dispatch } = useStudio()
  useEffect(() => { dispatch({ type: 'import-project-selected', album: { projectId: 'project-1', sourceMode: 'backend', name: 'Test album', artworkLabel: '', assets: [], tracks: [] } }); dispatch({ type: 'navigate', route: 'metadata' }) }, [dispatch])
  return <MetadataWorkspace />
}
const show = () => render(<StudioProvider><Bootstrap /></StudioProvider>)

describe('WU5 Metadata workspace', () => {
  it('initializes explicitly from Creation v4 without importing a legacy draft', async () => {
    const document = metadata()
    const requests: Array<{ url: string; method: string }> = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); const method = init?.method ?? 'GET'; requests.push({ url, method })
      if (url.endsWith('/youtube-metadata') && method === 'GET') return response(404, { error: { code: 'METADATA_STATE_NOT_FOUND', message: 'Not initialized.' } })
      if (url.endsWith('/creation-state')) return response(200, { contract_version: 'wrld-creation-state/4.0', project_id: 'project-1', revision: 3, save_id: 'creation', preferred_short_duration_seconds: 45, visual_templates: [], visual_template_families: [], albums: [], singles: [], shorts: [], state_digest: sha, issues: [] })
      if (url.endsWith('/youtube-metadata/initialize') && method === 'POST') return response(201, document)
      throw new Error(`Unexpected request ${method} ${url}`)
    }))
    const user = userEvent.setup(); show()
    await user.click(await screen.findByRole('button', { name: /Initialize metadata/i }))
    expect(await screen.findByRole('heading', { name: /Publishing metadata/i })).toBeInTheDocument()
    expect(screen.getByText(/No legacy draft was imported/i)).toBeInTheDocument()
    expect(requests.filter((item) => item.method === 'POST')).toEqual([{ url: '/api/v1/projects/project-1/youtube-metadata/initialize', method: 'POST' }])
  })

  it('supports local undo/redo, explicit revision-safe Save, target approval, and selected export preview', async () => {
    let document = metadata()
    const calls: string[] = []
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); const method = init?.method ?? 'GET'; calls.push(`${method} ${url}`)
      if (url.endsWith('/youtube-metadata/validate')) return response(200, { contract_version: 'wrld-youtube-metadata-validation/1.0', mode: 'approval', valid: true, target_fingerprints: [{ target_key: 'single:single-1', approval_fingerprint: sha }], diagnostics: [] })
      if (url.endsWith('/youtube-metadata/export-preview')) return response(200, { contract_version: 'wrld-youtube-metadata-export-preview/1.0', editor_revision: document.revision, eligible: true, preview_fingerprint: sha, proposed_sha256: sha, predicted_export_revision: 1, existing_sha256: null, document: {}, diagnostics: [] })
      if (url.endsWith('/youtube-metadata/exports')) return response(200, { contract_version: 'wrld-youtube-metadata-export-result/1.0', path: 'output/metadata/youtube_metadata.json', sha256: sha, byte_size: 120, revision: 1, reused: false, document: {} })
      if (url.endsWith('/youtube-metadata') && method === 'PUT') { const request = JSON.parse(String(init?.body)) as { state: YouTubeMetadataState; save_id: string }; document = { ...request.state, revision: document.revision + 1, save_id: request.save_id, state_digest: 'b'.repeat(64) }; return response(200, document) }
      if (url.endsWith('/youtube-metadata')) return response(200, document)
      throw new Error(`Unexpected request ${method} ${url}`)
    }))
    const user = userEvent.setup(); show()
    const title = await screen.findByLabelText('single:single-1 title')
    fireEvent.change(title, { target: { value: 'Edited title' } })
    await user.click(screen.getByRole('button', { name: /Undo metadata change/i }))
    expect(screen.getByLabelText('single:single-1 title')).toHaveValue('First Light')
    await user.click(screen.getByRole('button', { name: /Redo metadata change/i }))
    expect(screen.getByLabelText('single:single-1 title')).toHaveValue('Edited title')
    await user.click(screen.getByRole('button', { name: /^Save$/i }))
    await screen.findByText(/Saved revision 2/i)
    await user.click(screen.getByRole('tab', { name: 'Detail' }))
    await user.click(screen.getByRole('button', { name: /Validate & approve/i }))
    expect(screen.getByText(/Approval added locally/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^Save$/i }))
    await screen.findByText(/Saved revision 3/i)
    await user.click(screen.getByRole('tab', { name: 'Table' }))
    await user.click(screen.getByLabelText(/Select single:single-1 for export/i))
    await user.click(screen.getByRole('button', { name: /Preview & export/i }))
    await waitFor(() => expect(screen.getByText(/Wrote output\/metadata\/youtube_metadata.json/i)).toBeInTheDocument())
    expect(calls).toContain('POST /api/v1/projects/project-1/youtube-metadata/export-preview')
    expect(calls).toContain('POST /api/v1/projects/project-1/youtube-metadata/exports')
  })
})
