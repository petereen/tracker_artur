import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { bootstrapSession } from './api/enterprise'
import { EnterpriseShell } from './components/EnterpriseShell'
import { useAuthStore } from './store/auth'
import { LoginPage } from './pages/LoginPage'
import { ForgotPasswordPage, ResetPasswordPage } from './pages/PasswordResetPages'
import { InitialWorkspaceSkeleton } from './components/Loading'

const EnterpriseDashboardPage = lazy(() => import('./pages/EnterpriseDashboardPage').then((module) => ({ default: module.EnterpriseDashboardPage })))
const ProjectsWorkspacePage = lazy(() => import('./pages/ProjectsWorkspacePage').then((module) => ({ default: module.ProjectsWorkspacePage })))
const EnterpriseTasksPage = lazy(() => import('./pages/EnterpriseTasksPage').then((module) => ({ default: module.EnterpriseTasksPage })))
const CalendarWorkspacePage = lazy(() => import('./pages/CalendarWorkspacePage').then((module) => ({ default: module.CalendarWorkspacePage })))
const StatsWorkspacePage = lazy(() => import('./pages/StatsWorkspacePage').then((module) => ({ default: module.StatsWorkspacePage })))
const EnterpriseReportsPage = lazy(() => import('./pages/EnterpriseReportsPage').then((module) => ({ default: module.EnterpriseReportsPage })))
const ERPWorkspacePage = lazy(() => import('./pages/ERPWorkspacePage').then((module) => ({ default: module.ERPWorkspacePage })))
const CapacityWorkspacePage = lazy(() => import('./pages/CapacityWorkspacePage').then((module) => ({ default: module.CapacityWorkspacePage })))
const PlansPage = lazy(() => import('./pages/PlansPage').then((module) => ({ default: module.PlansPage })))
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
const TgMiniAppPage = lazy(() => import('./pages/TgMiniAppPage').then((module) => ({ default: module.TgMiniAppPage })))
const PrivacyPage = lazy(() => import('./pages/LegalPages').then((module) => ({ default: module.PrivacyPage })))
const TermsPage = lazy(() => import('./pages/LegalPages').then((module) => ({ default: module.TermsPage })))

function AuthenticatedApp() {
  const token = useAuthStore((state) => state.token)
  const initialized = useAuthStore((state) => state.initialized)

  useEffect(() => {
    if (!initialized) bootstrapSession()
  }, [initialized])

  if (!initialized) return <InitialWorkspaceSkeleton />
  if (!token) return <LoginPage />

  return (
    <Routes>
      <Route element={<EnterpriseShell />}>
        <Route index element={<EnterpriseDashboardPage />} />
        <Route path="projects" element={<ProjectsWorkspacePage />} />
        <Route path="tasks" element={<EnterpriseTasksPage />} />
        <Route path="calendar" element={<CalendarWorkspacePage />} />
        <Route path="reports" element={<EnterpriseReportsPage />} />
        <Route path="capacity" element={<CapacityWorkspacePage />} />
        <Route path="plans" element={<PlansPage />} />
        <Route path="okrs" element={<Navigate to="/plans" replace />} />
        <Route path="analytics" element={<StatsWorkspacePage />} />
        <Route path="erp" element={<ERPWorkspacePage />} />
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
        <Route path="legacy/employees" element={<Navigate to="/administration/access" replace />} />
        <Route path="legacy/questions" element={<Navigate to="/administration/collaboration" replace />} />
        <Route path="legacy/schedule" element={<Navigate to="/administration/collaboration" replace />} />
        <Route path="legacy/manager" element={<Navigate to="/administration/automation" replace />} />
        <Route path="legacy/knowledge" element={<Navigate to="/administration/oyuns" replace />} />
        <Route path="legacy/onboarding" element={<Navigate to="/administration/automation" replace />} />
        <Route path="legacy/developer" element={<Navigate to="/administration/oyuns" replace />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<InitialWorkspaceSkeleton />}>
        <Routes>
          <Route path="/tg" element={<TgMiniAppPage />} />
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
