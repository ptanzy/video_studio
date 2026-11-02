import { ArrowLeft, CheckCircle2, Clock3, FileText, LockKeyhole, Radio, ShieldAlert } from 'lucide-react'
import { useStudio } from '../../app/state'

export const FuturePage = ({ kind }: { kind: 'metadata' | 'render' }) => {
  const { dispatch } = useStudio()
  const metadata = kind === 'metadata'
  const cards = metadata
    ? [['Canonical source', 'Album and track facts remain read-only.', CheckCircle2], ['Draft review', 'Future WU5-owned publishing text and chapters.', Clock3], ['Approval', 'Separate human approval from saving.', ShieldAlert]] as const
    : [['Preflight', 'Resolve exact target, profile, and source state.', ShieldAlert], ['Progress', 'Existing worker phases, cancellation, and recovery.', Clock3], ['Artifacts', 'Only verified outputs and technical reports.', CheckCircle2]] as const
  return <div className="future-page">
    <section className="page-heading"><div><span className="kicker">{metadata ? '03 · METADATA' : '04 · RENDER'}</span><h1>{metadata ? 'Publishing metadata' : 'Render & batch operations'}</h1><p>{metadata ? 'Planned WU5 workflow for titles, descriptions, chapters, and approval.' : 'Planned WU6 workflow for verified exports, queueing, progress, and artifacts.'}</p></div><span className="future-chip"><LockKeyhole size={15} /> Future work unit</span></section>
    <div className="future-hero panel"><div className="future-icon">{metadata ? <FileText size={34} /> : <Radio size={34} />}</div><span className="eyebrow">PREVIEW OF INTENDED STRUCTURE</span><h2>{metadata ? 'Metadata is not implemented in WU4' : 'Rendering is not controlled from this UI yet'}</h2><p>This screen is intentionally non-operational. It communicates the planned information architecture without generating data, starting jobs, or presenting simulated success.</p><button onClick={() => dispatch({ type: 'navigate', route: 'review' })}><ArrowLeft size={16} /> Return to Review</button></div>
    <div className="future-grid">{cards.map(([title, copy, Icon]) => <div className="panel future-card" key={title}><Icon size={21} /><h3>{title}</h3><p>{copy}</p><span>Not available in Phase 2A</span></div>)}</div>
  </div>
}
