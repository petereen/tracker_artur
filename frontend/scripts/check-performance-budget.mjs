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
  const visited = new Set()
  // `imports` holds manifest keys (shared chunks are keyed `_name-hash.js`,
  // entries by source path); `file` is `assets/<name>`, while `sizes` is keyed
  // by the bare file name.
  const visit = (key) => {
    if (visited.has(key)) return
    const entry = manifest[key]
    if (!entry) return
    visited.add(key)
    entry.imports?.forEach(visit)
  }
  visit('index.html')
  // The active language's catalogue is imported before first render (src/i18n.ts); count the
  // largest one so the figure holds for every language.
  const bundleSize = (key) => sizes.get(manifest[key].file.replace(/^assets\//, '')) || 0
  const catalogues = Object.keys(manifest).filter((key) => key.startsWith('virtual:oyuns-locale/')).sort((a, b) => bundleSize(b) - bundleSize(a))
  if (catalogues[0]) visit(catalogues[0])
  const dashboard = Object.entries(manifest).find(([, value]) => value.src === 'src/pages/EnterpriseDashboardPage.tsx')
  if (dashboard) visit(dashboard[0])
  return new Set([...visited].map((key) => manifest[key].file.replace(/^assets\//, '')).filter((file) => sizes.has(file)))
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
