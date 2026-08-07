import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { bootstrapSession } from './api/enterprise'
import { EnterpriseShell } from './components/EnterpriseShell'
import { useAuthStore } from './store/auth'
import { LoginPage } from './pages/LoginPage'
import { ForgotPasswordPage, ResetPasswordPage } from './pages/PasswordResetPages'
import { WorkspaceSkeleton } from './components/Loading'

const EnterpriseDashboardPage = lazy(() => import('./pages/EnterpriseDashboardPage').then((module) => ({ default: module.EnterpriseDashboardPage })))
const ProjectsWorkspacePage = lazy(() => import('./pages/ProjectsWorkspacePage').then((module) => ({ default: module.ProjectsWorkspacePage })))
const EnterpriseTasksPage = lazy(() => import('./pages/EnterpriseTasksPage').then((module) => ({ default: module.EnterpriseTasksPage })))
const CalendarWorkspacePage = lazy(() => import('./pages/CalendarWorkspacePage').then((module) => ({ default: module.CalendarWorkspacePage })))
const StatsWorkspacePage = lazy(() => import('./pages/StatsWorkspacePage').then((module) => ({ default: module.StatsWorkspacePage })))
const EnterpriseReportsPage = lazy(() => import('./pages/EnterpriseReportsPage').then((module) => ({ default: module.EnterpriseReportsPage })))
const CapacityWorkspacePage = lazy(() => import('./pages/CapacityWorkspacePage').then((module) => ({ default: module.CapacityWorkspacePage })))
const PlansPage = lazy(() => import('./pages/PlansPage').then((module) => ({ default: module.PlansPage })))
const AdministrationHubPage = lazy(() => import('./pages/AdministrationHubPage').then((module) => ({ default: module.AdministrationHubPage })))
const ProfilePage = lazy(() => import('./pages/ProfilePage').then((module) => ({ default: module.ProfilePage })))
const TgMiniAppPage = lazy(() => import('./pages/TgMiniAppPage').then((module) => ({ default: module.TgMiniAppPage })))
const EmployeesPage = lazy(() => import('./pages/EmployeesPage').then((module) => ({ default: module.EmployeesPage })))
const QuestionsPage = lazy(() => import('./pages/QuestionsPage').then((module) => ({ default: module.QuestionsPage })))
const SchedulePage = lazy(() => import('./pages/SchedulePage').then((module) => ({ default: module.SchedulePage })))
const ManagerSettingsPage = lazy(() => import('./pages/ManagerSettingsPage').then((module) => ({ default: module.ManagerSettingsPage })))
const KnowledgePage = lazy(() => import('./pages/KnowledgePage').then((module) => ({ default: module.KnowledgePage })))
const OnboardingPage = lazy(() => import('./pages/OnboardingPage').then((module) => ({ default: module.OnboardingPage })))
const DeveloperPage = lazy(() => import('./pages/DeveloperPage').then((module) => ({ default: module.DeveloperPage })))
const PrivacyPage = lazy(() => import('./pages/LegalPages').then((module) => ({ default: module.PrivacyPage })))
const TermsPage = lazy(() => import('./pages/LegalPages').then((module) => ({ default: module.TermsPage })))

function AuthenticatedApp() {
  const token = useAuthStore((state) => state.token)
  const initialized = useAuthStore((state) => state.initialized)

  useEffect(() => {
    if (!initialized) bootstrapSession()
  }, [initialized])

  if (!initialized) return <div className="app-loading"><img src="/oyuns-aio-logo.png" alt="OYUNS" /><span>Ажлын орон зайг бэлтгэж байна…</span></div>
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
        <Route path="administration" element={<AdministrationHubPage />} />
        <Route path="profile" element={<ProfilePage />} />
        <Route path="legacy/employees" element={<EmployeesPage />} />
        <Route path="legacy/questions" element={<QuestionsPage />} />
        <Route path="legacy/schedule" element={<SchedulePage />} />
        <Route path="legacy/manager" element={<ManagerSettingsPage />} />
        <Route path="legacy/knowledge" element={<KnowledgePage />} />
        <Route path="legacy/onboarding" element={<OnboardingPage />} />
        <Route path="legacy/developer" element={<DeveloperPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<WorkspaceSkeleton />}>
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
