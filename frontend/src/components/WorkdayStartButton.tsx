import { useState, type ReactNode } from 'react'
import toast from 'react-hot-toast'
import { useClockAction } from '../api/enterprise'

interface WorkdayStartButtonProps {
  children?: ReactNode
  className?: string
  disabled?: boolean
}

function locationErrorMessage(error: GeolocationPositionError) {
  if (error.code === error.PERMISSION_DENIED) return 'Ажил эхлүүлэхийн тулд байршлын зөвшөөрөл олгоно уу.'
  if (error.code === error.TIMEOUT) return 'Байршлыг тодорхойлох хугацаа дууслаа. Дахин оролдоно уу.'
  return 'Таны байршлыг тодорхойлж чадсангүй. Байршлын тохиргоогоо шалгана уу.'
}

export function WorkdayStartButton({ children = 'Оффис эхлэх', className = 'primary-action', disabled = false }: WorkdayStartButtonProps) {
  const action = useClockAction()
  const [locating, setLocating] = useState(false)

  const start = () => {
    if (!navigator.geolocation) {
      toast.error('Энэ төхөөрөмж байршил тодорхойлохыг дэмжихгүй байна.')
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

  return <button type="button" className={className} onClick={start} disabled={disabled || locating || action.isPending} aria-busy={locating || action.isPending}>{locating ? 'Байршил шалгаж байна…' : children}</button>
}

