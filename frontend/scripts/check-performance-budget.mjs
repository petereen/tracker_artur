import { gzipSync } from 'node:zlib'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

const dist = resolve(process.cwd(), process.env.PERF_DIST || 'dist')
const assets = join(dist, 'assets')
const maxChunkGzip = 160 * 1024
const maxCriticalCssGzip = 48 * 1024
const maxShellTodayGzip = 300 * 1024

if (!statSync(assets, { throwIfNoEntry: false })) {
  console.error(`Missing ${assets}. Run npm run build first.`)
  process.exit(1)
}

const files = readdirSync(assets).filter((name) => /\.(?:js|css)$/.test(name))
const sizes = new Map(files.map((name) => [name, gzipSync(readFileSync(join(assets, name))).byteLength]))
const kb = (bytes) => `${(bytes / 1024).toFixed(1)} KiB`
const matching = (pattern) => [...sizes.entries()].filter(([name]) => pattern.test(name)).reduce((sum, [, bytes]) => sum + bytes, 0)

function manifestGraph() {
  const manifestPath = join(dist, '.vite', 'manifest.json')
  if (!statSync(manifestPath, { throwIfNoEntry: false })) return new Set()
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
  const byFile = new Map(Object.values(manifest).map((entry) => [entry.file, entry]))
  const visited = new Set()
  const visit = (file) => {
    if (visited.has(file)) return
    visited.add(file)
    const entry = byFile.get(file)
    entry?.imports?.forEach((importKey) => visit(byFile.get(importKey.replace(/^_/, ''))?.file || importKey.replace(/^_/, '')))
  }
  const entry = manifest['index.html']?.file
  if (entry) visit(entry)
  const dashboard = Object.values(manifest).find((value) => value.src === 'src/pages/EnterpriseDashboardPage.tsx')
  if (dashboard?.file) visit(dashboard.file)
  return new Set([...visited].filter((file) => sizes.has(file)))
}

const failures = []
for (const [name, bytes] of sizes) {
  if (name.endsWith('.js') && bytes > maxChunkGzip) failures.push(`${name} is ${kb(bytes)} (limit ${kb(maxChunkGzip)})`)
}

const criticalCss = matching(/^index-[^/]+\.css$/)
const graph = manifestGraph()
const shellToday = graph.size ? [...graph].reduce((sum, file) => sum + (sizes.get(file) || 0), 0) : matching(/^(?:index|vendor|lucide|EnterpriseDashboardPage|react-core|data-core|motion)-[^/]+\.js$/)
if (criticalCss > maxCriticalCssGzip) {
  const message = `critical CSS is ${kb(criticalCss)} (limit ${kb(maxCriticalCssGzip)})`
  if (process.env.PERF_STRICT_CSS === '1') failures.push(message)
  else console.warn(`Warning: ${message}; enable PERF_STRICT_CSS=1 in CI after route-style extraction.`)
}
if (shellToday > maxShellTodayGzip) failures.push(`shell + Today JS is ${kb(shellToday)} (limit ${kb(maxShellTodayGzip)})`)

console.log(`Performance budget: shell + Today JS ${kb(shellToday)} / ${kb(maxShellTodayGzip)}`)
console.log(`Performance budget: critical CSS ${kb(criticalCss)} / ${kb(maxCriticalCssGzip)}`)
console.log(`Performance budget: largest JS chunk ${kb(Math.max(0, ...[...sizes.entries()].filter(([name]) => name.endsWith('.js')).map(([, bytes]) => bytes)))} / ${kb(maxChunkGzip)}`)
if (failures.length) {
  console.error(failures.map((failure) => `- ${failure}`).join('\n'))
  process.exit(1)
}
