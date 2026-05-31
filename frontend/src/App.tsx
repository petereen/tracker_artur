import { useState, useEffect } from 'react'
import { useAuthStore } from './store/auth'
import { Sidebar } from './components/Sidebar'
import { LoginPage } from './pages/LoginPage'
import { DashboardPage } from './pages/DashboardPage'
import { EmployeesPage } from './pages/EmployeesPage'
import { QuestionsPage } from './pages/QuestionsPage'
import { SchedulePage } from './pages/SchedulePage'
import { JournalPage } from './pages/JournalPage'
import { ManagerSettingsPage } from './pages/ManagerSettingsPage'
import { OnboardingPage } from './pages/OnboardingPage'
import { TasksPage } from './pages/TasksPage'
import { TgMiniAppPage } from './pages/TgMiniAppPage'
import { PrivacyPage, TermsPage } from './pages/LegalPages'

// Check if this is the Telegram Mini App route
const isTgRoute = () => window.location.pathname === '/tg'

const PAGES: Record<string, JSX.Element> = {
  dashboard:  <DashboardPage />,
  employees:  <EmployeesPage />,
  tasks:      <TasksPage />,
  questions:  <QuestionsPage />,
  schedule:   <SchedulePage />,
  journal:    <JournalPage />,
  manager:    <ManagerSettingsPage />,
  onboarding: <OnboardingPage />,
}

export default function App() {
  const token = useAuthStore((s) => s.token)
  const [page, setPage] = useState('dashboard')
  const [hydrated, setHydrated] = useState(false)

  useEffect(() => {
    // Ждём пока Zustand persist прочитает localStorage
    const unsub = useAuthStore.persist.onFinishHydration(() => setHydrated(true))
    // Если hydration уже завершился — сразу выставляем
    if (useAuthStore.persist.hasHydrated()) setHydrated(true)
    return unsub
  }, [])

  // Public routes (no auth required)
  if (isTgRoute()) {
    return <TgMiniAppPage />
  }
  if (window.location.pathname === '/privacy') return <PrivacyPage />
  if (window.location.pathname === '/terms') return <TermsPage />

  if (!hydrated) {
    return (
      <div className="min-h-screen bg-bg flex items-center justify-center">
        <div className="text-muted text-sm">Загрузка...</div>
      </div>
    )
  }

  if (!token) return <LoginPage />

  return (
    <div className="flex min-h-screen">
      <Sidebar active={page} onNav={setPage} />
      <main className="flex-1 overflow-y-auto px-9 py-8 min-w-0">
        {PAGES[page]}
      </main>
    </div>
  )
}
