import { Suspense, useEffect, useRef, useState } from 'react'
import { BrowserRouter, Navigate, Outlet, Route, Routes, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { clearAuthenticatedQueryCache } from './api/client'
import { bootstrapSession, useActor } from './api/enterprise'
import { EnterpriseShell } from './components/EnterpriseShell'
import { useAuthStore } from './store/auth'
import { useWorkspaceModeStore } from './store/workspaceMode'
import { LoginPage } from './pages/LoginPage'
import { ForgotPasswordPage, ResetPasswordPage } from './pages/PasswordResetPages'
import { InitialWorkspaceSkeleton, lazyWithPreload as lazy, RouteLoadErrorBoundary } from './components/Loading'
import { notificationService } from './platform/notifications'
import { isNativePlatform } from './platform/runtime'
import { CallProvider } from './components/CallProvider'
import { tenancyError, useTenantContext } from './api/tenancy'
import { LicenseRequiredScreen, WorkspaceUnavailableScreen, isWorkspaceUnavailable, useLicenseGraceNotice } from './components/TenantGate'
import { TwoFactorGate } from './components/TwoFactorGate'
import { TWO_FACTOR_REQUIRED_EVENT } from './platform/app-events'
import { App as NativeApp } from '@capacitor/app'
import { BiometricLockGate } from './components/BiometricLock'
import { syncAutoWorktime } from './platform/auto-worktime'

const EnterpriseDashboardPage = lazy(() => import('./pages/EnterpriseDashboardPage').then((module) => ({ default: module.EnterpriseDashboardPage })))
const AnnouncementsPage = lazy(() => import('./pages/AnnouncementsPage').then((module) => ({ default: module.AnnouncementsPage })))
const WorktimePage = lazy(() => import('./pages/WorktimePage').then((module) => ({ default: module.WorktimePage })))
const WorktimeQrPage = lazy(() => import('./pages/WorktimeQrPage').then((module) => ({ default: module.WorktimeQrPage })))
const HRWorkspacePage = lazy(() => import('./pages/HRWorkspacePage'))
const ProjectsWorkspacePage = lazy(() => import('./pages/ProjectsWorkspacePage').then((module) => ({ default: module.ProjectsWorkspacePage })))
const EnterpriseTasksPage = lazy(() => import('./pages/EnterpriseTasksPage').then((module) => ({ default: module.EnterpriseTasksPage })))
const CalendarWorkspacePage = lazy(() => import('./pages/CalendarWorkspacePage').then((module) => ({ default: module.CalendarWorkspacePage })))
const StatsWorkspacePage = lazy(() => import('./pages/StatsWorkspacePage').then((module) => ({ default: module.StatsWorkspacePage })))
const EnterpriseReportsPage = lazy(() => import('./pages/EnterpriseReportsPage').then((module) => ({ default: module.EnterpriseReportsPage })))
const ChartOfAccountsPage = lazy(() => import('./pages/ChartOfAccountsPage').then((module) => ({ default: module.ChartOfAccountsPage })))
const CRMWorkspacePage = lazy(() => import('./pages/CRMWorkspacePage').then((module) => ({ default: module.CRMWorkspacePage })))
const BudgetWorkspacePage = lazy(() => import('./pages/BudgetWorkspacePage').then((module) => ({ default: module.BudgetWorkspacePage })))
const PayrollWorkspacePage = lazy(() => import('./pages/PayrollWorkspacePage').then((module) => ({ default: module.PayrollWorkspacePage })))
const CapacityWorkspacePage = lazy(() => import('./pages/CapacityWorkspacePage').then((module) => ({ default: module.CapacityWorkspacePage })))
const PlansPage = lazy(() => import('./pages/PlansPage').then((module) => ({ default: module.PlansPage })))
const ContractsWorkspacePage = lazy(() => import('./pages/ContractsWorkspacePage').then((module) => ({ default: module.ContractsWorkspacePage })))
const ContractArchiveWorkspace = lazy(() => import('./components/ContractArchiveWorkspace').then((module) => ({ default: module.ContractArchiveWorkspace })))
const ContractPrintPage = lazy(() => import('./pages/ContractsWorkspacePage').then((module) => ({ default: module.ContractPrintPage })))
const AdministrationHubPage = lazy(() => import('./pages/AdministrationSettingsPages').then((module) => ({ default: module.AdministrationHubPage })))
const WorkspaceIdentitySettingsPage = lazy(() => import('./pages/AdministrationSettingsPages').then((module) => ({ default: module.WorkspaceIdentitySettingsPage })))
const CollaborationSettingsPage = lazy(() => import('./pages/AdministrationSettingsPages').then((module) => ({ default: module.CollaborationSettingsPage })))
const ReportSettingsPage = lazy(() => import('./pages/AdministrationSettingsPages').then((module) => ({ default: module.ReportSettingsPage })))
const PermissionsSettingsPage = lazy(() => import('./pages/AdministrationSettingsPages').then((module) => ({ default: module.PermissionsSettingsPage })))
const AccessControlSettingsPage = lazy(() => import('./pages/AdministrationSettingsPages').then((module) => ({ default: module.AccessControlSettingsPage })))
const AutomationSettingsPage = lazy(() => import('./pages/AdministrationSettingsPages').then((module) => ({ default: module.AutomationSettingsPage })))
const ERPSettingsPage = lazy(() => import('./pages/AdministrationSettingsPages').then((module) => ({ default: module.ERPSettingsPage })))
const DomainSettingsPage = lazy(() => import('./pages/AdministrationSettingsPages').then((module) => ({ default: module.DomainSettingsPage })))
const AdminAccessSettingsPage = lazy(() => import('./pages/AdministrationSettingsPages').then((module) => ({ default: module.AdminAccessSettingsPage })))
const LicenseSettingsPage = lazy(() => import('./pages/AdministrationSettingsPages').then((module) => ({ default: module.LicenseSettingsPage })))
const OyunsAssistantSettingsPage = lazy(() => import('./pages/AdministrationSettingsPages').then((module) => ({ default: module.OyunsAssistantSettingsPage })))
const ProfilePage = lazy(() => import('./pages/ProfilePage').then((module) => ({ default: module.ProfilePage })))
const DocsPage = lazy(() => import('./pages/DocsPage').then((module) => ({ default: module.DocsPage })))
const CompanyFilesPage = lazy(() => import('./pages/CompanyFilesPage').then((module) => ({ default: module.CompanyFilesPage })))
const ChatWorkspacePage = lazy(() => import('./pages/ChatWorkspacePage').then((module) => ({ default: module.ChatWorkspacePage })))
const TgMiniAppPage = lazy(() => import('./pages/TgMiniAppPage').then((module) => ({ default: module.TgMiniAppPage })))
const PrivacyPage = lazy(() => import('./pages/LegalPages').then((module) => ({ default: module.PrivacyPage })))
const TermsPage = lazy(() => import('./pages/LegalPages').then((module) => ({ default: module.TermsPage })))
// Operator (superadmin) console: separate login, token and shell.
const ConsoleApp = lazy(() => import('./console/ConsoleApp'))

const MANAGEMENT_ROLES = ['admin', 'manager', 'team_lead']
const PAYROLL_ROLES = ['admin', 'hr']

function RequireRoles({ allowedRoles }: { allowedRoles: string[] }) {
  const token = useAuthStore((state) => state.token)
  const actor = useActor(Boolean(token))

  if (!token) return <Navigate to="/" replace />
  if (actor.isError && !actor.data) return <SessionBootstrapError onRetry={() => void actor.refetch()} />
  if (actor.isLoading || !actor.data) return <InitialWorkspaceSkeleton />
  if (!actor.data.roles.some((role) => allowedRoles.includes(role))) return <Navigate to="/" replace />
  return <Outlet />
}

function NativeNotificationBridge() {
  const token = useAuthStore((state) => state.token)
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  useEffect(() => {
    if (!token || !isNativePlatform()) return
    const unsubscribe = notificationService.subscribeToEvents((event) => {
      if (event.type === 'received') void queryClient.invalidateQueries({ queryKey: ['v1', 'notifications'] })
      if (event.type === 'action') {
        void queryClient.invalidateQueries({ queryKey: ['v1', 'notifications'] })
        if (event.targetUrl) navigate(event.targetUrl)
      }
    })
    void notificationService.initialize().then(() => notificationService.syncExistingRegistration())
    return unsubscribe
  }, [navigate, queryClient, token])

  return null
}

/** Keeps the phone's office geofences and its reported state current. */
function NativeAutoWorktimeBridge() {
  const token = useAuthStore((state) => state.token)

  useEffect(() => {
    if (!token || !isNativePlatform()) return
    void syncAutoWorktime()
    const listener = NativeApp.addListener('resume', () => { void syncAutoWorktime() })
    return () => { void listener.then((handle) => handle.remove()) }
  }, [token])

  return null
}

function AuthenticatedApp() {
  const token = useAuthStore((state) => state.token)
  const initialized = useAuthStore((state) => state.initialized)
  const bootstrapFailed = useAuthStore((state) => state.bootstrapFailed)
  const queryClient = useQueryClient()
  const actor = useActor(Boolean(initialized && token))
  // The tenant requires 2FA and this session has not enrolled / entered a code yet.
  const twoFactorOwed = Boolean(actor.data?.two_factor?.required && !actor.data.two_factor.verified)
  // Stays up until the step is finished, so a background refetch cannot close
  // the dialog while the one-time recovery codes are still on screen.
  const [twoFactorGate, setTwoFactorGate] = useState(false)
  const tenant = useTenantContext(Boolean(token && actor.data && !twoFactorOwed))
  const isAdmin = Boolean(actor.data?.account_roles?.includes('admin') ?? actor.data?.roles.includes('admin'))
  useLicenseGraceNotice(tenant.data, isAdmin)
  const previousToken = useRef<string | null>(null)

  useEffect(() => {
    if (previousToken.current && !token) {
      useWorkspaceModeStore.getState().reset()
      void clearAuthenticatedQueryCache(queryClient)
    }
    previousToken.current = token
  }, [queryClient, token])

  useEffect(() => {
    if (!initialized) bootstrapSession()
  }, [initialized])

  useEffect(() => {
    if (!token) setTwoFactorGate(false)
    else if (twoFactorOwed) setTwoFactorGate(true)
  }, [token, twoFactorOwed])

  const refetchActor = actor.refetch
  useEffect(() => {
    // An admin switched 2FA on while this session was open: the API now
    // refuses its requests, so re-read what the session owes.
    const recheck = () => { void refetchActor({ cancelRefetch: false }) }
    window.addEventListener(TWO_FACTOR_REQUIRED_EVENT, recheck)
    return () => window.removeEventListener(TWO_FACTOR_REQUIRED_EVENT, recheck)
  }, [refetchActor])

  // The lock sits outside the session checks: on a cold start it prompts at once while the
  // stored session is restored behind it, and the login screen never waits for a fingerprint.
  const content = () => {
    if (!initialized) return <InitialWorkspaceSkeleton />
    if (!token && bootstrapFailed) return <SessionBootstrapError onRetry={() => { useAuthStore.getState().setInitialized(false) }} />
    if (!token) return <LoginPage />
    const unavailable = tenancyError(actor.error)?.code
    if (actor.isError && !actor.data && isWorkspaceUnavailable(unavailable)) return <WorkspaceUnavailableScreen code={unavailable} />
    if (actor.isError && !actor.data) return <SessionBootstrapError onRetry={() => void actor.refetch()} />
    if (actor.isLoading || !actor.data) return <InitialWorkspaceSkeleton />
    if (twoFactorOwed || twoFactorGate) {
      return <>
        <InitialWorkspaceSkeleton />
        <TwoFactorGate enrolled={Boolean(actor.data.two_factor?.enrolled)} onDone={() => { void actor.refetch().finally(() => setTwoFactorGate(false)) }} />
      </>
    }
    // Without a valid license the API only answers the activation endpoints.
    if (tenant.data && (tenant.data.license.state === 'missing' || tenant.data.license.state === 'expired')) {
      return <LicenseRequiredScreen context={tenant.data} isAdmin={isAdmin} />
    }

    return (
      <CallProvider>
        <NativeNotificationBridge />
        <NativeAutoWorktimeBridge />
        <Routes>
        <Route element={<EnterpriseShell />}>
          <Route index element={<EnterpriseDashboardPage />} />
          <Route path="worktime" element={<WorktimePage />} />
          <Route path="hr" element={<HRWorkspacePage />} />
          <Route path="projects" element={<ProjectsWorkspacePage />} />
          <Route path="tasks" element={<EnterpriseTasksPage />} />
          <Route path="calendar" element={<CalendarWorkspacePage />} />
          <Route path="reports" element={<EnterpriseReportsPage />} />
          <Route path="capacity" element={<CapacityWorkspacePage />} />
          <Route path="plans" element={<PlansPage />} />
          <Route path="contracts" element={<ContractsWorkspacePage />} />
          <Route path="contracts/archive" element={<ContractArchiveWorkspace />} />
          <Route path="contracts/:publicId" element={<ContractsWorkspacePage />} />
          <Route path="okrs" element={<Navigate to="/plans" replace />} />
          <Route path="analytics" element={<StatsWorkspacePage />} />
          {/* ERP modules are switched on in Settings → Modules; there is no ERP hub page. */}
          <Route path="erp" element={<Navigate to="/administration/organization/modules" replace />} />
          {/* CRM is authorized by ERP capabilities (e.g. the Sales role), not system roles. */}
          <Route path="erp/crm" element={<CRMWorkspacePage />} />
          <Route path="erp/crm/customers" element={<CRMWorkspacePage />} />
          <Route path="erp/crm/customers/:partyId" element={<CRMWorkspacePage />} />
          <Route path="erp/crm/settings" element={<CRMWorkspacePage />} />
          {/* Budget is authorized by ERP capabilities (budget / budget_settings), like CRM. */}
          {/* Chart of accounts is authorized by the ERP `accounts` capability (Accountant, admin; manager/team_lead view). */}
          <Route path="erp/accounts" element={<ChartOfAccountsPage />} />
          <Route path="erp/budget" element={<BudgetWorkspacePage />} />
          <Route path="erp/budget/analysis" element={<BudgetWorkspacePage />} />
          <Route path="erp/budget/accounts" element={<BudgetWorkspacePage />} />
          <Route path="erp/budget/:budgetId" element={<BudgetWorkspacePage />} />
          <Route element={<RequireRoles allowedRoles={PAYROLL_ROLES} />}>
            <Route path="erp/payroll" element={<PayrollWorkspacePage />} />
            <Route path="erp/payroll/setup" element={<PayrollWorkspacePage />} />
            <Route path="erp/payroll/inputs" element={<PayrollWorkspacePage />} />
            <Route path="erp/payroll/reports" element={<PayrollWorkspacePage />} />
            <Route path="erp/payroll/monthly" element={<PayrollWorkspacePage />} />
            <Route path="erp/payroll/monthly/reports" element={<PayrollWorkspacePage />} />
            <Route path="erp/payroll/monthly/runs/:runId" element={<PayrollWorkspacePage />} />
            <Route path="erp/payroll/monthly/settings" element={<PayrollWorkspacePage />} />
            <Route path="erp/payroll/monthly/archive" element={<PayrollWorkspacePage />} />
            <Route path="erp/payroll/tax-benefits" element={<Navigate to="/erp/payroll" replace />} />
            <Route path="erp/payroll/runs/new" element={<PayrollWorkspacePage />} />
            <Route path="erp/payroll/runs/:runId" element={<PayrollWorkspacePage />} />
            <Route path="erp/payroll/payroll-entries" element={<PayrollWorkspacePage />} />
            <Route path="erp/payroll/payroll-entries/new" element={<PayrollWorkspacePage />} />
            <Route path="erp/payroll/payroll-entries/:entryId" element={<PayrollWorkspacePage />} />
            <Route path="erp/payroll/salary-components" element={<PayrollWorkspacePage />} />
            <Route path="erp/payroll/payroll-periods" element={<PayrollWorkspacePage />} />
            <Route path="erp/payroll/salary-structures" element={<PayrollWorkspacePage />} />
            <Route path="erp/payroll/accounting" element={<PayrollWorkspacePage />} />
            <Route path="erp/payroll/additional-salaries" element={<PayrollWorkspacePage />} />
            <Route path="erp/payroll/assignments" element={<PayrollWorkspacePage />} />
            <Route path="erp/payroll/salary-slips" element={<PayrollWorkspacePage />} />
            <Route path="erp/payroll/reports/salary-register" element={<PayrollWorkspacePage />} />
            <Route path="erp/payroll/reports/bank-remittance" element={<PayrollWorkspacePage />} />
          </Route>
          <Route element={<RequireRoles allowedRoles={MANAGEMENT_ROLES} />}>
            <Route path="announcements" element={<AnnouncementsPage />} />
            <Route path="administration" element={<AdministrationHubPage />} />
            <Route path="administration/organization/profile" element={<WorkspaceIdentitySettingsPage />} />
            <Route path="administration/workflows/worktime" element={<CollaborationSettingsPage />} />
            <Route path="administration/workflows/reports" element={<ReportSettingsPage />} />
            <Route path="administration/integrations/overview" element={<AutomationSettingsPage />} />
          </Route>
          <Route path="administration/ai/knowledge" element={<OyunsAssistantSettingsPage />} />
          <Route element={<RequireRoles allowedRoles={['admin']} />}>
            <Route path="administration/people/users" element={<AccessControlSettingsPage />} />
            <Route path="administration/organization/modules" element={<ERPSettingsPage />} />
            <Route path="administration/organization/domains" element={<DomainSettingsPage />} />
            <Route path="administration/security/authentication" element={<AdminAccessSettingsPage />} />
            <Route path="administration/security/license" element={<LicenseSettingsPage />} />
          </Route>
          <Route element={<RequireRoles allowedRoles={['admin', 'manager']} />}>
            <Route path="administration/people/permissions" element={<PermissionsSettingsPage />} />
          </Route>
          <Route path="profile" element={<ProfilePage />} />
          <Route path="company-files" element={<CompanyFilesPage />} />
          <Route path="docs" element={<DocsPage />} />
          <Route path="docs/:articleId" element={<DocsPage />} />
          <Route path="chat/:conversationId?" element={<ChatWorkspacePage />} />
          <Route path="administration/workspace" element={<Navigate to="/administration/organization/profile" replace />} />
          <Route path="administration/collaboration" element={<Navigate to="/administration/workflows/worktime" replace />} />
          <Route path="administration/automation" element={<Navigate to="/administration/integrations/overview" replace />} />
          <Route path="administration/oyuns" element={<Navigate to="/administration/ai/knowledge" replace />} />
          <Route path="administration/access" element={<Navigate to="/administration/people/users" replace />} />
          <Route path="administration/erp" element={<Navigate to="/administration/organization/modules" replace />} />
          <Route path="administration/admin-access" element={<Navigate to="/administration/security/authentication" replace />} />
          <Route path="legacy/employees" element={<Navigate to="/administration/people/users" replace />} />
          <Route path="legacy/questions" element={<Navigate to="/administration/workflows/worktime" replace />} />
          <Route path="legacy/schedule" element={<Navigate to="/administration/workflows/worktime" replace />} />
          <Route path="legacy/manager" element={<Navigate to="/administration/integrations/overview" replace />} />
          <Route path="legacy/knowledge" element={<Navigate to="/administration/ai/knowledge" replace />} />
          <Route path="legacy/onboarding" element={<Navigate to="/administration/people/users" replace />} />
          <Route path="legacy/developer" element={<Navigate to="/administration/ai/knowledge" replace />} />
        </Route>
        <Route path="contracts/:publicId/print" element={<ContractPrintPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </CallProvider>
    )
  }

  return <BiometricLockGate active={!initialized || Boolean(token)}>{content()}</BiometricLockGate>
}

function SessionBootstrapError({ onRetry }: { onRetry: () => void }) {
  const { t } = useTranslation()
  return <main className="workspace-bootstrap-error" role="alert"><div className="query-region-state"><strong>{t('common.workspaceOpenFailed')}</strong><button className="secondary-action" type="button" onClick={onRetry}>{t('common.retry')}</button></div></main>
}

export default function App() {
  return (
    <BrowserRouter>
      <RouteLoadErrorBoundary>
        <Suspense fallback={<InitialWorkspaceSkeleton />}>
          <Routes>
            <Route path="/tg" element={<TgMiniAppPage />} />
            <Route path="/worktimeqr" element={<WorktimeQrPage />} />
            <Route path="/privacy" element={<PrivacyPage />} />
            <Route path="/terms" element={<TermsPage />} />
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />
            <Route path="/platform/*" element={<ConsoleApp />} />
            <Route path="/*" element={<AuthenticatedApp />} />
          </Routes>
        </Suspense>
      </RouteLoadErrorBoundary>
    </BrowserRouter>
  )
}
