import { useEffect, useRef, useState } from 'react'
import { Archive, Download, File, FileArchive, FileImage, FileText, Folder, FolderPlus, Grid2X2, Info, List, LoaderCircle, MoreVertical, Pencil, Printer, Search, ShieldCheck, Trash2, Upload, Users, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { useSearchParams } from 'react-router-dom'
import { DropdownSelect } from './DropdownSelect'
import { isNativePlatform, resolvePublicAssetUrl, safeLocalStorage } from '../platform/runtime'
import { useActor, useContractArchive, useContractArchiveAccessCandidates, useContractArchiveEntryDetail, useContractArchiveFolderDetail, useContractArchiveReviewQueue, useCreateContractArchiveFolder, useDeleteContractArchiveEntry, useDeleteContractArchiveFolder, useReviewContractArchiveEntry, useUpdateContractArchiveAccess, useUpdateContractArchiveEntry, useUpdateContractArchiveFolder, useUploadContractArchiveEntry, getContractArchiveEntryBlob, downloadContractArchiveEntry, recordContractArchivePrint, ContractArchiveEntry, ContractArchiveFolder, ArchivePermission } from '../api/enterprise'

type Layout = 'list' | 'grid'
type Sheet = { kind: 'preview' | 'info'; entry: ContractArchiveEntry } | { kind: 'folder-info' | 'folder-access'; folder: ContractArchiveFolder } | null

function formatDate(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  const pad = (number: number) => String(number).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} • ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function formatSize(bytes: number | null | undefined) {
  if (bytes == null) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function extension(name: string) { return name.split('.').pop()?.toLowerCase() || '' }

function initials(name?: string | null) { return (name || '?').split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase() }

function roleLabel(role: string) {
  const labels: Record<string, string> = { admin: 'Админ', legal_counsel: 'Хуульч', manager: 'Менежер', team_lead: 'Багийн ахлагч', hr: 'Хүний нөөц', member: 'Ажилтан', contractor: 'Гэрээт', client_auditor: 'Аудитор' }
  return labels[role] || role
}

function useFocusTrap(ref: React.RefObject<HTMLElement>, onClose: () => void, active = true) {
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  useEffect(() => {
    const container = ref.current
    if (!active || !container) return
    const previous = document.activeElement as HTMLElement | null
    const focusable = () => Array.from(container.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'))
    focusable()[0]?.focus()
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); onCloseRef.current(); return }
      if (event.key !== 'Tab') return
      const items = focusable()
      if (!items.length) return
      const first = items[0]
      const last = items[items.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', handleKey)
    return () => { document.removeEventListener('keydown', handleKey); previous?.focus() }
  }, [ref, active])
}

function ItemIcon({ item, size = 20 }: { item: ContractArchiveEntry | ContractArchiveFolder; size?: number }) {
  if ('nested_item_count' in item) return <Folder size={size} />
  const ext = extension(item.name)
  if (['png', 'jpg', 'jpeg', 'tiff'].includes(ext)) return <FileImage size={size} />
  if (['zip', 'rar', '7z'].includes(ext)) return <FileArchive size={size} />
  if (['pdf', 'doc', 'docx'].includes(ext)) return <FileText size={size} />
  return <File size={size} />
}

function Person({ value }: { value: ContractArchiveEntry['author'] }) {
  if (!value) return <span className="archive-person"><span className="archive-avatar">?</span><span>—</span></span>
  return <span className="archive-person"><span className="archive-avatar">{value.avatar_url ? <img src={resolvePublicAssetUrl(value.avatar_url) || undefined} alt="" /> : initials(value.name)}</span><span>{value.name}</span></span>
}

function PreviewSheet({ entry, onClose }: { entry: ContractArchiveEntry; onClose: () => void }) {
  const [url, setUrl] = useState<string | null>(null)
  const [text, setText] = useState<string | null>(null)
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(true)
  const sheetRef = useRef<HTMLElement>(null)
  const ext = extension(entry.name)
  useFocusTrap(sheetRef, onClose)
  useEffect(() => {
    if (ext === 'doc') {
      setLoading(false)
      return
    }
    let objectUrl: string | null = null
    getContractArchiveEntryBlob(entry, false, true).then((blob) => { if (ext === 'docx') return blob.text().then(setText); objectUrl = URL.createObjectURL(blob); setUrl(objectUrl) }).catch(() => setError(true)).finally(() => setLoading(false))
    return () => { if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [entry, ext])
  const print = () => {
    if (isNativePlatform()) { toast.error('Хэвлэх үйлдэл зөвхөн web хувилбарт боломжтой.'); return }
    if (ext === 'docx' && text !== null) {
      void recordContractArchivePrint(entry).catch(() => undefined)
      const printWindow = window.open('', '_blank', 'noopener,noreferrer')
      if (printWindow) {
        const safeText = text.replace(/[&<>]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[character] || character))
        printWindow.document.write(`<pre style="font: 12px Montserrat, sans-serif; white-space: pre-wrap; line-height: 1.7">${safeText}</pre>`)
        printWindow.document.close()
        window.setTimeout(() => printWindow.print(), 300)
      }
      return
    }
    if (url) {
      void recordContractArchivePrint(entry).catch(() => undefined)
      const printWindow = window.open(url, '_blank', 'noopener,noreferrer')
      if (printWindow) window.setTimeout(() => printWindow.print(), 600)
    }
  }
  const download = () => { void downloadContractArchiveEntry(entry).catch((error: any) => toast.error(error?.message || 'Файл татаж чадсангүй')) }
  return <div className="sheet-backdrop archive-sheet-backdrop" onMouseDown={onClose}><aside ref={sheetRef} className="archive-sheet" role="dialog" aria-modal="true" aria-labelledby="archive-preview-title" onMouseDown={(event) => event.stopPropagation()}>
    <header className="archive-sheet-header"><div><span className="eyebrow">{entry.category} · {entry.signing_status}</span><h2 id="archive-preview-title">{entry.name}</h2></div><button className="icon-button" onClick={onClose} aria-label="Хаах"><X size={19} /></button></header>
    <div className="archive-sheet-meta"><span>{entry.review_status === 'pending' ? 'Хяналт хүлээж байна' : 'Архивлагдсан'}</span><span>{formatSize(entry.size)}</span><span>{entry.content_type}</span></div>
    <div className="archive-preview-canvas">{loading && <LoaderCircle className="spin" size={28} />}{error && <div className="archive-preview-error"><FileText size={32} /><p>Урьдчилан харах боломжгүй байна.</p><button className="secondary-action" onClick={download}>Татаж авах</button></div>}{!loading && !error && url && ext === 'pdf' && <iframe title={`${entry.name} preview`} src={url} />}{!loading && !error && ext === 'docx' && text !== null && <pre className="archive-docx-text">{text}</pre>}{!loading && !error && ext !== 'pdf' && ext !== 'docx' && <div className="archive-doc-preview"><FileText size={44} /><strong>{ext.toUpperCase() || 'FILE'} баримт</strong><p>Энэ төрлийн баримтыг татаж авч нээх боломжтой.</p></div>}</div>
    <div className="archive-sheet-details"><div><span>Үүсгэсэн ажилтан</span><Person value={entry.author} /></div><div><span>Үүсгэсэн огноо</span><strong>{formatDate(entry.created_at)}</strong></div><div><span>Checksum</span><code>{entry.checksum}</code></div></div>
    <footer className="archive-sheet-toolbar"><button className="secondary-action" onClick={download}><Download size={15} />Татаж авах</button><button className="secondary-action" disabled={!url && !(ext === 'docx' && text !== null)} onClick={print}><Printer size={15} />Хэвлэх</button></footer>
  </aside></div>
}

function InfoSheet({ entry, onClose }: { entry: ContractArchiveEntry; onClose: () => void }) {
  const detail = useContractArchiveEntryDetail(entry.id)
  const sheetRef = useRef<HTMLElement>(null)
  useFocusTrap(sheetRef, onClose)
  return <div className="sheet-backdrop archive-sheet-backdrop" onMouseDown={onClose}><aside ref={sheetRef} className="archive-sheet" role="dialog" aria-modal="true" aria-labelledby="archive-info-title" onMouseDown={(event) => event.stopPropagation()}><header className="archive-sheet-header"><div><span className="eyebrow">МЭДЭЭЛЭЛ</span><h2 id="archive-info-title">{entry.name}</h2></div><button className="icon-button" onClick={onClose} aria-label="Хаах"><X size={19} /></button></header><div className="archive-info-grid"><span>Төрөл</span><strong>{entry.category}</strong><span>Хэмжээ</span><strong>{formatSize(entry.size)}</strong><span>Checksum</span><code>{entry.checksum}</code><span>Үүсгэсэн</span><strong>{formatDate(entry.created_at)}</strong><span>Хянасан</span><strong>{entry.reviewed_at ? formatDate(entry.reviewed_at) : 'Хүлээж байна'}</strong></div><div className="archive-timeline"><h3>Үйл явдлын бүртгэл</h3>{detail.isLoading ? <LoaderCircle className="spin" size={20} /> : detail.data?.timeline?.length ? detail.data.timeline.map((event) => <div key={event.id}><strong>{event.operation}</strong><time>{formatDate(event.created_at)}</time></div>) : <p>Бүртгэл алга.</p>}</div></aside></div>
}

function FolderInfoSheet({ folder, onClose }: { folder: ContractArchiveFolder; onClose: () => void }) {
  const detail = useContractArchiveFolderDetail(folder.id)
  const sheetRef = useRef<HTMLElement>(null)
  useFocusTrap(sheetRef, onClose)
  return <div className="sheet-backdrop archive-sheet-backdrop" onMouseDown={onClose}><aside ref={sheetRef} className="archive-sheet" role="dialog" aria-modal="true" aria-labelledby="archive-folder-info-title" onMouseDown={(event) => event.stopPropagation()}><header className="archive-sheet-header"><div><span className="eyebrow">МЭДЭЭЛЭЛ / ХАВТАС</span><h2 id="archive-folder-info-title">{folder.name}</h2></div><button className="icon-button" onClick={onClose} aria-label="Хаах"><X size={19} /></button></header><div className="archive-info-grid"><span>Доторх зүйлс</span><strong>{folder.nested_item_count}</strong><span>Нийт хэмжээ</span><strong>{formatSize(folder.total_size)}</strong><span>Үүсгэсэн огноо</span><strong>{formatDate(folder.created_at)}</strong><span>Manifest checksum</span><code>{folder.manifest_checksum}</code></div><div className="archive-timeline"><h3>Үйл явдлын бүртгэл</h3>{detail.isLoading ? <LoaderCircle className="spin" size={20} /> : detail.data?.timeline?.length ? detail.data.timeline.map((event) => <div key={event.id}><strong>{event.operation}</strong><time>{formatDate(event.created_at)}</time></div>) : <p>Бүртгэл алга.</p>}</div></aside></div>
}

function AccessSheet({ folder, onClose }: { folder: ContractArchiveFolder; onClose: () => void }) {
  const detail = useContractArchiveFolderDetail(folder.id)
  const [candidateSearch, setCandidateSearch] = useState('')
  const candidates = useContractArchiveAccessCandidates(candidateSearch)
  const save = useUpdateContractArchiveAccess()
  const [name, setName] = useState(folder.name)
  const [description, setDescription] = useState(folder.description || '')
  const [grants, setGrants] = useState<Array<{ account_id: number; permission: ArchivePermission }>>([])
  const sheetRef = useRef<HTMLElement>(null)
  const canEditAccount = (accountId: number) => Boolean(candidates.data?.find((candidate) => candidate.account_id === accountId)?.roles.some((role) => role === 'admin' || role === 'legal_counsel'))
  useFocusTrap(sheetRef, onClose)
  useEffect(() => { if (detail.data) { setName(detail.data.name); setDescription(detail.data.description || ''); setGrants(detail.data.access.map((item) => ({ account_id: item.account_id, permission: item.permission }))) } }, [detail.data])
  const add = (accountId: number) => setGrants((current) => current.some((item) => item.account_id === accountId) ? current : [...current, { account_id: accountId, permission: 'view' }])
  const remove = (accountId: number) => setGrants((current) => current.filter((item) => item.account_id !== accountId))
  const submit = async () => { try { await save.mutateAsync({ id: folder.id, name, description, version: detail.data?.version || folder.version, grants: grants.map((grant) => ({ ...grant, permission: canEditAccount(grant.account_id) ? grant.permission : 'view' })) }); onClose() } catch {} }
  return <div className="sheet-backdrop archive-sheet-backdrop" onMouseDown={onClose}><aside ref={sheetRef} className="archive-sheet archive-access-sheet" role="dialog" aria-modal="true" aria-labelledby="archive-access-title" onMouseDown={(event) => event.stopPropagation()}><header className="archive-sheet-header"><div><span className="eyebrow">ACCESS CONTROL</span><h2 id="archive-access-title">Хавтасны тохиргоо ба хандалт</h2></div><button className="icon-button" onClick={onClose} aria-label="Хаах"><X size={19} /></button></header><div className="archive-access-body"><label>Хавтасны нэр<input value={name} onChange={(event) => setName(event.target.value)} /></label><label>Тайлбар<textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={3} /></label><div className="archive-access-section"><h3>Ажилтан оноох</h3><label className="archive-candidate-search"><Search size={15} /><input value={candidateSearch} onChange={(event) => setCandidateSearch(event.target.value)} placeholder="Ажилтан хайж нэмэх..." /></label><div className="archive-candidates">{candidates.data?.filter((candidate) => !grants.some((grant) => grant.account_id === candidate.account_id)).slice(0, 8).map((candidate) => <button key={candidate.account_id} onClick={() => add(candidate.account_id)}><span className="archive-avatar">{candidate.avatar_url ? <img src={resolvePublicAssetUrl(candidate.avatar_url) || undefined} alt="" /> : initials(candidate.name)}</span><span><strong>{candidate.name}</strong><small>{candidate.roles.length ? candidate.roles.map(roleLabel).join(', ') : 'Ажилтан'}</small></span><Users size={15} /></button>)}</div></div><div className="archive-access-section"><h3>Одоогийн хандалт</h3><div className="archive-roster">{grants.length ? grants.map((grant) => { const person = detail.data?.access.find((item) => item.account_id === grant.account_id)?.employee; const privileged = canEditAccount(grant.account_id); return <div key={grant.account_id}><Person value={person || null} /><span className="archive-role-badge">{person?.roles?.length ? person.roles.map(roleLabel).join(', ') : 'Ажилтан'}</span><span className="archive-grant-scope">Шууд</span>{privileged ? <span className="archive-grant-global">Глобал эрх</span> : <select value="view" onChange={() => undefined} aria-label={`${person?.name || 'Ажилтан'} эрх`}><option value="view">Харах</option></select>}<button className="text-button" onClick={() => remove(grant.account_id)}>Хасах</button></div> }) : <p>Одоогоор ажилтан оноогоогүй байна.</p>}</div>{!!detail.data?.inherited_access?.length && <div className="archive-inherited-access"><h3>Өвлөсөн хандалт</h3>{detail.data.inherited_access.map((grant) => <div key={grant.account_id}><Person value={grant.employee} /><span className="archive-role-badge">{grant.employee?.roles?.length ? grant.employee.roles.map(roleLabel).join(', ') : 'Ажилтан'}</span><span className="archive-grant-scope">Өвлөсөн</span><span>{grant.permission === 'edit' ? 'Засах' : 'Харах'}</span></div>)}</div>}</div></div><footer className="archive-sheet-footer"><button className="secondary-action" onClick={onClose}>Цуцлах</button><button className="primary-action" onClick={submit} disabled={save.isPending}>{save.isPending && <LoaderCircle className="spin" size={15} />}Хадгалах</button></footer></aside></div>
}

function ReviewDialog({ entry, folders, onClose }: { entry: ContractArchiveEntry; folders: ContractArchiveFolder[]; onClose: () => void }) {
  const review = useReviewContractArchiveEntry()
  const [folderId, setFolderId] = useState('')
  const [newFolder, setNewFolder] = useState(false)
  const [newFolderName, setNewFolderName] = useState('')
  const [category, setCategory] = useState(entry.category)
  const [reason, setReason] = useState('')
  const modalRef = useRef<HTMLElement>(null)
  useFocusTrap(modalRef, onClose)
  const submit = async (decision: 'approve' | 'reject') => { if (decision === 'approve' && !folderId && !newFolderName.trim()) return toast.error('Хавтас сонгох эсвэл шинээр үүсгэнэ үү'); if (decision === 'reject' && !reason.trim()) return toast.error('Буцаах шалтгаан оруулна уу'); try { await review.mutateAsync({ id: entry.id, decision, folder_id: folderId ? Number(folderId) : undefined, new_folder: newFolderName.trim() ? { name: newFolderName.trim() } : undefined, category, reason: reason.trim() || undefined }); onClose() } catch {} }
  return <div className="contract-modal-backdrop"><section ref={modalRef} className="contract-modal archive-review-dialog" role="dialog" aria-modal="true" aria-labelledby="archive-review-title"><button className="icon-button" onClick={onClose} aria-label="Хаах"><X size={18} /></button><ShieldCheck size={30} className="modal-success-icon" /><h3 id="archive-review-title">Архивын хяналт</h3><p>{entry.name}</p><label>Ангилал<input value={category} onChange={(event) => setCategory(event.target.value)} /></label><label>Одоо байгаа хавтас<select value={folderId} onChange={(event) => { setFolderId(event.target.value); setNewFolder(false); setNewFolderName('') }} disabled={newFolder}><option value="">Хавтас сонгох</option>{folders.map((folder) => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select></label><button className="text-button" onClick={() => { if (newFolder) setNewFolderName(''); setNewFolder(!newFolder); setFolderId('') }}>{newFolder ? 'Одоо байгаа хавтас сонгох' : '+ Шинэ хавтас үүсгэх'}</button>{newFolder && <label>Шинэ хавтасны нэр<input value={newFolderName} onChange={(event) => setNewFolderName(event.target.value)} /></label>}<label>Буцаах шалтгаан (шаардлагатай үед)<textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={3} /></label><footer><button className="secondary-action" onClick={onClose}>Цуцлах</button><button className="danger-action" onClick={() => submit('reject')} disabled={review.isPending}>Буцаах</button><button className="primary-action" onClick={() => submit('approve')} disabled={review.isPending}>{review.isPending && <LoaderCircle className="spin" size={15} />}Баталгаажуулах</button></footer></section></div>
}

function DeleteDialog({ target, onClose }: { target: { kind: 'folder' | 'entry'; value: ContractArchiveFolder | ContractArchiveEntry }; onClose: () => void }) {
  const deleteFolder = useDeleteContractArchiveFolder(); const deleteEntry = useDeleteContractArchiveEntry(); const [verification, setVerification] = useState('')
  const isFolder = target.kind === 'folder'; const item = target.value; const needsVerification = isFolder && (item as ContractArchiveFolder).nested_item_count > 0
  const modalRef = useRef<HTMLElement>(null)
  useFocusTrap(modalRef, onClose)
  const submit = async () => { try { if (isFolder) await deleteFolder.mutateAsync({ id: item.id, verification_name: verification || undefined }); else await deleteEntry.mutateAsync(item.id); onClose() } catch {} }
  return <div className="contract-modal-backdrop"><section ref={modalRef} className="contract-modal archive-review-dialog" role="dialog" aria-modal="true" aria-labelledby="archive-delete-title"><Trash2 size={30} className="archive-danger-icon" /><h3 id="archive-delete-title">Устгах уу?</h3><p>{item.name}</p>{needsVerification && <label>Баталгаажуулахын тулд хавтасны нэрийг оруулна уу<input value={verification} onChange={(event) => setVerification(event.target.value)} placeholder={item.name} /></label>}<footer><button className="secondary-action" onClick={onClose}>Цуцлах</button><button className="danger-action" onClick={submit} disabled={(isFolder ? deleteFolder.isPending : deleteEntry.isPending) || (needsVerification && verification !== item.name)}>Устгах</button></footer></section></div>
}

export function ContractArchiveWorkspace() {
  const actor = useActor()
  const roles = actor.data?.roles || []
  const canManage = roles.includes('admin') || roles.includes('legal_counsel')
  const [params, setParams] = useSearchParams()
  const folderId = params.get('folder') ? Number(params.get('folder')) : undefined
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  useEffect(() => { const timer = window.setTimeout(() => setDebouncedSearch(search), 220); return () => window.clearTimeout(timer) }, [search])
  const [sort, setSort] = useState<'name' | 'created_at' | 'size'>('name')
  const [layout, setLayout] = useState<Layout>(() => safeLocalStorage().get('contract-archive-layout') === 'grid' ? 'grid' : 'list')
  const [sheet, setSheet] = useState<Sheet>(null)
  const [actionId, setActionId] = useState<string | null>(null)
  const [folderDialog, setFolderDialog] = useState(false)
  const [folderName, setFolderName] = useState('')
  const [folderDescription, setFolderDescription] = useState('')
  const [pendingUpload, setPendingUpload] = useState<File | null>(null)
  const [reviewEntry, setReviewEntry] = useState<ContractArchiveEntry | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<{ kind: 'folder' | 'entry'; value: ContractArchiveFolder | ContractArchiveEntry } | null>(null)
  const [renameTarget, setRenameTarget] = useState<{ kind: 'folder' | 'entry'; value: ContractArchiveFolder | ContractArchiveEntry } | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const folderModalRef = useRef<HTMLElement>(null)
  const data = useContractArchive({ folderId, search: debouncedSearch, sort })
  const queue = useContractArchiveReviewQueue(canManage)
  const createFolder = useCreateContractArchiveFolder(); const upload = useUploadContractArchiveEntry(); const updateEntry = useUpdateContractArchiveEntry(); const updateFolder = useUpdateContractArchiveFolder()
  const searchRef = useRef<HTMLInputElement>(null); const uploadRef = useRef<HTMLInputElement>(null)
  useFocusTrap(folderModalRef, () => { setFolderDialog(false); setPendingUpload(null) }, folderDialog)
  useEffect(() => { const key = (event: KeyboardEvent) => { const target = event.target as HTMLElement | null; if (event.key === '/' && target && !['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) && !target.isContentEditable) { event.preventDefault(); searchRef.current?.focus() } }; window.addEventListener('keydown', key); return () => window.removeEventListener('keydown', key) }, [])
  const navigateFolder = (id?: number) => { const next = new URLSearchParams(params); if (id == null) next.delete('folder'); else next.set('folder', String(id)); setParams(next) }
  const chooseLayout = (next: Layout) => { setLayout(next); safeLocalStorage().set('contract-archive-layout', next) }
  const openCreateFolder = (file?: File) => { setPendingUpload(file || null); setFolderName(''); setFolderDescription(''); setFolderDialog(true) }
  const create = async () => { if (!folderName.trim()) return; try { const folder = await createFolder.mutateAsync({ name: folderName.trim(), description: folderDescription.trim() || null, parent_id: folderId || null }) as ContractArchiveFolder; setFolderDialog(false); if (pendingUpload) { await upload.mutateAsync({ folderId: folder.id, category: 'Бусад', file: pendingUpload }); setPendingUpload(null) } } catch {} }
  const drop = (event: React.DragEvent) => { event.preventDefault(); if (!canManage) return; const file = event.dataTransfer.files?.[0]; if (file) folderId ? upload.mutate({ folderId, category: 'Бусад', file }) : openCreateFolder(file) }
  const startRename = (value: ContractArchiveFolder | ContractArchiveEntry, kind: 'folder' | 'entry') => { setRenameTarget({ value, kind }); setRenameValue(value.name); setActionId(null) }
  const saveRename = async () => { if (!renameTarget || !renameValue.trim()) return; try { if (renameTarget.kind === 'folder') await updateFolder.mutateAsync({ id: renameTarget.value.id, name: renameValue.trim(), version: (renameTarget.value as ContractArchiveFolder).version }); else await updateEntry.mutateAsync({ id: renameTarget.value.id, name: renameValue.trim() }); setRenameTarget(null) } catch {} }
  const actionMenu = (item: ContractArchiveFolder | ContractArchiveEntry, kind: 'folder' | 'entry') => actionId === `${kind}:${item.id}` && <div className="archive-action-menu" role="menu"><button role="menuitem" onClick={() => { setSheet(kind === 'entry' ? { kind: 'info', entry: item as ContractArchiveEntry } : { kind: 'folder-info', folder: item as ContractArchiveFolder }); setActionId(null) }}><Info size={15} />Мэдээлэл</button>{canManage && <><button role="menuitem" onClick={() => startRename(item, kind)}><Pencil size={15} />Нэр солих</button>{kind === 'folder' && <button role="menuitem" onClick={() => { setSheet({ kind: 'folder-access', folder: item as ContractArchiveFolder }); setActionId(null) }}><Users size={15} />Хандалт</button>}{kind === 'entry' && <><button role="menuitem" onClick={() => { setSheet({ kind: 'preview', entry: item as ContractArchiveEntry }); setActionId(null) }}><FileText size={15} />Урьдчилан харах</button>{data.data?.current_folder && <button role="menuitem" onClick={() => { setSheet({ kind: 'folder-access', folder: data.data.current_folder as ContractArchiveFolder }); setActionId(null) }}><Users size={15} />Хандалт</button>}</>}<button className="danger" role="menuitem" onClick={() => { setDeleteTarget({ kind, value: item }); setActionId(null) }}><Trash2 size={15} />Устгах</button></>}</div>
  return <section className="contract-archive-workspace" onClick={() => actionId && setActionId(null)}>
    <header className="archive-header"><div><span className="eyebrow">Гэрээ / Архив</span><h2>Архив</h2><p>Гарын үсэг зурж баталгаажсан гэрээ болон архивийн баримтууд.</p></div>{canManage && <button className="primary-action" onClick={() => openCreateFolder()}><FolderPlus size={16} />+ Шинэ хавтас үүсгэх</button>}</header>
    <div className="contract-module-tabs"><a href="/contracts" className="">Гэрээний төсөл</a><a href="/contracts/archive" className="active">Архив {data.data?.pending_review_count ? <span>{data.data.pending_review_count}</span> : null}</a></div>
    {canManage && !!queue.data?.items.length && <section className="archive-review-inbox"><div><span className="eyebrow">REVIEW INBOX</span><h3>Хянах гэрээнүүд <span>{queue.data.items.length}</span></h3></div><div className="archive-review-list">{queue.data.items.map((entry) => <button key={entry.id} onClick={() => setReviewEntry(entry)}><ShieldCheck size={18} /><span><strong>{entry.name}</strong><small>{entry.category} · {formatDate(entry.created_at)}</small></span><span className="archive-pending-badge">Хүлээж байна</span></button>)}</div></section>}
    <section className="panel archive-browser" onDragOver={(event) => event.preventDefault()} onDrop={drop} aria-busy={data.isLoading || upload.isPending}><div className="archive-toolbar"><nav className="archive-breadcrumbs" aria-label="Гэрээний архивын зам"><button onClick={() => navigateFolder()}>Гэрээ</button><span>/</span><button onClick={() => navigateFolder()}>Архив</button>{data.data?.breadcrumbs.map((crumb) => <span key={crumb.id}> / <button onClick={() => navigateFolder(crumb.id)}>{crumb.name}</button></span>)}</nav><div className="archive-controls"><label className="archive-search"><Search size={15} /><span className="sr-only">Архив хайх</span><input ref={searchRef} value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Хайх… /" /></label><DropdownSelect ariaLabel="Эрэмбэлэх" value={sort} onChange={(value) => setSort(value as typeof sort)} options={[{ value: 'name', label: 'Нэр' }, { value: 'created_at', label: 'Үүсгэсэн огноо' }, { value: 'size', label: 'Хэмжээ' }]} /><div className="archive-layout-toggle" aria-label="Харагдац"><button className={layout === 'list' ? 'active' : ''} onClick={() => chooseLayout('list')} aria-label="Жагсаалт"><List size={16} /></button><button className={layout === 'grid' ? 'active' : ''} onClick={() => chooseLayout('grid')} aria-label="Preview grid"><Grid2X2 size={16} /></button></div>{canManage && <button className="secondary-action" onClick={() => uploadRef.current?.click()}><Upload size={15} />Файл нэмэх</button>}<input ref={uploadRef} className="sr-only" type="file" accept=".pdf,.doc,.docx,.jpg,.jpeg,.png,.tiff" onChange={(event) => { const file = event.target.files?.[0]; if (file) folderId ? upload.mutate({ folderId, category: 'Бусад', file }) : openCreateFolder(file); event.currentTarget.value = '' }} /></div></div>
      {data.isError && <div className="archive-empty archive-error-state"><Archive size={48} strokeWidth={1.2} /><h3>Архивыг ачаалж чадсангүй</h3><p>Холболтоо шалгаад дахин оролдоно уу.</p><button className="secondary-action" onClick={() => data.refetch()}>Дахин оролдох</button></div>}
      {!data.isLoading && !data.isError && !data.data?.folders.length && !data.data?.items.length && <div className="archive-empty"><Archive size={62} strokeWidth={1.2} /><h3>Архивлагдсан гэрээ байхгүй байна</h3><p>Эхний хавтсаа үүсгэх эсвэл файлаа энд чирж оруулна уу.</p>{canManage && <button className="primary-action" onClick={() => openCreateFolder()}><FolderPlus size={15} />Эхний хавтас үүсгэх</button>}</div>}
      {!!(data.data?.folders.length || data.data?.items.length) && <div className={layout === 'list' ? 'archive-table' : 'archive-grid'} role={layout === 'list' ? 'table' : 'list'}>{layout === 'list' && <div className="archive-table-head" role="row"><span>Нэр</span><span>Төрөл</span><span>Үүсгэсэн огноо</span><span>Үүсгэсэн ажилтан</span><span>Үйлдэл</span></div>}{data.data?.folders.map((folder) => <div className="archive-row archive-folder-row" role={layout === 'list' ? 'row' : 'listitem'} key={`folder-${folder.id}`}><button className="archive-name-cell" onClick={() => navigateFolder(folder.id)}><span className="archive-item-icon folder"><ItemIcon item={folder} /></span><span><strong>{renameTarget?.kind === 'folder' && renameTarget.value.id === folder.id ? <input autoFocus value={renameValue} onChange={(event) => setRenameValue(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') saveRename(); if (event.key === 'Escape') setRenameTarget(null) }} onClick={(event) => event.stopPropagation()} /> : folder.name}</strong><small>{folder.nested_item_count} nested item · {formatSize(folder.total_size)}</small></span></button><span className="archive-category">Хавтас</span><time>{formatDate(folder.created_at)}</time><Person value={folder.author} /><div className="archive-row-actions"><button onClick={(event) => { event.stopPropagation(); setActionId(actionId === `folder:${folder.id}` ? null : `folder:${folder.id}`) }} aria-label={`${folder.name} үйлдэл`}><MoreVertical size={18} /></button>{actionMenu(folder, 'folder')}</div></div>)}{data.data?.items.map((entry) => <div className="archive-row" role={layout === 'list' ? 'row' : 'listitem'} key={`entry-${entry.id}`}><button className="archive-name-cell" onClick={() => setSheet({ kind: 'preview', entry })}><span className="archive-item-icon"><ItemIcon item={entry} /></span><span><strong>{renameTarget?.kind === 'entry' && renameTarget.value.id === entry.id ? <input autoFocus value={renameValue} onChange={(event) => setRenameValue(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') saveRename(); if (event.key === 'Escape') setRenameTarget(null) }} onClick={(event) => event.stopPropagation()} /> : entry.name}</strong><small>{entry.signing_status}</small></span></button><span className="archive-category"><b>{entry.category}</b><small>{entry.review_status === 'pending' ? 'Хяналт хүлээж байна' : ''}</small></span><time>{formatDate(entry.created_at)}</time><Person value={entry.author} /><div className="archive-row-actions"><button onClick={(event) => { event.stopPropagation(); setActionId(actionId === `entry:${entry.id}` ? null : `entry:${entry.id}`) }} aria-label={`${entry.name} үйлдэл`}><MoreVertical size={18} /></button>{actionMenu(entry, 'entry')}</div></div>)}</div>}
    </section>
    {folderDialog && <div className="contract-modal-backdrop"><section ref={folderModalRef} className="contract-modal archive-review-dialog" role="dialog" aria-modal="true" aria-labelledby="archive-folder-dialog-title"><button className="icon-button" onClick={() => { setFolderDialog(false); setPendingUpload(null) }} aria-label="Хаах"><X size={18} /></button><FolderPlus size={30} className="modal-success-icon" /><h3 id="archive-folder-dialog-title">Шинэ хавтас үүсгэх</h3><label>Хавтасны нэр<input autoFocus value={folderName} onChange={(event) => setFolderName(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && create()} /></label><label>Тайлбар<textarea value={folderDescription} onChange={(event) => setFolderDescription(event.target.value)} rows={3} /></label>{pendingUpload && <p className="field-help">{pendingUpload.name} файлыг энэ хавтаст байршуулна.</p>}<footer><button className="secondary-action" onClick={() => { setFolderDialog(false); setPendingUpload(null) }}>Цуцлах</button><button className="primary-action" onClick={create} disabled={createFolder.isPending || !folderName.trim()}>{createFolder.isPending && <LoaderCircle className="spin" size={15} />}Хадгалах</button></footer></section></div>}
    {reviewEntry && <ReviewDialog entry={reviewEntry} folders={data.data?.folder_options || data.data?.folders || []} onClose={() => setReviewEntry(null)} />}
    {deleteTarget && <DeleteDialog target={deleteTarget} onClose={() => setDeleteTarget(null)} />}
    {sheet?.kind === 'preview' && <PreviewSheet entry={sheet.entry} onClose={() => setSheet(null)} />}{sheet?.kind === 'info' && <InfoSheet entry={sheet.entry} onClose={() => setSheet(null)} />}{sheet?.kind === 'folder-info' && <FolderInfoSheet folder={sheet.folder} onClose={() => setSheet(null)} />}{sheet?.kind === 'folder-access' && <AccessSheet folder={sheet.folder} onClose={() => setSheet(null)} />}
  </section>
}
