import { Link } from 'react-router-dom'
import { Banner } from '@astryxdesign/core/Banner'
import { useTenantSeats, type SeatUsage } from '../api/tenancy'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'

export function seatsFull(seats: SeatUsage | undefined) {
  return Boolean(seats && seats.limit !== null && seats.used >= seats.limit)
}

export const SEAT_FULL_WORKER_MESSAGE = 'Ажилтан бүртгэгдлээ. Лицензийн хэрэглэгчийн эрх дүүрсэн тул түүнд системд нэвтрэх эрх олгогдохгүй.'

/** Seats of the tenant for admins and HR (the only roles that add workers). */
export function useWorkerSeats() {
  const roles = useAuthStore((state) => state.actor?.account_roles ?? state.actor?.roles ?? EMPTY_ROLES)
  const seats = useTenantSeats(roles.includes('admin') || roles.includes('hr'))
  return { seats: seats.data, full: seatsFull(seats.data) }
}

/**
 * Warning shown where workers or logins are added. Workers can always be
 * added (an HR record takes no seat); only a login needs a free seat.
 */
export function SeatLimitNotice({ context = 'worker' }: { context?: 'worker' | 'account' }) {
  const { seats, full } = useWorkerSeats()
  if (!seats || !full) return null
  const roles = useAuthStore.getState().actor?.account_roles ?? []
  return <Banner status="warning" collapsible={false}
    title={`Хэрэглэгчийн эрх дүүрсэн (${seats.used} / ${seats.limit})`}
    description={context === 'worker'
      ? 'Ажилтныг бүртгэж болно, гэхдээ шинэ ажилтанд системд нэвтрэх эрх олгогдохгүй (Telegram урилга ч ажиллахгүй). Багцаа өргөтгөх эсвэл ашиглахгүй хэрэглэгчийг идэвхгүй болгоно уу.'
      : 'Шинэ нэвтрэх эрх үүсгэх боломжгүй. Багцаа өргөтгөх эсвэл ашиглахгүй хэрэглэгчийг идэвхгүй болгоно уу.'}
    endContent={roles.includes('admin') ? <Link to="/administration/security/license">Багц өргөтгөх</Link> : undefined} />
}
