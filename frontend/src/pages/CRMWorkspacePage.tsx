import { createElement, useState } from 'react'
import { MessagesSquare, Settings2, Users, type LucideIcon } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useCRMActivity, useCRMCapabilities, useCRMLookups, type CRMActivity, type CRMParty } from '../api/crm'
import { useActor } from '../api/enterprise'
import { ActivitiesPanel } from '../components/crm/ActivitiesPanel'
import { ActivityForm } from '../components/crm/ActivityForm'
import { CustomerDetail } from '../components/crm/CustomerDetail'
import { CustomerForm } from '../components/crm/CustomerForm'
import { CustomersPanel } from '../components/crm/CustomersPanel'
import { SettingsPanel } from '../components/crm/SettingsPanel'
import { crmErrorText } from '../components/crm/shared'
import '../components/crm/crm.css'

type Tab = 'activities' | 'customers' | 'settings'
const TAB_PATHS: Record<Tab, string> = { activities: '/erp/crm', customers: '/erp/crm/customers', settings: '/erp/crm/settings' }
const TAB_ICONS: Record<Tab, LucideIcon> = { activities: MessagesSquare, customers: Users, settings: Settings2 }
const MANAGER_ROLES = ['admin', 'manager', 'team_lead']

export function CRMWorkspacePage() {
  const { t } = useTranslation()
  const capabilities = useCRMCapabilities()
  const actor = useActor()
  const location = useLocation()
  const navigate = useNavigate()
  const { partyId } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const caps = capabilities.data
  const canUse = Boolean(caps && (caps.parties.view || caps.activities.view))
  const lookups = useCRMLookups(canUse)
  const activityParam = Number(searchParams.get('activity')) || undefined
  const linkedActivity = useCRMActivity(activityParam)
  const [editingActivity, setEditingActivity] = useState<CRMActivity | 'new' | null>(null)
  const [activityParty, setActivityParty] = useState<{ id: number; label: string } | null>(null)
  const [editingParty, setEditingParty] = useState<CRMParty | 'new' | null>(null)

  const tab: Tab = location.pathname.startsWith(TAB_PATHS.customers) ? 'customers' : location.pathname.startsWith(TAB_PATHS.settings) ? 'settings' : 'activities'
  const isManager = Boolean(actor.data?.roles?.some((role) => MANAGER_ROLES.includes(role)))

  if (capabilities.isLoading || (canUse && lookups.isLoading)) return <div className="hr-empty">{t('crm.common.loading')}</div>
  if (capabilities.isError) return <div className="hr-empty">{crmErrorText(capabilities.error)}</div>
  if (!caps || !canUse) return <div className="hr-empty">{t('crm.page.noAccess')}</div>
  if (!lookups.data) return <div className="hr-empty">{lookups.isError ? crmErrorText(lookups.error) : t('crm.common.loading')}</div>

  const data = lookups.data
  const visibleTabs = (['activities', 'customers', 'settings'] as Tab[]).filter((key) => (key === 'customers' ? caps.parties.view : key === 'activities' ? caps.activities.view : caps.activities.view || caps.settings.edit))
  const openActivity = (activity: CRMActivity) => setEditingActivity(activity)
  const closeActivity = () => {
    setEditingActivity(null)
    setActivityParty(null)
    if (activityParam) { searchParams.delete('activity'); setSearchParams(searchParams, { replace: true }) }
  }
  const shownActivity = editingActivity ?? (activityParam && linkedActivity.data ? linkedActivity.data : null)

  return <div className="crm-workspace">
    {!caps.module_enabled && <div className="crm-warning">
      {actor.data?.roles?.includes('admin')
        ? <>{t('crm.page.moduleOffBefore')} <Link to="/administration/organization/modules">{t('crm.page.moduleOffLink')}</Link> {t('crm.page.moduleOffAfter')}</>
        : t('crm.page.moduleOffMember')}
    </div>}
    <nav className="page-tabs"><div className="page-tabs-list" aria-label={t('crm.page.tabsAria')}>
      {visibleTabs.map((key) => <button key={key} className={tab === key ? 'active' : ''} onClick={() => navigate(TAB_PATHS[key])}>{createElement(TAB_ICONS[key], { size: 15 })}{t(`crm.page.tab.${key}`)}</button>)}
    </div></nav>

    {tab === 'activities' && caps.activities.view && <ActivitiesPanel lookups={data} capabilities={caps} isManager={isManager} onOpen={openActivity} onCreate={() => setEditingActivity('new')} />}
    {tab === 'customers' && caps.parties.view && <CustomersPanel lookups={data} capabilities={caps} onOpen={(party) => navigate(`${TAB_PATHS.customers}/${party.id}`)} onCreate={() => setEditingParty('new')} />}
    {tab === 'settings' && <SettingsPanel lookups={data} canEdit={caps.settings.edit} />}

    {tab === 'customers' && partyId && <CustomerDetail
      key={partyId}
      partyId={Number(partyId)} lookups={data} capabilities={caps} isManager={isManager}
      onClose={() => navigate(TAB_PATHS.customers)}
      onEdit={(party) => setEditingParty(party)}
      onOpenActivity={openActivity}
      onNewActivity={(party) => { setActivityParty({ id: party.id, label: `${party.name} (${party.code})` }); setEditingActivity('new') }}
      onOpenParty={(id) => navigate(`${TAB_PATHS.customers}/${id}`)}
    />}

    <div className="crm-layer">
    {shownActivity && <ActivityForm
      key={shownActivity === 'new' ? 'new' : `${shownActivity.id}:${shownActivity.version}`}
      activity={shownActivity === 'new' ? null : shownActivity}
      lookups={data} capabilities={caps} defaultParty={activityParty}
      onClose={closeActivity}
    />}
    {editingParty && <CustomerForm
      party={editingParty === 'new' ? null : editingParty}
      lookups={data}
      onClose={() => setEditingParty(null)}
      onSaved={(saved) => { if (editingParty === 'new') navigate(`${TAB_PATHS.customers}/${saved.id}`) }}
    />}
    </div>
  </div>
}
