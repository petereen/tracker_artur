import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { useClockAction, useWorktimeMethods } from '../api/enterprise'
import i18n from '../i18n'

interface WorkdayStartButtonProps {
  children?: ReactNode
  className?: string
  disabled?: boolean
}

function locationErrorMessage(error: GeolocationPositionError) {
  if (error.code === error.PERMISSION_DENIED) return i18n.t('shell.workdayStart.permissionDenied')
  if (error.code === error.TIMEOUT) return i18n.t('shell.workdayStart.timeout')
  return i18n.t('shell.workdayStart.failed')
}

/**
 * Office start that follows the organization's check-in methods: location
 * check when enabled, the QR scanner when only QR is on, and a plain start
 * when both are off.
 */
export function WorkdayStartButton({ children, className = 'primary-action', disabled = false }: WorkdayStartButtonProps) {
  const { t } = useTranslation()
  const action = useClockAction()
  const methods = useWorktimeMethods()
  const navigate = useNavigate()
  const [locating, setLocating] = useState(false)
  const locationEnabled = methods.data?.location_enabled ?? true
  const qrEnabled = methods.data?.qr_enabled ?? true

  const start = () => {
    if (!locationEnabled) {
      if (qrEnabled) navigate('/worktime?scan=1')
      else action.mutate({ action: 'start', mode: 'in_person' })
      return
    }
    if (!navigator.geolocation) {
      toast.error(t('shell.workdayStart.unsupported'))
      return
    }
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setLocating(false)
        action.mutate({
          action: 'start',
          mode: 'in_person',
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        })
      },
      (error) => {
        setLocating(false)
        toast.error(locationErrorMessage(error))
      },
      { enableHighAccuracy: true, maximumAge: 0, timeout: 10_000 },
    )
  }

  return <button type="button" className={className} onClick={start} disabled={disabled || locating || action.isPending} aria-busy={locating || action.isPending}>{locating ? t('shell.workdayStart.checking') : (children ?? t('shell.workdayStart.label'))}</button>
}
