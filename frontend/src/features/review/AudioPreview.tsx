/* eslint-disable react-refresh/only-export-components */
import { Pause, Play } from 'lucide-react'
import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { assetAudioUrl } from '../../api/client'
import type { ReviewWorkspace } from '../../api/types'

type AudioAsset = ReviewWorkspace['assets'][number]

export interface AudioPreviewController {
  activeKey: string
  error: string
  playing: boolean
  progress: number
  stop: () => void
  toggle: (key: string, asset: AudioAsset, startSeconds?: number, endSeconds?: number) => Promise<void>
}

export const useAudioPreview = (projectId: string): AudioPreviewController => {
  const mediaRef = useRef<HTMLAudioElement | null>(null)
  const activeKeyRef = useRef('')
  const endSecondsRef = useRef<number | undefined>()
  const startSecondsRef = useRef(0)
  const generationRef = useRef(0)
  const timerRef = useRef<number | undefined>()
  const [activeKey, setActiveKey] = useState('')
  const [playing, setPlaying] = useState(false)
  const [error, setError] = useState('')
  const [progress, setProgress] = useState(0)

  const clearTimer = useCallback(() => {
    if (timerRef.current !== undefined) window.clearTimeout(timerRef.current)
    timerRef.current = undefined
  }, [])
  const finish = useCallback(() => {
    clearTimer()
    const media = mediaRef.current
    if (media && !media.paused) media.pause()
    activeKeyRef.current = ''
    endSecondsRef.current = undefined
    setActiveKey('')
    setPlaying(false)
    setProgress(0)
  }, [clearTimer])
  const finishRef = useRef(finish)
  finishRef.current = finish

  const scheduleBoundary = useCallback(() => {
    clearTimer()
    const media = mediaRef.current
    const endSeconds = endSecondsRef.current
    if (!media || endSeconds === undefined || media.paused) return
    const remaining = Math.max(0, endSeconds - media.currentTime)
    timerRef.current = window.setTimeout(() => finishRef.current(), remaining * 1000)
  }, [clearTimer])

  useEffect(() => {
    const media = new Audio()
    media.preload = 'metadata'
    mediaRef.current = media
    const onPlay = () => { setPlaying(true); scheduleBoundary() }
    const onPause = () => { clearTimer(); setPlaying(false) }
    const onEnded = () => finishRef.current()
    const onTimeUpdate = () => {
      const endSeconds = endSecondsRef.current
      const effectiveEnd = endSeconds ?? (Number.isFinite(media.duration) ? media.duration : undefined)
      if (effectiveEnd !== undefined && effectiveEnd > startSecondsRef.current) {
        setProgress(Math.max(0, Math.min(1, (media.currentTime - startSecondsRef.current) / (effectiveEnd - startSecondsRef.current))))
      }
      if (endSeconds !== undefined && media.currentTime >= endSeconds) finishRef.current()
    }
    const onError = () => {
      setError('This browser could not play the selected recording.')
      finishRef.current()
    }
    media.addEventListener('play', onPlay)
    media.addEventListener('pause', onPause)
    media.addEventListener('ended', onEnded)
    media.addEventListener('timeupdate', onTimeUpdate)
    media.addEventListener('error', onError)
    return () => {
      generationRef.current += 1
      clearTimer()
      media.pause()
      media.removeAttribute('src')
      media.load()
      media.removeEventListener('play', onPlay)
      media.removeEventListener('pause', onPause)
      media.removeEventListener('ended', onEnded)
      media.removeEventListener('timeupdate', onTimeUpdate)
      media.removeEventListener('error', onError)
      mediaRef.current = null
    }
  }, [clearTimer, projectId, scheduleBoundary])

  const toggle = useCallback(async (key: string, asset: AudioAsset, startSeconds = 0, endSeconds?: number) => {
    const media = mediaRef.current
    if (!media) return
    setError('')
    if (activeKeyRef.current === key) {
      if (media.paused) {
        try { await media.play(); scheduleBoundary() }
        catch { setError('This browser could not play the selected recording.'); finish() }
      } else media.pause()
      return
    }

    const generation = ++generationRef.current
    media.pause()
    clearTimer()
    activeKeyRef.current = key
    startSecondsRef.current = startSeconds
    endSecondsRef.current = endSeconds
    setActiveKey(key)
    setPlaying(false)
    setProgress(0)
    media.src = assetAudioUrl(projectId, asset.asset_id)
    media.load()
    try {
      if (media.readyState < 1) {
        await new Promise<void>((resolve, reject) => {
          const loaded = () => { cleanup(); resolve() }
          const failed = () => { cleanup(); reject(new Error('Audio metadata could not be loaded.')) }
          const cleanup = () => {
            media.removeEventListener('loadedmetadata', loaded)
            media.removeEventListener('error', failed)
          }
          media.addEventListener('loadedmetadata', loaded)
          media.addEventListener('error', failed)
        })
      }
      if (generation !== generationRef.current || activeKeyRef.current !== key) return
      media.currentTime = startSeconds
      await media.play()
      if (generation === generationRef.current) scheduleBoundary()
    } catch {
      if (generation !== generationRef.current) return
      setError('This browser could not play the selected recording.')
      finish()
    }
  }, [clearTimer, finish, projectId, scheduleBoundary])

  return { activeKey, error, playing, progress, stop: finish, toggle }
}

export const AudioPreviewButton = ({
  asset, controller, playbackKey, playLabel, pauseLabel, startSeconds, endSeconds,
}: {
  asset?: AudioAsset
  controller: AudioPreviewController
  playbackKey: string
  playLabel: string
  pauseLabel: string
  startSeconds?: number
  endSeconds?: number
}) => {
  const helpId = useId()
  const supported = Boolean(
    asset
    && asset.presence === 'present'
    && asset.capabilities.server_stream.status === 'supported'
    && asset.capabilities.browser_audition.status !== 'unsupported',
  )
  const active = controller.activeKey === playbackKey && controller.playing
  const reason = !asset
    ? 'The source recording is not currently included in this workspace.'
    : asset.presence !== 'present'
      ? 'The source recording is missing.'
      : asset.capabilities.server_stream.status !== 'supported'
        ? `Preview unavailable: ${asset.capabilities.server_stream.reason}`
        : `Preview unavailable: ${asset.capabilities.browser_audition.reason}`
  return <span className="audio-preview-control"><button
    type="button"
    className="audio-preview-button"
    aria-label={supported ? (active ? pauseLabel : playLabel) : `${playLabel} unavailable`}
    aria-disabled={!supported}
    aria-describedby={supported ? undefined : helpId}
    title={supported ? (active ? pauseLabel : playLabel) : reason}
    onClick={() => supported && asset && void controller.toggle(playbackKey, asset, startSeconds, endSeconds)}
  >{active ? <Pause size={13}/> : <Play size={13}/>}</button>{!supported && <span className="sr-only" id={helpId}>{reason}</span>}</span>
}
