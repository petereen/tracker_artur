import { useDeferredValue, useEffect, useMemo, useRef, useState } from 'react'
import { BriefcaseBusiness, CheckSquare2, File, Folder, Keyboard, LayoutDashboard, Search, Settings2, Upload, UserCircle2, Users2, X, type LucideIcon } from 'lucide-react'
import { useGlobalSearch, type GlobalSearchResult } from '../api/enterprise'

type LocalItem = { id: string; type: 'channel' | 'feature'; title: string; subtitle: string; icon: LucideIcon; run: () => void }
type Item = LocalItem | GlobalSearchResult
const RECENT_LIMIT = 8

function formatSize(bytes?: number | null) { if (!bytes) return ''; return bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB` }

export function GlobalCommandBar({ open, onClose, accountId, channels, features, onWorker }: { open: boolean; onClose: () => void; accountId?: number; channels: LocalItem[]; features: LocalItem[]; onWorker: (id: number) => void }) {
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const previousFocus = useRef<HTMLElement | null>(null)
  const deferredQuery = useDeferredValue(query.trim())
  const search = useGlobalSearch(deferredQuery)
  const storageKey = `oyuns-command-recents:${accountId ?? 'anonymous'}`
  const [recents, setRecents] = useState<string[]>([])
  useEffect(() => { if (open) { previousFocus.current = document.activeElement as HTMLElement; setTimeout(() => input.current?.focus()); try { setRecents(JSON.parse(localStorage.getItem(storageKey) || '[]')) } catch { setRecents([]) } } else previousFocus.current?.focus() }, [open, storageKey])
  const localMatches = useMemo(() => [...channels, ...features].filter((item) => !deferredQuery || `${item.title} ${item.subtitle}`.toLocaleLowerCase().includes(deferredQuery.toLocaleLowerCase())), [channels, features, deferredQuery])
  const items = useMemo<Item[]>(() => deferredQuery ? [...(search.data?.groups.tasks ?? []), ...(search.data?.groups.workers ?? []), ...(search.data?.groups.files ?? []), ...localMatches] : [...channels, ...features], [channels, features, deferredQuery, search.data, localMatches])
  useEffect(() => setActive(0), [deferredQuery, open])
  const record = (value: string) => { const next = [value, ...recents.filter((item) => item !== value)].slice(0, RECENT_LIMIT); setRecents(next); localStorage.setItem(storageKey, JSON.stringify(next)) }
  const select = (item: Item) => {
    if ('run' in item) { item.run(); onClose(); return }
    if (query.trim()) record(query.trim())
    if (item.type === 'task') location.assign(`/tasks?task=${item.id}`)
    if (item.type === 'worker') { onWorker(item.id); onClose() }
    if (item.type === 'file') location.assign(`/company-files?parent=${item.metadata.kind === 'folder' ? item.id : item.metadata.parent_id ?? ''}&item=${item.id}`)
  }
  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Escape') { event.preventDefault(); onClose() }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); setActive((current) => items.length ? (current + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length : 0) }
    if (event.key === 'Enter' && items[active]) { event.preventDefault(); select(items[active]) }
  }
  if (!open) return null
  let cursor = 0
  const row = (item: Item) => { const index = cursor++; const selected = index === active; const Icon = 'run' in item ? item.icon : item.type === 'task' ? CheckSquare2 : item.type === 'worker' ? Users2 : item.metadata.kind === 'folder' ? Folder : File; const subtitle = 'run' in item ? item.subtitle : item.type === 'task' ? `${item.metadata.status ?? ''}${item.metadata.assignee ? ` · ${item.metadata.assignee}` : ''}${item.metadata.project ? ` · ${item.metadata.project}` : ''}` : item.type === 'worker' ? `${item.metadata.role ?? item.subtitle ?? ''} · ${item.metadata.presence ?? 'offline'}` : `${item.subtitle ?? ''}${formatSize(item.metadata.size) ? ` · ${formatSize(item.metadata.size)}` : ''}`; return <button key={`${'run' in item ? item.id : `${item.type}-${item.id}`}`} id={`command-item-${index}`} className={selected ? 'is-active' : ''} role="option" aria-selected={selected} onMouseMove={() => setActive(index)} onClick={() => select(item)}><span className="command-result-icon"><Icon size={17} /></span><span className="command-result-copy"><strong>{item.title}</strong><small>{subtitle}</small></span>{selected && <kbd>↵</kbd>}</button> }
  const group = (title: string, values: Item[]) => values.length ? <section className="command-group" key={title}><h3>{title}</h3>{values.map(row)}</section> : null
  const taskResults = search.data?.groups.tasks ?? []; const workerResults = search.data?.groups.workers ?? []; const fileResults = search.data?.groups.files ?? []
  return <div className="command-backdrop" onMouseDown={onClose}><div className="command-panel global-command-panel" role="dialog" aria-modal="true" aria-label="Global search" onMouseDown={(event) => event.stopPropagation()} onKeyDown={onKeyDown}><div className="command-input"><Search size={18} /><input ref={input} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search tasks, people, files, or features…" role="combobox" aria-expanded aria-controls="command-results" aria-activedescendant={items[active] ? `command-item-${active}` : undefined} /><kbd>Esc</kbd></div><div className="command-list" id="command-results" role="listbox">{!deferredQuery && recents.length > 0 && <section className="command-recents"><div><h3>Recent searches</h3><button onClick={() => { setRecents([]); localStorage.removeItem(storageKey) }}>Clear</button></div>{recents.map((item) => <button key={item} onClick={() => setQuery(item)}><Keyboard size={15} />{item}</button>)}</section>}{deferredQuery ? <>{group('Tasks', taskResults)}{group('Workers', workerResults)}{group('Files', fileResults)}{group('Workspace', localMatches)}{search.isFetching && <p className="command-state">Searching…</p>}{!search.isFetching && items.length === 0 && <p className="command-state">No results found.</p>}</> : <>{group('Workspace', channels)}{group('Quick actions', features)}</>}</div></div></div>
}

export const commandIcons = { LayoutDashboard, BriefcaseBusiness, Settings2, Upload, UserCircle2 }
