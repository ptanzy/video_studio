import type { VisualTemplate } from '../../api/types'

export const CompositionPreview = ({ title, template, imageUrl, progress = 0 }: { title: string; template?: VisualTemplate; imageUrl?: string; progress?: number }) => {
  const treatment = template?.color_treatment
  const tint = treatment?.mode === 'custom' ? `${treatment.hex}${Math.round(treatment.intensity * 255).toString(16).padStart(2, '0')}` : 'transparent'
  const zoom = template?.camera.mode === 'bounded' ? template.camera.max_zoom : 1
  const portrait = template?.canvas.aspect_ratio === '9:16'
  return <div className={`composition-shell template-preview ${portrait ? 'portrait' : 'landscape'}`}>
    <div className="preview-label"><span>{portrait ? '9:16 portrait' : '16:9 landscape'}</span><strong>Approximate</strong></div>
    <div className="composition-canvas" style={{ aspectRatio: portrait ? '9 / 16' : '16 / 9' }}>
      {imageUrl ? <img
        className={template?.camera.mode === 'bounded' ? 'bounded-camera' : ''}
        src={imageUrl}
        alt=""
        style={{ objectFit: template?.geometry.fit_mode ?? 'contain', objectPosition: `${(template?.geometry.focal_x ?? 0.5) * 100}% ${(template?.geometry.focal_y ?? 0.5) * 100}%`, transform: `scale(${zoom})` }}
      /> : <div className="no-background"><strong>No background selected</strong><span>Choose an imported project image to preview this composition.</span></div>}
      {tint !== 'transparent' && (
        <div className="preview-tint" style={{ background: tint }}/>
      )}
      <div className="preview-overlay"><strong>{title}</strong>{template?.visualizer.enabled && <div className="mini-bars" aria-label="Approximate visualizer enabled">{Array.from({ length: Math.min(template.visualizer.bar_count, 32) }, (_, index) => <i key={index} style={{ height: `${5 + ((index * 11) % 18)}px`, opacity: template.visualizer.opacity }}/>)}</div>}</div>
      {template?.progress.enabled && <div className="preview-progress"><span style={{ width: `${Math.max(0, Math.min(1, progress)) * 100}%` }}/></div>}
    </div>
    <p>Approximate browser preview · authoritative rendering is not available for Creation templates.</p>
  </div>
}
