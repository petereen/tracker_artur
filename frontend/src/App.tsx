import { Suspense, useEffect, useRef } from 'react'
import { BrowserRouter, Navigate, Outlet, Route, Routes, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
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

const EnterpriseDashboardPage = lazy(() => import('./pages/EnterpriseDashboardPage').then((module) => ({ default: module.EnterpriseDashboardPage })))
const WorktimePage = lazy(() => import('./pages/WorktimePage').then((module) => ({ default: module.WorktimePage })))
const WorktimeQrPage = lazy(() => import('./pages/WorktimeQrPage').then((module) => ({ default: module.WorktimeQrPage })))
const HRWorkspacePage = lazy(() => import('./pages/HRWorkspacePage'))
const ProjectsWorkspacePage = lazy(() => import('./pages/ProjectsWorkspacePage').then((module) => ({ default: module.ProjectsWorkspacePage })))
const EnterpriseTasksPage = lazy(() => import('./pages/EnterpriseTasksPage').then((module) => ({ default: module.EnterpriseTasksPage })))
const CalendarWorkspacePage = lazy(() => import('./pages/CalendarWorkspacePage').then((module) => ({ default: module.CalendarWorkspacePage })))
const StatsWorkspacePage = lazy(() => import('./pages/StatsWorkspacePage').then((module) => ({ default: module.StatsWorkspacePage })))
const EnterpriseReportsPage = lazy(() => import('./pages/EnterpriseReportsPage').then((module) => ({ default: module.EnterpriseReportsPage })))
const ERPWorkspacePage = lazy(() => import('./pages/ERPWorkspacePage').then((module) => ({ default: module.ERPWorkspacePage })))
const PayrollWorkspacePage = lazy(() => import('./pages/PayrollWorkspacePage').then((module) => ({ default: module.PayrollWorkspacePage })))
const TaxBenefitsWorkspacePage = lazy(() => import('./pages/TaxBenefitsWorkspacePage').then((module) => ({ default: module.TaxBenefitsWorkspacePage })))
const CapacityWorkspacePage = lazy(() => import('./pages/CapacityWorkspacePage').then((module) => ({ default: module.CapacityWorkspacePage })))
const PlansPage = lazy(() => import('./pages/PlansPage').then((module) => ({ default: module.PlansPage })))
const ContractsWorkspacePage = lazy(() => import('./pages/ContractsWorkspacePage').then((module) => ({ default: module.ContractsWorkspacePage })))
const ContractArchiveWorkspace = lazy(() => import('./components/ContractArchiveWorkspace').then((module) => ({ default: module.ContractArchiveWorkspace })))
const ContractPrintPage = lazy(() => import('./pages/ContractsWorkspacePage').then((module) => ({ default: module.ContractPrintPage })))
const AdministrationHubPage = lazy(() => import('./pages/AdministrationSettingsPages').then((module) => ({ default: module.AdministrationHubPage })))
const WorkspaceIdentitySettingsPage = lazy(() => import('./pages/AdministrationSettingsPages').then((module) => ({ default: module.WorkspaceIdentitySettingsPage })))
const CollaborationSettingsPage = lazy(() => import('./pages/AdministrationSettingsPages').then((module) => ({ default: module.CollaborationSettingsPage })))
const AccessControlSettingsPage = lazy(() => import('./pages/AdministrationSettingsPages').then((module) => ({ default: module.AccessControlSettingsPage })))
const AutomationSettingsPage = lazy(() => import('./pages/AdministrationSettingsPages').then((module) => ({ default: module.AutomationSettingsPage })))
const ERPSettingsPage = lazy(() => import('./pages/AdministrationSettingsPages').then((module) => ({ default: module.ERPSettingsPage })))
const AdminAccessSettingsPage = lazy(() => import('./pages/AdministrationSettingsPages').then((module) => ({ default: module.AdminAccessSettingsPage })))
const OyunsAssistantSettingsPage = lazy(() => import('./pages/AdministrationSettingsPages').then((module) => ({ default: module.OyunsAssistantSettingsPage })))
const ProfilePage = lazy(() => import('./pages/ProfilePage').then((module) => ({ default: module.ProfilePage })))
const CompanyFilesPage = lazy(() => import('./pages/CompanyFilesPage').then((module) => ({ default: module.CompanyFilesPage })))
const ChatWorkspacePage = lazy(() => import('./pages/ChatWorkspacePage').then((module) => ({ default: module.ChatWorkspacePage })))
const TgMiniAppPage = lazy(() => import('./pages/TgMiniAppPage').then((module) => ({ default: module.TgMiniAppPage })))
const PrivacyPage = lazy(() => import('./pages/LegalPages').then((module) => ({ default: module.PrivacyPage })))
const TermsPage = lazy(() => import('./pages/LegalPages').then((module) => ({ default: module.TermsPage })))

const MANAGEMENT_ROLES = ['admin', 'manager', 'team_lead']
const ERP_ROLES = ['admin', 'manager', 'team_lead']
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

function AuthenticatedApp() {
  const token = useAuthStore((state) => state.token)
  const initialized = useAuthStore((state) => state.initialized)
  const queryClient = useQueryClient()
  const actor = useActor(Boolean(initialized && token))
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

  if (!initialized) return <InitialWorkspaceSkeleton />
  if (!token) return <LoginPage />
  if (actor.isError && !actor.data) return <SessionBootstrapError onRetry={() => void actor.refetch()} />
  if (actor.isLoading || !actor.data) return <InitialWorkspaceSkeleton />

  return (
    <CallProvider>
      <NativeNotificationBridge />
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
        <Route element={<RequireRoles allowedRoles={ERP_ROLES} />}>
          <Route path="erp" element={<ERPWorkspacePage />} />
        </Route>
        <Route element={<RequireRoles allowedRoles={PAYROLL_ROLES} />}>
          <Route path="erp/payroll" element={<PayrollWorkspacePage />} />
          <Route path="erp/payroll/setup" element={<PayrollWorkspacePage />} />
          <Route path="erp/payroll/tax-benefits" element={<TaxBenefitsWorkspacePage />} />
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
          <Route path="administration" element={<AdministrationHubPage />} />
          <Route path="administration/workspace" element={<WorkspaceIdentitySettingsPage />} />
          <Route path="administration/collaboration" element={<CollaborationSettingsPage />} />
          <Route path="administration/automation" element={<AutomationSettingsPage />} />
          <Route path="administration/oyuns" element={<OyunsAssistantSettingsPage />} />
        </Route>
        <Route element={<RequireRoles allowedRoles={['admin']} />}>
          <Route path="administration/access" element={<AccessControlSettingsPage />} />
          <Route path="administration/erp" element={<ERPSettingsPage />} />
          <Route path="administration/admin-access" element={<AdminAccessSettingsPage />} />
        </Route>
        <Route path="profile" element={<ProfilePage />} />
        <Route path="company-files" element={<CompanyFilesPage />} />
        <Route path="chat/:conversationId?" element={<ChatWorkspacePage />} />
        <Route path="legacy/employees" element={<Navigate to="/administration/access" replace />} />
        <Route path="legacy/questions" element={<Navigate to="/administration/collaboration" replace />} />
        <Route path="legacy/schedule" element={<Navigate to="/administration/collaboration" replace />} />
        <Route path="legacy/manager" element={<Navigate to="/administration/automation" replace />} />
        <Route path="legacy/knowledge" element={<Navigate to="/administration/oyuns" replace />} />
        <Route path="legacy/onboarding" element={<Navigate to="/administration/automation" replace />} />
        <Route path="legacy/developer" element={<Navigate to="/administration/oyuns" replace />} />
      </Route>
      <Route path="contracts/:publicId/print" element={<ContractPrintPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </CallProvider>
  )
}

function SessionBootstrapError({ onRetry }: { onRetry: () => void }) {
  return <main className="workspace-bootstrap-error" role="alert"><div className="query-region-state"><strong>Ажлын орон зайг нээж чадсангүй.</strong><button className="secondary-action" type="button" onClick={onRetry}>Дахин оролдох</button></div></main>
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
            <Route path="/*" element={<AuthenticatedApp />} />
          </Routes>
        </Suspense>
      </RouteLoadErrorBoundary>
    </BrowserRouter>
  )
}
