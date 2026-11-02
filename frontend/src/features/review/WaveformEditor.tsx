import { useEffect, useRef, useState } from 'react'
import WaveSurfer from 'wavesurfer.js'
import RegionsPlugin from 'wavesurfer.js/dist/plugins/regions.esm.js'
import { Pause, Play, RotateCcw, SkipBack } from 'lucide-react'
import type { PrimaryShort } from '../../api/types'

interface Props {
  audioUrl?: string
  duration: number
  region: PrimaryShort
  onChange: (start: number, end: number) => void
}

const makePeaks = () => {
  const values = new Float32Array(640)
  for (let index = 0; index < values.length; index += 1) values[index] = Math.sin(index * 0.71) * (0.2 + Math.abs(Math.sin(index * 0.037)) * 0.72)
  return values
}

const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}.${Math.floor((seconds % 1) * 10)}`

export const WaveformEditor = ({ audioUrl, duration, region, onChange }: Props) => {
  const container = useRef<HTMLDivElement>(null)
  const wave = useRef<WaveSurfer | null>(null)
  const bounds = useRef(region)
  const onChangeRef = useRef(onChange)
  const [playing, setPlaying] = useState(false)
  const [time, setTime] = useState(region.start)
  bounds.current = region
  onChangeRef.current = onChange

  useEffect(() => {
    if (!container.current) return
    const regions = RegionsPlugin.create()
    const instance = WaveSurfer.create({
      container: container.current, height: 116, waveColor: '#53637a', progressColor: '#889dbb',
      cursorColor: '#f0bc73', cursorWidth: 1, barWidth: 2, barGap: 2, barRadius: 2,
      normalize: true, plugins: [regions],
    })
    wave.current = instance
    const addRegion = () => {
      regions.clearRegions()
      regions.addRegion({ id: 'primary-short', start: bounds.current.start, end: bounds.current.end, color: 'rgba(224, 153, 69, .20)', drag: true, resize: true, minLength: Math.min(0.1, duration) })
    }
    instance.on('ready', addRegion)
    instance.on('decode', addRegion)
    instance.on('timeupdate', (current) => {
      setTime(current)
      if (instance.isPlaying() && current >= bounds.current.end) { instance.pause(); instance.setTime(bounds.current.start); setPlaying(false) }
    })
    instance.on('pause', () => setPlaying(false))
    instance.on('play', () => setPlaying(true))
    regions.on('region-updated', (updated) => onChangeRef.current(Math.max(0, updated.start), Math.min(duration, updated.end)))
    if (audioUrl) void instance.load(audioUrl)
    else void instance.load('', [makePeaks()], duration).catch(() => undefined)
    return () => { instance.destroy(); wave.current = null }
  }, [audioUrl, duration])

  useEffect(() => {
    const plugin = wave.current?.getActivePlugins().find((candidate) => 'getRegions' in candidate) as ReturnType<typeof RegionsPlugin.create> | undefined
    const active = plugin?.getRegions()[0]
    if (active && (Math.abs(active.start - region.start) > 0.05 || Math.abs(active.end - region.end) > 0.05)) active.setOptions({ start: region.start, end: region.end })
  }, [region.start, region.end])

  const play = () => {
    const instance = wave.current
    if (!instance) return
    if (instance.isPlaying()) instance.pause()
    else { if (instance.getCurrentTime() < region.start || instance.getCurrentTime() >= region.end) instance.setTime(region.start); void instance.play() }
  }
  return <div className="waveform-editor">
    <div className="wave-head"><div><span className="eyebrow">Audio excerpt</span><h3>Primary Short range</h3></div><span className="time-chip">{clock(region.start)} — {clock(region.end)} · {(region.end - region.start).toFixed(1)}s</span></div>
    <div ref={container} className="wave-container" role="slider" tabIndex={0} aria-label="Interactive Short start position" aria-valuemin={0} aria-valuemax={duration} aria-valuenow={region.start} aria-valuetext={`${clock(region.start)} to ${clock(region.end)}`} onKeyDown={(event) => {
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return
      event.preventDefault()
      const step = event.shiftKey ? 1 : .1
      const offset = event.key === 'ArrowLeft' ? -step : step
      const length = region.end - region.start
      const start = Math.max(0, Math.min(duration - length, region.start + offset))
      onChange(start, start + length)
    }}/>
    <div className="wave-ticks"><span>0:00</span><span>{clock(duration / 4)}</span><span>{clock(duration / 2)}</span><span>{clock(duration * .75)}</span><span>{clock(duration)}</span></div>
    <div className="transport">
      <button className="transport-main" disabled={!audioUrl} title={audioUrl ? undefined : 'Audio playback requires a connected Phase 1 project.'} onClick={play}>{playing ? <Pause size={16} /> : <Play size={16} />}{audioUrl ? (playing ? 'Pause' : 'Play selection') : 'Audio unavailable'}</button>
      <button disabled={!audioUrl} title={audioUrl ? undefined : 'Audio playback requires a connected Phase 1 project.'} onClick={() => { wave.current?.pause(); wave.current?.setTime(region.start); setTime(region.start) }}><SkipBack size={16} /> Replay</button>
      <span>{clock(time)}</span><button className="quiet" onClick={() => onChange(0, Math.min(30, duration))}><RotateCcw size={15} /> Reset 30s</button>
    </div>
  </div>
}
