import type { CapacitorConfig } from '@capacitor/cli'

const otaChannel = process.env.VITE_OTA_CHANNEL === 'staging' ? 'staging' : 'production'
const config: CapacitorConfig = {
  appId: 'mn.oyuns.workspace',
  appName: 'OYUNS Workspace',
  webDir: 'dist',
  plugins: {
    PushNotifications: {
      presentationOptions: ['badge', 'sound', 'banner', 'list'],
    },
    CapacitorUpdater: {
      appId: 'mn.oyuns.workspace',
      // The native plugin remains the installer/rollback engine. Update checks
      // are performed against the OYUNS API by frontend code so no Capgo Cloud
      // endpoint or telemetry is contacted.
      autoUpdate: 'off',
      defaultChannel: otaChannel,
      appReadyTimeout: 10_000,
      autoDeleteFailed: true,
      autoDeletePrevious: true,
      resetWhenUpdate: true,
      autoSplashscreen: false,
      keepUrlPathAfterReload: false,
      allowSetDefaultChannel: false,
      allowModifyAppId: false,
      allowModifyUrl: false,
      statsUrl: '',
    },
  },
}

export default config
