import { registerPlugin } from '@capacitor/core'
import { isNativePlatform } from './runtime'

export type AudioRoute = 'default' | 'speaker'

interface NativeAudioRoutePlugin {
  setRoute(options: { route: AudioRoute }): Promise<{ route: AudioRoute }>
}

const nativeAudioRoute = registerPlugin<NativeAudioRoutePlugin>('AudioRoute')

export async function setCallAudioRoute(route: AudioRoute) {
  if (isNativePlatform()) return (await nativeAudioRoute.setRoute({ route })).route
  const audio = document.querySelector<HTMLAudioElement>('audio[data-call-audio]')
  const sinkAudio = audio as (HTMLAudioElement & { setSinkId?: (sinkId: string) => Promise<void> }) | null
  if (sinkAudio?.setSinkId) await sinkAudio.setSinkId('default')
  return route
}
