import { Check, Redo2, RotateCcw, Save, Undo2 } from 'lucide-react'
import { useCallback, useEffect } from 'react'
import type { ReviewWorkspace, VisualTemplate } from '../../api/types'
import { useStudio } from '../../app/state'
import { CompositionPreview } from './CompositionPreview'
import { WaveformEditor } from './WaveformEditor'

const templateFor = (effects: ReturnType<typeof useStudio>['state']['drafts'][string]['effects']): VisualTemplate => ({
  visual_template_id: 'demonstration-template', label: 'Demonstration visual', canvas: { aspect_ratio: '9:16' }, background_image: null,
  geometry: { fit_mode: 'contain', focal_x: effects.positionX / 100, focal_y: effects.positionY / 100 },
  camera: { mode: effects.camera ? 'bounded' : 'static', max_zoom: effects.zoom },
  visualizer: { enabled: effects.bars, bar_count: effects.barCount, opacity: effects.barOpacity },
  progress: { enabled: effects.progress }, color_treatment: { mode: 'custom', hex: effects.tint, intensity: effects.tintIntensity / 100 },
})

export const DemonstrationEditor = ({ workspace }: { workspace: ReviewWorkspace }) => {
  const { state, dispatch, dirty, registerGuard } = useStudio()
  const track = workspace.tracks.find((item) => item.id === state.selectedTrackId) ?? workspace.tracks[0]
  const draft = track ? state.drafts[track.id] : undefined
  const save = useCallback(async () => { dispatch({ type: 'mark-saved' }); return true }, [dispatch])
  const discard = useCallback(() => dispatch({ type: 'discard-edits' }), [dispatch])
  useEffect(() => registerGuard({ dirty, save, discard, label: 'demonstration Editor' }), [dirty, save, discard, registerGuard])
  if (!track || !draft) return <div className="panel empty-state"><strong>No demonstration track is selected.</strong></div>
  const setRange = (start: number, end: number) => {
    const length = Math.max(0, end - start)
    const boundedStart = Math.max(0, Math.min(track.durationSeconds - Math.min(length, track.durationSeconds), start))
    dispatch({ type: 'set-range', start: Math.round(boundedStart * 10) / 10, end: Math.round(Math.min(track.durationSeconds, boundedStart + length) * 10) / 10 })
  }
  return <>
    <div className="editor-toolbar panel"><div><strong>{track.title}</strong><span>Demonstration-only local draft · no project files are changed</span></div><div className="heading-actions"><button disabled={!state.history.past.length} onClick={() => dispatch({ type: 'undo' })}><Undo2 size={16}/> Undo</button><button disabled={!state.history.future.length} onClick={() => dispatch({ type: 'redo' })}><Redo2 size={16}/> Redo</button><button className="primary" disabled={!dirty} onClick={() => dispatch({ type: 'mark-saved' })}><Save size={16}/> Save demonstration draft</button></div></div>
    <div className="review-grid">
      <aside className="panel track-rail"><div className="panel-title"><div><span className="eyebrow">Demonstration tracks</span><h2>Primary Shorts</h2></div></div><div className="rail-list">{workspace.tracks.map((item) => <button key={item.id} aria-label={`${item.title} Draft primary Short`} className={item.id === track.id ? 'selected' : ''} onClick={() => dispatch({ type: 'select-track', trackId: item.id })}><span>{String(item.number).padStart(2, '0')}</span><div><strong>{item.title}</strong><small>Draft primary Short</small></div></button>)}</div></aside>
      <main className="review-center"><div className="panel preview-panel"><CompositionPreview title={track.title} template={templateFor(draft.effects)}/></div><div className="panel" key={track.id}><WaveformEditor duration={track.durationSeconds} region={{ shortId: draft.short.shortId, start: draft.short.start, end: draft.short.end, approved: draft.short.approved, reviewRequired: draft.short.reviewRequired }} onChange={setRange}/><div className="numeric-range"><label>Start <div><input aria-label="Short start seconds" type="number" min="0" max={track.durationSeconds} step="0.1" value={draft.short.start} onChange={(event) => setRange(Number(event.target.value), Number(event.target.value) + (draft.short.end - draft.short.start))}/><span>s</span></div></label><label>End <div><input aria-label="Short end seconds" type="number" min="0" max={track.durationSeconds} step="0.1" value={draft.short.end} onChange={(event) => setRange(draft.short.start, Number(event.target.value))}/><span>s</span></div></label><label>Duration <div className="readonly-value">{(draft.short.end - draft.short.start).toFixed(1)}s</div></label><button className={`approval-button ${draft.short.approved ? 'approved' : ''}`} disabled={draft.short.reviewRequired} onClick={() => dispatch({ type: 'approve' })}>{draft.short.approved && <Check size={16}/>} {draft.short.approved ? 'Approved' : 'Approve Short'}</button></div></div></main>
      <aside className="panel inspector"><div className="panel-title"><div><span className="eyebrow">Approximate preview</span><h2>Visual controls</h2></div><button onClick={() => dispatch({ type: 'reset-effects' })}><RotateCcw size={13}/> Reset inherited</button></div>
        <section className="control-group"><label className="switch-row"><span><strong>Camera motion</strong><small>Bounded approximation</small></span><input aria-label="Camera motion" type="checkbox" checked={draft.effects.camera} onChange={(event) => dispatch({ type: 'set-effect', key: 'camera', value: event.target.checked })}/><i/></label></section>
        <section className="control-group"><label className="switch-row"><span><strong>RMS audio bars</strong><small>Demonstration values only</small></span><input aria-label="RMS audio bars" type="checkbox" checked={draft.effects.bars} onChange={(event) => dispatch({ type: 'set-effect', key: 'bars', value: event.target.checked })}/><i/></label></section>
        <section className="control-group"><label className="range-label"><span>Tint intensity</span><strong>{draft.effects.tintIntensity}%</strong><input aria-label="Tint intensity" type="range" min="0" max="60" step="1" value={draft.effects.tintIntensity} onChange={(event) => dispatch({ type: 'set-effect', key: 'tintIntensity', value: Number(event.target.value) })}/></label></section>
      </aside>
    </div>
  </>
}
