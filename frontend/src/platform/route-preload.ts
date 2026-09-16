const routeLoaders: Record<string, () => Promise<unknown>> = {
  '/': () => import('../pages/EnterpriseDashboardPage'),
  '/worktime': () => import('../pages/WorktimePage'),
  '/hr': () => import('../pages/HRWorkspacePage'),
  '/calendar': () => import('../pages/CalendarWorkspacePage'),
  '/tasks': () => import('../pages/EnterpriseTasksPage'),
  '/chat': () => import('../pages/ChatWorkspacePage'),
  '/projects': () => import('../pages/ProjectsWorkspacePage'),
  '/reports': () => import('../pages/EnterpriseReportsPage'),
  '/analytics': () => import('../pages/StatsWorkspacePage'),
  '/contracts': () => import('../pages/ContractsWorkspacePage'),
  '/erp/payroll': () => import('../pages/PayrollWorkspacePage'),
}

const warmed = new Set<string>()

export function preloadRoute(path: string) {
  if (typeof window === 'undefined' || window.innerWidth < 768 || warmed.has(path)) return
  const loader = routeLoaders[path]
  if (!loader) return
  warmed.add(path)
  void loader().catch(() => warmed.delete(path))
}
