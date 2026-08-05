import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { bootstrapSession } from './api/enterprise'
import { EnterpriseShell } from './components/EnterpriseShell'
import { useAuthStore } from './store/auth'
import { LoginPage } from './pages/LoginPage'
import { ForgotPasswordPage, ResetPasswordPage } from './pages/PasswordResetPages'

const EnterpriseDashboardPage = lazy(() => import('./pages/EnterpriseDashboardPage').then((module) => ({ default: module.EnterpriseDashboardPage })))
const ProjectsWorkspacePage = lazy(() => import('./pages/ProjectsWorkspacePage').then((module) => ({ default: module.ProjectsWorkspacePage })))
const EnterpriseTasksPage = lazy(() => import('./pages/EnterpriseTasksPage').then((module) => ({ default: module.EnterpriseTasksPage })))
const EnterpriseReportsPage = lazy(() => import('./pages/EnterpriseReportsPage').then((module) => ({ default: module.EnterpriseReportsPage })))
const CapacityWorkspacePage = lazy(() => import('./pages/CapacityWorkspacePage').then((module) => ({ default: module.CapacityWorkspacePage })))
const OkrsWorkspacePage = lazy(() => import('./pages/OkrsWorkspacePage').then((module) => ({ default: module.OkrsWorkspacePage })))
const AdministrationHubPage = lazy(() => import('./pages/AdministrationHubPage').then((module) => ({ default: module.AdministrationHubPage })))
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
        <Route path="reports" element={<EnterpriseReportsPage />} />
        <Route path="capacity" element={<CapacityWorkspacePage />} />
        <Route path="okrs" element={<OkrsWorkspacePage />} />
        <Route path="analytics" element={<EnterpriseDashboardPage />} />
        <Route path="administration" element={<AdministrationHubPage />} />
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
      <Suspense fallback={<div className="app-loading"><img src="/oyuns-aio-logo.png" alt="OYUNS" /><span>Ачаалж байна…</span></div>}>
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
