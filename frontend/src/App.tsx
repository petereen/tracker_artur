import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { bootstrapSession } from './api/enterprise'
import { EnterpriseShell } from './components/EnterpriseShell'
import { useAuthStore } from './store/auth'
import { LoginPage } from './pages/LoginPage'
import { ForgotPasswordPage, ResetPasswordPage } from './pages/PasswordResetPages'
import { InitialWorkspaceSkeleton } from './components/Loading'
import { notificationService } from './platform/notifications'
import { isNativePlatform } from './platform/runtime'
import { CallProvider } from './components/CallProvider'

const EnterpriseDashboardPage = lazy(() => import('./pages/EnterpriseDashboardPage').then((module) => ({ default: module.EnterpriseDashboardPage })))
const WorktimePage = lazy(() => import('./pages/WorktimePage').then((module) => ({ default: module.WorktimePage })))
const WorktimeQrPage = lazy(() => import('./pages/WorktimeQrPage').then((module) => ({ default: module.WorktimeQrPage })))
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

  useEffect(() => {
    if (!initialized) bootstrapSession()
  }, [initialized])

  if (!initialized) return <InitialWorkspaceSkeleton />
  if (!token) return <LoginPage />

  return (
    <CallProvider>
      <NativeNotificationBridge />
      <Routes>
      <Route element={<EnterpriseShell />}>
        <Route index element={<EnterpriseDashboardPage />} />
        <Route path="worktime" element={<WorktimePage />} />
        <Route path="projects" element={<ProjectsWorkspacePage />} />
        <Route path="tasks" element={<EnterpriseTasksPage />} />
        <Route path="calendar" element={<CalendarWorkspacePage />} />
        <Route path="reports" element={<EnterpriseReportsPage />} />
        <Route path="capacity" element={<CapacityWorkspacePage />} />
        <Route path="plans" element={<PlansPage />} />
        <Route path="contracts" element={<ContractsWorkspacePage />} />
        <Route path="contracts/:publicId" element={<ContractsWorkspacePage />} />
        <Route path="okrs" element={<Navigate to="/plans" replace />} />
        <Route path="analytics" element={<StatsWorkspacePage />} />
        <Route path="erp" element={<ERPWorkspacePage />} />
        <Route path="erp/payroll" element={<PayrollWorkspacePage />} />
        <Route path="erp/payroll/tax-benefits" element={<TaxBenefitsWorkspacePage />} />
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
        <Route path="administration" element={<AdministrationHubPage />} />
        <Route path="administration/workspace" element={<WorkspaceIdentitySettingsPage />} />
        <Route path="administration/collaboration" element={<CollaborationSettingsPage />} />
        <Route path="administration/access" element={<AccessControlSettingsPage />} />
        <Route path="administration/automation" element={<AutomationSettingsPage />} />
        <Route path="administration/erp" element={<ERPSettingsPage />} />
        <Route path="administration/admin-access" element={<AdminAccessSettingsPage />} />
        <Route path="administration/oyuns" element={<OyunsAssistantSettingsPage />} />
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

export default function App() {
  return (
    <BrowserRouter>
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
    </BrowserRouter>
  )
}
