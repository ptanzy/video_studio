import { AlertTriangle, CheckCircle2, Clapperboard, RefreshCw, Square } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  cancelCreationRender, creationRenderArtifactUrl, loadCreationRenderJobs,
  loadCreationRenderResult, loadCreationRenderTargets, preflightCreationRender, preflightCreationRenderRecovery, submitCreationRender, submitCreationRenderRecovery,
} from '../../api/client'
import type { CreationRenderJob, CreationRenderPreflight, CreationRenderRecoveryPreflight, CreationRenderRecoveryRequest, CreationRenderRequest, CreationRenderResult, CreationRenderTargets } from '../../api/types'
import { useStudio } from '../../app/state'

type TargetEntry = CreationRenderTargets['targets'][number]
const terminal = new Set<CreationRenderJob['state']>(['cancelled', 'failed', 'succeeded'])
const message = (error: unknown) => error instanceof Error ? error.message : 'The render operation failed.'
const technicalDetails = (details: Record<string, unknown>) => Object.keys(details).length ? JSON.stringify(details, (_key, value: unknown) => {
  if (typeof value !== 'string') return value
  return value.replace(/[A-Za-z]:[\\/][^\r\n"']+/g, '<path>').replace(/\\\\[^\r\n"']+/g, '<path>')
}, 2) : null

export const RenderWorkspace = () => {
  const { state } = useStudio()
  const projectId = state.selectedAlbumId
  const [targets, setTargets] = useState<CreationRenderTargets | null>(null)
  const [jobs, setJobs] = useState<CreationRenderJob[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [preflight, setPreflight] = useState<CreationRenderPreflight | null>(null)
  const [result, setResult] = useState<CreationRenderResult | null>(null)
  const [recovery, setRecovery] = useState<{ job: CreationRenderJob; preflight: CreationRenderRecoveryPreflight } | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')

  const load = useCallback(async (signal?: AbortSignal) => {
    if (!projectId) return
    const [nextTargets, nextJobs] = await Promise.all([loadCreationRenderTargets(projectId, signal), loadCreationRenderJobs(projectId, signal)])
    if (signal?.aborted) return
    setTargets(nextTargets); setJobs(nextJobs)
    setSelectedId((current) => nextTargets.targets.some((entry) => entry.target.composition_id === current) ? current : nextTargets.targets.find((entry) => entry.status === 'active')?.target.composition_id ?? nextTargets.targets[0]?.target.composition_id ?? '')
  }, [projectId])

  useEffect(() => {
    const controller = new AbortController()
    setTargets(null); setJobs([]); setSelectedId(''); setPreflight(null); setResult(null); setRecovery(null); setNotice('')
    if (projectId) load(controller.signal).catch((error: unknown) => { if (!controller.signal.aborted) setNotice(message(error)) })
    return () => controller.abort()
  }, [load, projectId])

  useEffect(() => {
    if (!projectId || !jobs.some((job) => !terminal.has(job.state))) return
    const timer = window.setInterval(() => load().catch((error: unknown) => setNotice(message(error))), 1000)
    return () => window.clearInterval(timer)
  }, [jobs, load, projectId])

  const selected = targets?.targets.find((entry) => entry.target.composition_id === selectedId) ?? null
  const selectedJobs = useMemo(() => jobs.filter((job) => job.target.composition_id === selectedId), [jobs, selectedId])
  const basis = targets?.creation_basis
  const request = (entry: TargetEntry, mode: CreationRenderRequest['mode'], approved?: CreationRenderPreflight): CreationRenderRequest => ({
    contract_version: 'wrld-creation-render-request/1.0', mode, target: entry.target,
    expected_creation_revision: basis?.revision ?? 0, expected_creation_state_digest: basis?.state_digest ?? '',
    profile_id: entry.profile_id, expected_plan_fingerprint: mode === 'submit' ? approved?.plan?.plan_fingerprint ?? null : null,
    submission_id: mode === 'submit' ? crypto.randomUUID() : null,
    output_action: approved?.existing_artifact && approved.diagnostics.some((item) => item.code === 'OUTPUT_EXISTS') ? 'replace_verified' : 'reuse_verified_or_fail',
    replacement: approved?.existing_artifact && approved.diagnostics.some((item) => item.code === 'OUTPUT_EXISTS') ? { artifact_id: approved.existing_artifact.artifact_id, expected_sha256: approved.existing_artifact.sha256, expected_report_revision: approved.report_revision } : null,
  })

  const check = async (authorizeReplacement = false) => {
    if (!selected) return
    setBusy(true); setNotice(''); setResult(null)
    try {
      const receipt = authorizeReplacement ? preflight ?? undefined : undefined
      const next = await preflightCreationRender(projectId, request(selected, 'preflight', receipt))
      setPreflight(next)
      setNotice(next.status === 'ready' ? 'Preflight ready.' : next.status === 'replacement_required' ? 'A different verified output exists. Replacement requires explicit authorization.' : 'Preflight is blocked. Review the diagnostics below.')
    } catch (error) { setNotice(message(error)) }
    finally { setBusy(false) }
  }

  const submit = async () => {
    if (!selected || !preflight?.plan || preflight.status !== 'ready') return
    setBusy(true); setNotice('')
    try { const job = await submitCreationRender(projectId, request(selected, 'submit', preflight)); setJobs((items) => [job, ...items.filter((item) => item.job_id !== job.job_id)]); setNotice(`Render ${job.state}.`) }
    catch (error) { setNotice(message(error)) }
    finally { setBusy(false) }
  }

  const showResult = async (job: CreationRenderJob) => {
    try { setResult(await loadCreationRenderResult(projectId, job.job_id)); setNotice('Render result loaded.') }
    catch (error) { setNotice(message(error)) }
  }

  const cancel = async (job: CreationRenderJob) => {
    try { const next = await cancelCreationRender(projectId, job.job_id); setJobs((items) => items.map((item) => item.job_id === next.job_id ? next : item)); setNotice(`Render ${next.state}.`) }
    catch (error) { setNotice(message(error)) }
  }

  const recoveryRequest = (job: CreationRenderJob, mode: CreationRenderRecoveryRequest['mode'], approved?: CreationRenderRecoveryPreflight): CreationRenderRecoveryRequest => ({
    contract_version: 'wrld-creation-render-recovery-request/1.0', mode, target: job.target,
    failed_job_id: job.job_id, failed_attempt_id: job.attempt_id,
    expected_creation_revision: basis?.revision ?? 0, expected_creation_state_digest: basis?.state_digest ?? '', profile_id: selected?.profile_id ?? 'wrld-album-1080p30-v1',
    expected_recovery_fingerprint: mode === 'submit' ? approved?.recovery_fingerprint ?? null : null,
    submission_id: mode === 'submit' ? crypto.randomUUID() : null,
    output_action: approved?.existing_artifact ? 'replace_verified' : 'reuse_verified_or_fail',
    replacement: approved?.existing_artifact ? { artifact_id: approved.existing_artifact.artifact_id, expected_sha256: approved.existing_artifact.sha256, expected_report_revision: approved.report_revision } : null,
  })

  const assessRecovery = async (job: CreationRenderJob) => {
    setBusy(true); setNotice(''); setRecovery(null)
    try { const next = await preflightCreationRenderRecovery(projectId, recoveryRequest(job, 'preflight')); setRecovery({ job, preflight: next }); setNotice(next.status === 'ready' ? 'Staged recovery is ready for explicit authorization.' : 'Staged recovery is not eligible. Review the diagnostics below.') }
    catch (error) { setNotice(message(error)) }
    finally { setBusy(false) }
  }

  const authorizeRecovery = async () => {
    if (!recovery || recovery.preflight.status !== 'ready' || !recovery.preflight.recovery_fingerprint) return
    setBusy(true); setNotice('')
    try { const job = await submitCreationRenderRecovery(projectId, recoveryRequest(recovery.job, 'submit', recovery.preflight)); setJobs((items) => [job, ...items.filter((item) => item.job_id !== job.job_id)]); setRecovery(null); setNotice(`Recovery ${job.state}. Encoding will not run.`) }
    catch (error) { setNotice(message(error)) }
    finally { setBusy(false) }
  }

  if (!projectId) return <section className="panel render-empty"><h2>Select a project in Import</h2><p>Rendering is project-scoped and requires an active Creation v4 workspace.</p></section>
  if (!targets) return <section className="panel render-empty"><h2>Loading render workspace…</h2>{notice && <p role="alert">{notice}</p>}</section>

  return <section>
    <header className="page-heading"><div><span className="kicker">WU6 · Creation rendering</span><h1>Render</h1><p>Verified Album, Single, and Short videos from Creation v4. Publishing metadata is not used.</p></div><button onClick={() => void load().catch((error: unknown) => setNotice(message(error)))}><RefreshCw size={15}/> Refresh</button></header>
    {notice && <p className="render-notice" role="status">{notice}</p>}
    <div className="render-layout">
      <aside className="panel render-targets"><div className="panel-title"><div><span className="eyebrow">Compositions</span><h2>Render targets</h2></div><span>{targets.targets.length}</span></div>{targets.targets.map((entry) => <button key={`${entry.target.kind}:${entry.target.composition_id}`} className={selectedId === entry.target.composition_id ? 'selected' : ''} onClick={() => { setSelectedId(entry.target.composition_id); setPreflight(null); setResult(null); setRecovery(null) }}><strong>{entry.label}</strong><small>{entry.target.kind} · {entry.status}</small>{entry.latest_artifact && <em>Verified output</em>}</button>)}</aside>
      <main className="panel render-main">
        {!selected ? <div className="render-empty"><h2>No render targets</h2><p>Create an active composition in Review first.</p></div> : <>
          <div className="panel-title"><div><span className="eyebrow">Selected composition</span><h2>{selected.label}</h2></div><span>{selected.profile_id}</span></div>
          {selected.status === 'archived' ? <div className="render-blocked"><AlertTriangle size={18}/><div><strong>Archived compositions cannot render.</strong><p>Existing verified artifacts remain available in job history.</p></div></div> : <div className="render-actions"><button className="primary" disabled={busy} onClick={() => void check(false)}>Run preflight</button>{preflight?.status === 'replacement_required' && <button className="danger-action" disabled={busy} onClick={() => void check(true)}>Authorize verified-output replacement</button>}<button disabled={busy || preflight?.status !== 'ready' || !preflight.plan} onClick={() => void submit()}><Clapperboard size={14}/> Start render</button></div>}
          {preflight && <section className={`render-preflight ${preflight.status}`}><h3>Preflight · {preflight.status.replace('_', ' ')}</h3>{preflight.plan && <dl><div><dt>Output</dt><dd>{preflight.plan.output.relative_path}</dd></div><div><dt>Duration</dt><dd>{preflight.plan.timeline.duration_seconds.toFixed(3)} seconds</dd></div><div><dt>Plan</dt><dd><code>{preflight.plan.plan_fingerprint}</code></dd></div></dl>}{preflight.diagnostics.map((item) => <p key={`${item.code}:${item.message}`}><AlertTriangle size={14}/><span><strong>{item.code}</strong> {item.message}</span></p>)}{preflight.existing_artifact && <p><AlertTriangle size={14}/><span>Replacement moves the current verified file into private <code>output/.wrld-history</code>. Historical copies are retained and storage use can accumulate.</span></p>}</section>}
          <section className="render-jobs"><h3>Job history</h3>{!selectedJobs.length && <p>No jobs for this composition.</p>}{selectedJobs.map((job) => {
            const details = job.diagnostic ? technicalDetails(job.diagnostic.details) : null
            return <article key={job.job_id}>
              <div className="render-job-row"><div>{job.state === 'succeeded' ? <CheckCircle2 size={16}/> : job.state === 'failed' ? <AlertTriangle size={16}/> : <Clapperboard size={16}/>}<span><strong>{job.state}</strong><small>{job.phase} · {job.progress.phase_percent == null ? 'progress unavailable' : `${job.progress.phase_percent.toFixed(0)}%`}</small></span></div><div>{!terminal.has(job.state) && <button onClick={() => void cancel(job)}><Square size={12}/> Cancel</button>}{job.state === 'failed' && <button disabled={busy} onClick={() => void assessRecovery(job)}>Assess staged recovery</button>}{job.result_available && <button onClick={() => void showResult(job)}>View result</button>}</div></div>
              {job.diagnostic && <div className="render-job-diagnostic" aria-label={`Failure details for job ${job.job_id}`}><strong>{job.diagnostic.code}</strong><p>{job.diagnostic.message}</p><small>Last recorded execution phase: {job.phase}</small>{details && <pre>{details}</pre>}<small>Retry: run a fresh preflight. This attempt does not declare automatic retry safety.</small></div>}
            </article>
          })}</section>
          {recovery && <section className={`render-preflight ${recovery.preflight.status}`}><h3>Staged recovery · {recovery.preflight.status.replace('_', ' ')}</h3>{recovery.preflight.candidate && <dl><div><dt>Attempt</dt><dd>{recovery.preflight.candidate.failed_attempt_id}</dd></div><div><dt>Staged bytes</dt><dd>{recovery.preflight.candidate.staged_byte_size.toLocaleString()}</dd></div><div><dt>Digest</dt><dd><code>{recovery.preflight.candidate.staged_sha256}</code></dd></div></dl>}{recovery.preflight.diagnostics.map((item) => <p key={`${item.code}:${item.message}`}><AlertTriangle size={14}/><span><strong>{item.code}</strong> {item.message}</span></p>)}{recovery.preflight.status === 'ready' && <button className="primary" disabled={busy} onClick={() => void authorizeRecovery()}>Authorize verification and publication</button>}<p>Recovery skips encoding only. Complete decode verification and normal publication safeguards still apply.</p></section>}
          {result && <section className="render-result"><h3>Result · {result.state}</h3>{result.diagnostics.map((item) => { const details = technicalDetails(item.details); return <div className="render-result-diagnostic" key={`${item.code}:${item.message}`} role="alert"><p><strong>{item.code}</strong> {item.message}</p>{details && <pre>{details}</pre>}</div> })}{result.artifacts.map((artifact) => <a key={artifact.artifact_id} href={creationRenderArtifactUrl(projectId, artifact.artifact_id)} target="_blank" rel="noreferrer">Open verified {artifact.kind.replace('_', ' ')}</a>)}</section>}
        </>}
      </main>
    </div>
  </section>
}
