import { assetAudioUrl, assetImageUrl, assetThumbnailUrl } from '../../api/client'
import type { ReviewWorkspace } from '../../api/types'
import { useStudio, type ReviewTab } from '../../app/state'
import { CreationWorkspace } from './CreationWorkspace'
import { EditorWorkspace } from './EditorWorkspace'

export const ReviewPage = () => {
  const { state, dispatch, requestGuarded } = useStudio()
  const tab = state.reviewTab
  const workspace = state.albums.find((item) => item.projectId === state.selectedAlbumId)
  if (!workspace) return <div className="panel empty-state"><strong>No project is open</strong><span>Open a project from Import to inspect media and prepare Creation drafts.</span></div>
  return <>
    <section className="page-heading review-heading"><div><span className="kicker">02 · REVIEW</span><h1>{workspace.name}</h1><p>{workspace.assets.length} included media assets · {workspace.tracks.length} audio recordings</p></div></section>
    <nav className="subworkspace-tabs" aria-label="Review workspace">{(['media','creation','editor'] as ReviewTab[]).map((value) => <button key={value} className={tab === value ? 'active' : ''} aria-current={tab === value ? 'page' : undefined} onClick={() => requestGuarded(() => dispatch({ type: 'select-review-tab', tab: value }))}>{value[0].toUpperCase() + value.slice(1)}</button>)}</nav>
    <div className="review-truth"><span className={workspace.sourceMode !== 'demonstration' ? 'real' : ''}>{workspace.sourceMode === 'inventory' ? 'PROJECT MEDIA' : workspace.sourceMode === 'backend' ? 'MANIFEST MEDIA' : 'DEMONSTRATION MEDIA'}</span><p>Creation drafts are saved privately and never modify source files. Rendering remains a separate capability check.</p></div>
    {tab === 'media' && <MediaWorkspace workspace={workspace}/>}
    {tab === 'creation' && <CreationWorkspace workspace={workspace}/>}
    {tab === 'editor' && <EditorWorkspace workspace={workspace}/>}
  </>
}

const MediaWorkspace = ({ workspace }: { workspace: ReviewWorkspace }) => <div className="panel review-media"><div className="panel-title"><div><span className="eyebrow">Included collection</span><h2>Project Media</h2></div></div>{!workspace.assets.length && <div className="empty-state">This project has no included media. Restore assets in Import or scan for files.</div>}<div className="asset-grid">{workspace.assets.map((asset) => <article key={asset.asset_id}>{asset.kind === 'image' && asset.capabilities.thumbnail.status === 'supported' ? <a className="asset-image" href={assetImageUrl(workspace.projectId, asset.asset_id)} target="_blank" rel="noreferrer"><img src={assetThumbnailUrl(workspace.projectId, asset.asset_id)} alt={`Preview of ${asset.relative_path}`}/></a> : <div className="asset-placeholder">{asset.kind.toUpperCase()}</div>}<strong>{asset.relative_path.split('/').at(-1)}</strong><small>{asset.relative_path}</small>{asset.kind === 'audio' && asset.capabilities.server_stream.status === 'supported' ? <audio controls preload="metadata" src={assetAudioUrl(workspace.projectId, asset.asset_id)}/> : asset.kind === 'audio' && <span className="unsupported-note">Audition unavailable · {asset.capabilities.server_stream.reason}</span>} {asset.kind === 'image' && asset.capabilities.inspection.status !== 'supported' && <span className="unsupported-note">Inspection unavailable · {asset.capabilities.inspection.reason}</span>}{asset.kind === 'video' && <span className="unsupported-note">Discovery only · WU8 rendering is not implemented</span>}</article>)}</div></div>
