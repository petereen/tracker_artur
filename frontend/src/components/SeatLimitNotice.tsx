import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Banner } from '@astryxdesign/core/Banner'
import { useTenantSeats, type SeatUsage } from '../api/tenancy'
import i18n from '../i18n'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'

export function seatsFull(seats: SeatUsage | undefined) {
  return Boolean(seats && seats.limit !== null && seats.used >= seats.limit)
}

export const seatFullWorkerMessage = () => i18n.t('tenant.seats.workerAdded')

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
  const { t } = useTranslation()
  const { seats, full } = useWorkerSeats()
  if (!seats || !full) return null
  const roles = useAuthStore.getState().actor?.account_roles ?? []
  return <Banner status="warning" collapsible={false}
    title={t('tenant.seats.title', { used: seats.used, limit: seats.limit })}
    description={t(context === 'worker' ? 'tenant.seats.worker' : 'tenant.seats.account')}
    endContent={roles.includes('admin') ? <Link to="/administration/security/license">{t('tenant.seats.upgrade')}</Link> : undefined} />
}
