import type { StudioAlbum } from '../api/types'

const track = (id: string, number: number, title: string, seconds: number) => ({
  id,
  number,
  title,
  audio: `audio/${String(number).padStart(2, '0')}.wav`,
  normalized_sample_count: seconds * 48_000,
  audio_sha256: '0'.repeat(64),
  durationSeconds: seconds,
})

export const DEMO_ALBUMS: StudioAlbum[] = [
  {
    projectId: 'demo-echoes', sourceMode: 'demonstration', title: 'Echoes of Asia',
    artist: 'WRLD-FI', channel: 'WRLD-FI', artworkLabel: 'Demonstration artwork',
    profileId: 'youtube-1080p30-player-v1', valid: true,
    tracks: [
      track('demo-t01', 1, 'Moonlight Over Gyeongju', 248),
      track('demo-t02', 2, 'Lanterns Across the Water', 226),
      track('demo-t03', 3, 'Temple Rain at Dawn', 254),
      track('demo-t04', 4, 'Bamboo Shadows', 198),
    ],
  },
  {
    projectId: 'demo-atrium', sourceMode: 'demonstration', title: 'Atrium Weather',
    artist: 'WRLD Archive', channel: 'Demonstration Library', artworkLabel: 'Demonstration artwork',
    profileId: 'youtube-1080p30-motion-v1', valid: true,
    tracks: [track('atrium-t01', 1, 'Glasshouse Morning', 193), track('atrium-t02', 2, 'Warm Front', 217)],
  },
]
