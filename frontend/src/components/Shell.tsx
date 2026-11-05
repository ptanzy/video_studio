import { Album, Clapperboard, Download, LayoutDashboard, Music2, PanelLeftClose, Settings2, Sparkles } from 'lucide-react'
import { useEffect, useRef, type KeyboardEvent, type ReactNode } from 'react'
import { useStudio, type Route } from '../app/state'

const nav: Array<{ route: Route; label: string; caption: string; icon: typeof Album }> = [
  { route: 'import', label: 'Import', caption: 'Projects & validation', icon: Download },
  { route: 'review', label: 'Review', caption: 'Tracks & Shorts', icon: LayoutDashboard },
  { route: 'metadata', label: 'Metadata', caption: 'Publishing workspace', icon: Music2 },
  { route: 'render', label: 'Render', caption: 'Creation videos', icon: Clapperboard },
]

export const Shell = ({ children }: { children: ReactNode }) => {
  const { state, dispatch, dirty, pendingGuard, requestGuarded, saveAndContinue, discardAndContinue, cancelGuard, guardLabel } = useStudio()
  const album = state.albums.find((item) => item.projectId === state.selectedAlbumId)
  const track = album?.tracks.find((item) => item.id === state.selectedTrackId)
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand-mark"><span><Sparkles size={17} /></span><div>WRLD<strong>STUDIO</strong></div></div>
      <nav aria-label="Primary navigation">
        {nav.map(({ route, label, caption, icon: Icon }) => <button
          key={route} className={`nav-item ${state.route === route ? 'active' : ''}`}
          onClick={() => requestGuarded(() => dispatch({ type: 'navigate', route }))} aria-current={state.route === route ? 'page' : undefined}
        ><Icon size={19} /><span><strong>{label}</strong><small>{caption}</small></span></button>)}
      </nav>
      <div className="sidebar-context">
        <div className="eyebrow">Active workspace</div>
        <strong>{album?.name ?? 'No project'}</strong>
        <span>{track ? `${String(track.number).padStart(2, '0')} · ${track.title}` : 'Choose a track'}</span>
      </div>
      <div className="sidebar-foot"><PanelLeftClose size={15} /><span>Local POC · Phase 2A</span><Settings2 size={15} /></div>
    </aside>
    <main className="main-area">
      <header className="context-header">
        <div><span className="context-channel">WRLD Music</span><span className="context-slash">/</span><strong>{album?.name ?? 'My Projects'}</strong></div>
        <div className="header-status"><span className={`connection-dot ${state.backendStatus}`} />{state.backendStatus === 'connected' ? 'Local project data' : state.backendStatus === 'demo' ? 'Demonstration data' : 'Backend unavailable'}{dirty && <span className="dirty-pill">Unsaved editor changes</span>}</div>
      </header>
      <div className="page-wrap">{children}</div>
    </main>
    {pendingGuard && <GuardDialog label={guardLabel} save={() => void saveAndContinue()} discard={discardAndContinue} cancel={cancelGuard}/>} 
  </div>
}

const GuardDialog = ({ label, save, discard, cancel }: { label: string; save: () => void; discard: () => void; cancel: () => void }) => {
  const dialog = useRef<HTMLDivElement>(null)
  useEffect(() => { dialog.current?.querySelector<HTMLButtonElement>('button')?.focus() }, [])
  const keyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') { event.preventDefault(); cancel(); return }
    if (event.key !== 'Tab') return
    const controls = [...(dialog.current?.querySelectorAll<HTMLElement>('button:not([disabled])') ?? [])]
    if (!controls.length) return
    const index = controls.indexOf(document.activeElement as HTMLElement)
    const next = event.shiftKey ? (index <= 0 ? controls.length - 1 : index - 1) : (index >= controls.length - 1 ? 0 : index + 1)
    event.preventDefault(); controls[next].focus()
  }
  return <div className="modal-backdrop" role="presentation"><div ref={dialog} className="dialog" role="dialog" aria-modal="true" aria-labelledby="leave-title" onKeyDown={keyboard}>
    <div className="dialog-icon"><Album size={23}/></div><h2 id="leave-title">Save {label} changes?</h2>
    <p>Your changes are not saved. Save them before continuing, discard them, or cancel navigation.</p>
    <div className="dialog-actions"><button onClick={cancel}>Cancel</button><button className="danger" onClick={discard}>Discard</button><button className="primary" onClick={save}>Save & continue</button></div>
  </div></div>
}
