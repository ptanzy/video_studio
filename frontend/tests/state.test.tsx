import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { StudioProvider, useStudio } from '../src/app/state'
import type { ImportHandoff, ReviewWorkspace } from '../src/api/types'

const workspace: ReviewWorkspace = { projectId: 'project-1', sourceMode: 'inventory', name: 'Project', artworkLabel: '', assets: [], tracks: [{ id: 'asset-a', number: 1, title: 'Song', audio: 'song.wav', audio_sha256: 'a'.repeat(64), normalized_sample_count: 48_000, durationSeconds: 1 }] }
const secondWorkspace: ReviewWorkspace = { ...workspace, projectId: 'project-2', name: 'Second project', tracks: [{ ...workspace.tracks[0], id: 'asset-b' }] }
const Probe = ({ handoff }: { handoff: ImportHandoff }) => { const { state, dispatch } = useStudio(); return <><button onClick={() => dispatch({ type: 'import-handoff', album: workspace, handoff })}>Load handoff</button><span>{state.backendMessage}</span></> }
const TabProbe = ({ handoff }: { handoff: ImportHandoff }) => { const { state, dispatch } = useStudio(); return <><button onClick={() => dispatch({ type: 'backend-loaded', albums: [workspace, secondWorkspace] })}>Load projects</button><button onClick={() => dispatch({ type: 'select-review-tab', tab: 'editor' })}>Select Editor</button><button onClick={() => dispatch({ type: 'navigate', route: 'metadata' })}>Leave Review</button><button onClick={() => dispatch({ type: 'navigate', route: 'review' })}>Return to Review</button><button onClick={() => dispatch({ type: 'select-album', albumId: secondWorkspace.projectId })}>Switch project</button><button onClick={() => dispatch({ type: 'import-handoff', album: workspace, handoff })}>New handoff</button><output aria-label="Review session state">{state.route}:{state.reviewTab}:{state.selectedAlbumId}</output></> }
const StaleProjectProbe = () => { const { state, dispatch } = useStudio(); const removedHandoff: ImportHandoff = { contract_version: 'wrld-import-handoff/2.0', project_id: secondWorkspace.projectId, inventory_revision: 1, preferences_revision: 1 }; return <><button onClick={() => dispatch({ type: 'import-handoff', album: secondWorkspace, handoff: removedHandoff })}>Open removed project</button><button onClick={() => dispatch({ type: 'select-review-tab', tab: 'editor' })}>Select removed Editor</button><button onClick={() => dispatch({ type: 'navigate', route: 'import' })}>Return to Import</button><button onClick={() => dispatch({ type: 'project-catalog-refreshed', projectIds: [workspace.projectId] })}>Refresh active catalog</button><button onClick={() => dispatch({ type: 'import-project-selected', album: workspace })}>Select current Import project</button><button onClick={() => dispatch({ type: 'navigate', route: 'review' })}>Navigate to Review</button><output aria-label="Project selection state">{state.route}:{state.reviewTab}:{state.selectedAlbumId}:{state.albums.map((item) => item.projectId).join(',')}:{state.importHandoff?.project_id ?? 'none'}</output></> }

describe('Import handoff compatibility', () => {
  it('accepts v1 as explicit session-only compatibility without treating workflow order as durable Creation state', async () => {
    const handoff: ImportHandoff = { contract_version: 'wrld-import-handoff/1.0', project_id: 'project-1', inventory_revision: 1, workflow: 'compilation', audio_assets: [{ asset_id: 'asset-a', sha256: 'a'.repeat(64) }] }
    const user = userEvent.setup(); render(<StudioProvider><Probe handoff={handoff}/></StudioProvider>)
    await user.click(screen.getByRole('button', { name: /Load handoff/i }))
    expect(screen.getByText(/Legacy v1 session handoff loaded for compatibility/i)).toHaveTextContent(/Creation state remains authoritative/i)
  })

  it('retains the Review tab for the same project and resets it on project changes and new handoffs', async () => {
    const handoff: ImportHandoff = { contract_version: 'wrld-import-handoff/2.0', project_id: 'project-1', inventory_revision: 1, preferences_revision: 1 }
    const user = userEvent.setup(); render(<StudioProvider><TabProbe handoff={handoff}/></StudioProvider>)
    await user.click(screen.getByRole('button', { name: 'Load projects' }))
    await user.click(screen.getByRole('button', { name: 'Select Editor' }))
    await user.click(screen.getByRole('button', { name: 'Leave Review' }))
    await user.click(screen.getByRole('button', { name: 'Return to Review' }))
    expect(screen.getByRole('status', { name: 'Review session state' })).toHaveTextContent('review:editor:project-1')
    await user.click(screen.getByRole('button', { name: 'Switch project' }))
    expect(screen.getByRole('status', { name: 'Review session state' })).toHaveTextContent('review:media:project-2')
    await user.click(screen.getByRole('button', { name: 'Select Editor' }))
    await user.click(screen.getByRole('button', { name: 'New handoff' }))
    expect(screen.getByRole('status', { name: 'Review session state' })).toHaveTextContent('review:media:project-1')
  })

  it('evicts a removed Review workspace and synchronizes the current Import selection before navigation', async () => {
    const user = userEvent.setup(); render(<StudioProvider><StaleProjectProbe /></StudioProvider>)
    await user.click(screen.getByRole('button', { name: 'Open removed project' }))
    await user.click(screen.getByRole('button', { name: 'Select removed Editor' }))
    await user.click(screen.getByRole('button', { name: 'Return to Import' }))
    expect(screen.getByRole('status', { name: 'Project selection state' })).toHaveTextContent('import:editor:project-2:project-2:project-2')

    await user.click(screen.getByRole('button', { name: 'Refresh active catalog' }))
    expect(screen.getByRole('status', { name: 'Project selection state' })).toHaveTextContent('import:media:::none')

    await user.click(screen.getByRole('button', { name: 'Select current Import project' }))
    await user.click(screen.getByRole('button', { name: 'Navigate to Review' }))
    expect(screen.getByRole('status', { name: 'Project selection state' })).toHaveTextContent('review:media:project-1:project-1:none')
  })
})
