import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { CreationRenderJob, CreationRenderPreflight, CreationRenderRecoveryPreflight, CreationRenderTargets } from '../src/api/types'
import { StudioProvider, useStudio } from '../src/app/state'
import { RenderWorkspace } from '../src/features/render/RenderWorkspace'

const sha = 'a'.repeat(64)
const response = (status: number, body: unknown) => ({ ok: status >= 200 && status < 300, status, headers: { get: () => 'application/json' }, url: 'http://127.0.0.1/api', json: async () => body }) as unknown as Response
const target = { kind: 'short' as const, composition_id: 'short-1' }
const artifact = { artifact_id: `artifact-${sha}`, sha256: 'b'.repeat(64) }
const targets = {
  contract_version: 'wrld-creation-render-targets/1.0', project_id: 'project-1',
  creation_basis: { contract_version: 'wrld-creation-state/4.0', revision: 4, state_digest: sha },
  targets: [{ target, label: 'Short one', status: 'active', profile_id: 'wrld-short-1080x1920p30-v1', preflight_required: true, latest_artifact: null }],
} as CreationRenderTargets
const plan = { plan_fingerprint: 'c'.repeat(64), output: { relative_path: 'output/shorts/short-1.mp4' }, timeline: { duration_seconds: 45 } }
const replacement = {
  contract_version: 'wrld-creation-render-preflight/1.0', status: 'replacement_required', request_fingerprint: sha,
  plan, diagnostics: [{ severity: 'error', code: 'OUTPUT_EXISTS', message: 'Existing output.', target, asset_id: null, details: {} }],
  existing_artifact: artifact, report_revision: 3,
} as unknown as CreationRenderPreflight
const ready = { ...replacement, status: 'ready' } as CreationRenderPreflight
const failedJob = {
  contract_version: 'wrld-creation-render-job/1.0', job_id: '11111111-1111-4111-8111-111111111111', attempt_id: '22222222-2222-4222-8222-222222222222', submission_id: '33333333-3333-4333-8333-333333333333', project_id: 'project-1', target,
  request_fingerprint: sha, plan_fingerprint: 'c'.repeat(64), state: 'failed', phase: 'probing_output',
  progress: { phase_percent: 100, processed_samples: 2160000, total_samples: 2160000, current_source: 1, total_sources: 1, elapsed_seconds: 12, eta_seconds: 0 }, queue_position: null,
  created_at: '2026-11-04T19:00:00Z', started_at: '2026-11-04T19:00:01Z', updated_at: '2026-11-04T19:01:00Z', last_heartbeat_at: '2026-11-04T19:00:59Z', finished_at: '2026-11-04T19:01:00Z', retry_of_attempt_id: null, recovery: 'none', result_available: true,
  diagnostic: { severity: 'error', code: 'RENDER_FAILED', message: 'FFprobe exceeded its time limit.', target, asset_id: null, details: { infrastructure_code: 'PROBE_TIMEOUT', reason: String.raw`Access denied: 'C:\private\state\job.json'` } },
} as unknown as CreationRenderJob
const recoveryReady = {
  contract_version: 'wrld-creation-render-recovery-preflight/1.0', status: 'ready', recovery_fingerprint: 'd'.repeat(64), plan: null,
  candidate: { contract_version: 'wrld-creation-render-recovery-candidate/1.0', project_id: 'project-1', failed_job_id: failedJob.job_id, failed_attempt_id: failedJob.attempt_id, plan_fingerprint: failedJob.plan_fingerprint, staged_sha256: 'e'.repeat(64), staged_byte_size: 1234, output_relative_path: 'output/shorts/short-1.mp4', profile_id: 'wrld-short-1080x1920p30-v1', renderer_id: 'wrld-creation-renderer', renderer_version: 'wu6-creation-renderer-1', artifact_report_revision: 0 },
  diagnostics: [], existing_artifact: null, report_revision: 0,
} as unknown as CreationRenderRecoveryPreflight

const Bootstrap = () => {
  const { dispatch } = useStudio()
  useEffect(() => { dispatch({ type: 'import-project-selected', album: { projectId: 'project-1', sourceMode: 'backend', name: 'Test album', artworkLabel: '', assets: [], tracks: [] } }); dispatch({ type: 'navigate', route: 'render' }) }, [dispatch])
  return <RenderWorkspace />
}

describe('WU6 Render workspace', () => {
  it('requires explicit replacement authorization and submits the preflighted plan', async () => {
    const posted: Array<Record<string, unknown>> = []
    let preflightCount = 0
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/render-targets')) return response(200, targets)
      if (url.endsWith('/render-jobs') && !init?.method) return response(200, [])
      if (url.endsWith('/render-preflights')) { posted.push(JSON.parse(String(init?.body))); return response(200, preflightCount++ === 0 ? replacement : ready) }
      if (url.endsWith('/render-jobs') && init?.method === 'POST') { posted.push(JSON.parse(String(init.body))); return response(202, { job_id: 'job-1', target, state: 'queued', phase: 'queued', progress: { phase_percent: null } }) }
      throw new Error(`Unexpected request ${url}`)
    }))
    const user = userEvent.setup()
    render(<StudioProvider><Bootstrap /></StudioProvider>)
    await user.click(await screen.findByRole('button', { name: /Run preflight/i }))
    expect(await screen.findByRole('button', { name: /Authorize verified-output replacement/i })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Authorize verified-output replacement/i }))
    expect(await screen.findByText(/Preflight ready/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Start render/i }))
    expect(await screen.findByText(/Render queued/i)).toBeInTheDocument()
    expect(posted[0].output_action).toBe('reuse_verified_or_fail')
    expect(posted[1]).toMatchObject({ mode: 'preflight', output_action: 'replace_verified', replacement: { artifact_id: `artifact-${sha}`, expected_report_revision: 3 } })
    expect(posted[2]).toMatchObject({ mode: 'submit', expected_plan_fingerprint: 'c'.repeat(64), output_action: 'replace_verified' })
    expect(typeof posted[2].submission_id).toBe('string')
  })

  it('lists archived targets but does not offer render admission', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/render-targets')
      ? response(200, { ...targets, targets: [{ ...targets.targets[0], status: 'archived' }] })
      : response(200, [])))
    render(<StudioProvider><Bootstrap /></StudioProvider>)
    expect(await screen.findByText(/Archived compositions cannot render/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Run preflight/i })).not.toBeInTheDocument()
  })

  it('shows durable failure diagnostics, phase, technical details, and conservative retry guidance', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/render-targets')
      ? response(200, targets)
      : response(200, [failedJob])))

    render(<StudioProvider><Bootstrap /></StudioProvider>)

    expect(await screen.findByText('RENDER_FAILED')).toBeInTheDocument()
    expect(screen.getByText('FFprobe exceeded its time limit.')).toBeInTheDocument()
    expect(screen.getByText(/Last recorded execution phase: probing_output/)).toBeInTheDocument()
    expect(screen.getByText(/PROBE_TIMEOUT/)).toBeInTheDocument()
    expect(screen.queryByText(/C:\\private/)).not.toBeInTheDocument()
    expect(screen.getByText(/<path>/)).toBeInTheDocument()
    expect(screen.getByText(/run a fresh preflight/i)).toBeInTheDocument()
    expect(screen.getByText(/does not declare automatic retry safety/i)).toBeInTheDocument()
  })

  it('requires explicit staged-recovery assessment and authorization', async () => {
    const posted: Array<Record<string, unknown>> = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/render-targets')) return response(200, targets)
      if (url.endsWith('/render-jobs') && !init?.method) return response(200, [failedJob])
      if (url.endsWith('/render-recovery-preflights')) { posted.push(JSON.parse(String(init?.body))); return response(200, recoveryReady) }
      if (url.endsWith('/render-recovery-jobs')) { posted.push(JSON.parse(String(init?.body))); return response(202, { ...failedJob, job_id: '44444444-4444-4444-8444-444444444444', attempt_id: '55555555-5555-4555-8555-555555555555', state: 'queued', phase: 'queued', diagnostic: null, result_available: false }) }
      throw new Error(`Unexpected request ${url}`)
    }))
    const user = userEvent.setup()
    render(<StudioProvider><Bootstrap /></StudioProvider>)
    await user.click(await screen.findByRole('button', { name: /Assess staged recovery/i }))
    expect(await screen.findByText(/Staged recovery is ready/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Authorize verification and publication/i }))
    expect(await screen.findByText(/Encoding will not run/i)).toBeInTheDocument()
    expect(posted[0]).toMatchObject({ mode: 'preflight', failed_job_id: failedJob.job_id, expected_recovery_fingerprint: null })
    expect(posted[1]).toMatchObject({ mode: 'submit', failed_attempt_id: failedJob.attempt_id, expected_recovery_fingerprint: 'd'.repeat(64) })
  })
})
