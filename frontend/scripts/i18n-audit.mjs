#!/usr/bin/env node
// Lists source files that still hardcode Cyrillic (Mongolian/Russian) UI text
// instead of going through `t()` / src/locales. Run: npm run i18n:audit
// A line carrying an `i18n-ignore` comment is skipped (backend data values, not UI text).
// Informational by default; `--strict` exits 1 while anything is left.
//
// Limits: it only sees Cyrillic literals. English strings hardcoded in JSX are
// not detected, so a clean report is necessary but not sufficient.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const ROOT = new URL('../src', import.meta.url).pathname
const SKIP_DIRS = new Set(['locales', 'test'])
// The language switcher deliberately shows each language under its own name.
const SKIP_FILES = new Set(['i18n.ts', 'components/LanguageSwitcher.tsx'])
// Not imported anywhere (checked 2026-10-01); translate or delete before reviving.
const DEAD = new Set([
  'components/Sidebar.tsx', 'components/payroll/PayrollPaymentWorkflow.tsx', 'components/payroll/PayrollDocumentsPage.tsx',
  'components/payroll/PayrollReconciliationPanel.tsx', 'api/miniapp.ts', 'pages/JournalPage.tsx', 'pages/ReportsPage.tsx',
  'pages/TasksPage.tsx', 'pages/TaxBenefitsWorkspacePage.tsx', 'pages/PayrollSetupHub.tsx', 'pages/OkrsWorkspacePage.tsx', 'pages/DashboardPage.tsx', 'components/payroll/PayrollWorkspaceUI.tsx',
])
const CYRILLIC = /[Ѐ-ӿ]/

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return SKIP_DIRS.has(name) ? [] : walk(path)
    return /\.(ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name) ? [path] : []
  })
}

const rows = []
for (const file of walk(ROOT)) {
  const rel = relative(ROOT, file)
  if (SKIP_FILES.has(rel) || DEAD.has(rel)) continue
  const count = readFileSync(file, 'utf8').split('\n').filter((line) => CYRILLIC.test(line) && !/^\s*(\/\/|\*|\/\*)/.test(line) && !line.includes('i18n-ignore')).length
  if (count) rows.push([count, rel])
}
rows.sort((a, b) => b[0] - a[0])
for (const [count, rel] of rows) console.log(String(count).padStart(5), rel)
console.log(`\n${rows.length} files, ${rows.reduce((sum, [count]) => sum + count, 0)} lines still hardcode Cyrillic text`)
if (process.argv.includes('--strict') && rows.length) process.exit(1)
