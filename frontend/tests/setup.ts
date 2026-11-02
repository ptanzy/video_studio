import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

const waveMocks = vi.hoisted(() => {
  const value = { destroy: vi.fn(), pause: vi.fn(), play: vi.fn(() => Promise.resolve()), setTime: vi.fn(), load: vi.fn(() => Promise.resolve()), listeners: new Map<string, (...args: any[]) => void>(), regionListeners: new Map<string, (...args: any[]) => void>() }
  ;(globalThis as typeof globalThis & { __waveMocks: typeof value }).__waveMocks = value
  return value
})
const region = { start: 0, end: 30, setOptions: vi.fn() }
const regions = { clearRegions: vi.fn(), addRegion: vi.fn(() => region), getRegions: vi.fn(() => [region]), on: vi.fn((name: string, callback: (...args: any[]) => void) => waveMocks.regionListeners.set(name, callback)) }
const mediaPaused = new WeakMap<HTMLMediaElement, boolean>()

Object.defineProperty(HTMLMediaElement.prototype, 'paused', { configurable: true, get() { return mediaPaused.get(this) ?? true } })
Object.defineProperty(HTMLMediaElement.prototype, 'play', { configurable: true, value: vi.fn(function (this: HTMLMediaElement) { mediaPaused.set(this, false); this.dispatchEvent(new Event('play')); return Promise.resolve() }) })
Object.defineProperty(HTMLMediaElement.prototype, 'pause', { configurable: true, value: vi.fn(function (this: HTMLMediaElement) { mediaPaused.set(this, true); this.dispatchEvent(new Event('pause')) }) })
Object.defineProperty(HTMLMediaElement.prototype, 'load', { configurable: true, value: vi.fn(function (this: HTMLMediaElement) { queueMicrotask(() => this.dispatchEvent(new Event('loadedmetadata'))) }) })

vi.mock('wavesurfer.js/dist/plugins/regions.esm.js', () => ({ default: { create: vi.fn(() => regions) } }))
vi.mock('wavesurfer.js', () => ({
  default: { create: vi.fn(() => ({
    on: vi.fn((name: string, callback: (...args: any[]) => void) => waveMocks.listeners.set(name, callback)),
    load: waveMocks.load,
    destroy: waveMocks.destroy,
    pause: waveMocks.pause,
    play: waveMocks.play,
    setTime: waveMocks.setTime,
    isPlaying: vi.fn(() => false),
    getCurrentTime: vi.fn(() => 0),
    getActivePlugins: vi.fn(() => [regions]),
  })) },
}))

afterEach(() => {
  cleanup()
  waveMocks.destroy.mockClear()
  waveMocks.listeners.clear()
  waveMocks.regionListeners.clear()
  vi.unstubAllGlobals()
})
