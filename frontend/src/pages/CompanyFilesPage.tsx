import { useDeferredValue, useEffect, useRef, useState } from 'react'
import { ArchiveRestore, ChevronRight, Download, Eye, File, FileArchive, FileAudio, FileCode2, FileImage, FileText, FileVideo, Folder, FolderPlus, Grid2X2, HardDrive, List, LoaderCircle, MoreHorizontal, Pencil, Search, Trash2, Upload, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import {
  CompanyLibraryItem,
  downloadCompanyFile,
  downloadCompanyFolder,
  getCompanyFileBlob,
  getCompanyFilePreview,
  useCompanyFiles,
  useCreateCompanyFolder,
  useDeleteCompanyItemPermanently,
  useRestoreCompanyItem,
  useTrashCompanyItem,
  useUpdateCompanyItem,
  useUploadCompanyFile,
} from '../api/enterprise'
import { DropdownSelect } from '../components/DropdownSelect'

type DialogState = { mode: 'create' } | { mode: 'rename' | 'move'; item: CompanyLibraryItem } | null
type Layout = 'list' | 'grid'
type PreviewKind = 'image' | 'pdf' | 'text' | 'audio' | 'video' | 'binary'

const textExtensions = new Set(['js', 'ts', 'json', 'md', 'txt', 'csv'])
const imageExtensions = new Set(['png', 'jpg', 'jpeg', 'webp', 'svg', 'gif'])
const audioExtensions = new Set(['mp3', 'wav'])
const videoExtensions = new Set(['mp4', 'webm'])

function extension(name: string) { return name.split('.').pop()?.toLowerCase() || '' }
function previewKind(item: CompanyLibraryItem): PreviewKind {
  const ext = extension(item.name)
  if (imageExtensions.has(ext)) return 'image'
  if (ext === 'pdf') return 'pdf'
  if (textExtensions.has(ext)) return 'text'
  if (audioExtensions.has(ext)) return 'audio'
  if (videoExtensions.has(ext)) return 'video'
  return 'binary'
}
function isPreviewable(item: CompanyLibraryItem) { return item.kind === 'file' && previewKind(item) !== 'binary' }
function formatSize(bytes: number | null) {
  if (bytes === null) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
function ItemIcon({ item, size = 20 }: { item: CompanyLibraryItem; size?: number }) {
  if (item.kind === 'folder') return <Folder size={size} />
  switch (previewKind(item)) {
    case 'image': return <FileImage size={size} />
    case 'text': return <FileCode2 size={size} />
    case 'audio': return <FileAudio size={size} />
    case 'video': return <FileVideo size={size} />
    case 'binary': return <FileArchive size={size} />
    default: return <FileText size={size} />
  }
}

function GridCard({ item, disabled, onOpen, onDownload, onMenu }: { item: CompanyLibraryItem; disabled: boolean; onOpen: () => void; onDownload: () => void; onMenu: () => void }) {
  const cardRef = useRef<HTMLElement>(null)
  const [visible, setVisible] = useState(false)
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [snippet, setSnippet] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  const kind = previewKind(item)
  useEffect(() => {
    const element = cardRef.current
    if (!element || item.kind === 'folder') return
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), { rootMargin: '180px' })
    observer.observe(element)
    return () => observer.disconnect()
  }, [item.id, item.kind])
  useEffect(() => {
    if (!visible || item.kind === 'folder' || !['image', 'text'].includes(kind)) return
    let cancelled = false
    let objectUrl: string | null = null
    getCompanyFilePreview(item).then(({ blob }) => {
      if (cancelled) return
      if (kind === 'image') { objectUrl = URL.createObjectURL(blob); setImageUrl(objectUrl) }
      else blob.text().then((value) => !cancelled && setSnippet(value))
    }).catch(() => !cancelled && setFailed(true))
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [item, kind, visible])
  return <article ref={cardRef} className="company-file-card" role="listitem">
    <button className="company-file-card-open" onClick={onOpen} disabled={disabled} aria-label={item.name}>
      <span className={`company-file-card-preview ${kind} ${failed ? 'failed' : ''}`}>
        {item.kind === 'folder' ? <ItemIcon item={item} size={44} /> : kind === 'image' && imageUrl ? <img src={imageUrl} alt="" /> : kind === 'text' && snippet !== null ? <code>{snippet.slice(0, 420)}</code> : kind === 'pdf' ? <><FileText size={42} /><b>PDF</b></> : <><ItemIcon item={item} size={42} /><b>{kind === 'binary' ? extension(item.name).toUpperCase() || 'FILE' : kind}</b></>}
      </span>
      <span className="company-file-card-copy"><strong>{item.name}</strong><small>{item.kind === 'folder' ? 'Folder' : formatSize(item.size)}</small></span>
    </button>
    <div className="company-file-card-actions">
      <button onClick={item.kind === 'folder' ? onDownload : isPreviewable(item) ? onOpen : onDownload} disabled={disabled} aria-label={`${item.name} ${isPreviewable(item) ? 'preview' : 'download'}`}>{item.kind === 'file' && isPreviewable(item) ? <Eye size={16} /> : <Download size={16} />}</button>
      {item.kind === 'file' && isPreviewable(item) && <button onClick={onDownload} disabled={disabled} aria-label={`${item.name} download`}><Download size={17} /></button>}
    </div>
  </article>
}

function FilePreviewModal({ item, onClose }: { item: CompanyLibraryItem; onClose: () => void }) {
  const [url, setUrl] = useState<string | null>(null)
  const [text, setText] = useState<string | null>(null)
  const [error, setError] = useState(false)
  const closeButton = useRef<HTMLButtonElement>(null)
  const kind = previewKind(item)
  useEffect(() => {
    closeButton.current?.focus()
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKeyDown)
    let objectUrl: string | null = null
    ;(kind === 'text' ? getCompanyFilePreview(item).then(({ blob }) => blob.text()).then(setText) : getCompanyFileBlob(item).then((blob) => { objectUrl = URL.createObjectURL(blob); setUrl(objectUrl) })).catch(() => setError(true))
    return () => { window.removeEventListener('keydown', onKeyDown); if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [item, kind, onClose])
  return <div className="sheet-backdrop company-file-preview-backdrop" onMouseDown={onClose}><section className="panel company-file-preview-modal" role="dialog" aria-modal="true" aria-label={item.name} onMouseDown={(event) => event.stopPropagation()}>
    <header><div><span className="eyebrow">{kind}</span><h3>{item.name}</h3></div><button ref={closeButton} onClick={onClose} aria-label="Close preview"><X size={19} /></button></header>
    <div className="company-file-preview-content">{error ? <p>Preview could not be loaded.</p> : kind === 'image' && url ? <img src={url} alt={item.name} /> : kind === 'pdf' && url ? <iframe src={url} title={item.name} /> : kind === 'audio' && url ? <audio controls autoPlay src={url} /> : kind === 'video' && url ? <video controls autoPlay src={url} /> : kind === 'text' && text !== null ? <pre><code>{text}</code></pre> : <LoaderCircle className="spin" size={28} />}</div>
  </section></div>
}

export function CompanyFilesPage() {
  const { t, i18n } = useTranslation()
  const params = new URLSearchParams(location.search)
  const [parentId, setParentId] = useState<number | undefined>(params.get('parent') ? Number(params.get('parent')) : undefined)
  const [search, setSearch] = useState('')
  const deferredSearch = useDeferredValue(search)
  const [sort, setSort] = useState('name')
  const [trashOpen, setTrashOpen] = useState(false)
  const [dialog, setDialog] = useState<DialogState>(null)
  const [dialogValue, setDialogValue] = useState('')
  const [uploadProgress, setUploadProgress] = useState<number | null>(null)
  const [layout, setLayout] = useState<Layout>(() => localStorage.getItem('company-files-layout') === 'grid' ? 'grid' : 'list')
  const [previewItem, setPreviewItem] = useState<CompanyLibraryItem | null>(null)
  const [actionItem, setActionItem] = useState<CompanyLibraryItem | null>(null)
  const [archivePending, setArchivePending] = useState(false)
  const uploadInput = useRef<HTMLInputElement>(null)
  const uploadAbort = useRef<AbortController | null>(null)
  const files = useCompanyFiles({ parentId: trashOpen ? undefined : parentId, search: trashOpen ? '' : deferredSearch, sort, trash: trashOpen })
  const createFolder = useCreateCompanyFolder(); const uploadFile = useUploadCompanyFile(); const updateItem = useUpdateCompanyItem(); const trashItem = useTrashCompanyItem(); const restoreItem = useRestoreCompanyItem(); const deleteItem = useDeleteCompanyItemPermanently()
  const busy = createFolder.isPending || updateItem.isPending
  useEffect(() => { if (params.get('upload') === '1') window.setTimeout(() => uploadInput.current?.click()) }, [])
  const chooseLayout = (next: Layout) => { setLayout(next); localStorage.setItem('company-files-layout', next) }
  const navigateTo = (id?: number) => { setParentId(id); setSearch(''); setTrashOpen(false); setActionItem(null) }
  const openDialog = (next: DialogState) => { setDialog(next); setDialogValue(next?.mode === 'rename' ? next.item.name : next?.mode === 'move' ? String(next.item.parent_id ?? '') : '') }
  const submitDialog = async (event: React.FormEvent) => { event.preventDefault(); if (!dialog) return; if (dialog.mode === 'create') await createFolder.mutateAsync({ name: dialogValue, parent_id: parentId ?? null }); if (dialog.mode === 'rename') await updateItem.mutateAsync({ id: dialog.item.id, name: dialogValue }); if (dialog.mode === 'move') await updateItem.mutateAsync({ id: dialog.item.id, parent_id: dialogValue ? Number(dialogValue) : undefined, move_to_root: !dialogValue }); setDialog(null) }
  const upload = async (selected?: FileList | null) => { if (!selected?.length) return; uploadAbort.current?.abort(); const controller = new AbortController(); uploadAbort.current = controller; setUploadProgress(0); try { await uploadFile.mutateAsync({ files: Array.from(selected), parent_id: parentId ?? null, onProgress: setUploadProgress, signal: controller.signal }) } catch {} finally { if (uploadAbort.current === controller) { uploadAbort.current = null; setUploadProgress(null) }; if (uploadInput.current) uploadInput.current.value = '' } }
  const download = async (item: CompanyLibraryItem) => { try { await downloadCompanyFile(item) } catch (error: any) { toast.error(error.response?.data?.detail || t('files.downloadError')) } }
  const archive = async (folder: CompanyLibraryItem) => { setArchivePending(true); try { await downloadCompanyFolder(folder); toast.success(t('files.archiveReady')) } catch (error: any) { toast.error(error.response?.data?.detail || t('files.archiveError')) } finally { setArchivePending(false); setActionItem(null) } }
  const openFile = (item: CompanyLibraryItem) => { if (item.kind === 'folder') navigateTo(item.id); else if (isPreviewable(item)) setPreviewItem(item); else download(item) }
  const moveToTrash = (item: CompanyLibraryItem) => { if (window.confirm(t(item.kind === 'folder' ? 'files.confirmTrashFolder' : 'files.confirmTrashFile'))) trashItem.mutate(item.id) }
  const actionMenu = (item: CompanyLibraryItem) => actionItem?.id === item.id && <div className="company-file-action-menu" role="menu"><button role="menuitem" onClick={() => item.kind === 'folder' ? archive(item) : download(item)}><Download size={15} />{item.kind === 'folder' ? t('files.downloadFolder') : t('files.download')}</button>{files.data?.can_manage && <><button role="menuitem" onClick={() => { openDialog({ mode: 'rename', item }); setActionItem(null) }}><Pencil size={15} />{t('files.rename')}</button><button role="menuitem" onClick={() => { openDialog({ mode: 'move', item }); setActionItem(null) }}><MoreHorizontal size={15} />{t('files.move')}</button><button role="menuitem" className="danger" onClick={() => { moveToTrash(item); setActionItem(null) }}><Trash2 size={15} />{t('files.trash')}</button></>}</div>
  return <div className="company-files-page">
    <div className="view-toolbar company-files-heading"><div><span className="eyebrow">OYUNS / Workspace</span><h2>{t('files.title')}</h2><p>{t('files.subtitle')}</p></div>{!trashOpen && <div className="company-files-primary-actions">{files.data?.can_manage && <button className="secondary-action" onClick={() => openDialog({ mode: 'create' })}><FolderPlus size={16} />{t('files.newFolder')}</button>}{files.data?.can_upload && <><button className="primary-action" onClick={() => uploadInput.current?.click()} disabled={uploadFile.isPending}><Upload size={16} />{t('files.upload')}</button><input ref={uploadInput} className="sr-only" type="file" multiple onChange={(event) => upload(event.target.files)} /></>}</div>}</div>
    <section className="panel company-files-browser" aria-busy={files.isLoading || uploadFile.isPending || archivePending}><div className="company-files-toolbar"><nav className="file-breadcrumbs" aria-label={t('files.breadcrumbs')}><button onClick={() => navigateTo()}><HardDrive size={15} />{t('files.root')}</button>{!trashOpen && files.data?.breadcrumbs.map((crumb) => <span key={crumb.id}><ChevronRight size={14} /><button onClick={() => navigateTo(crumb.id)}>{crumb.name}</button></span>)}{trashOpen && <span><ChevronRight size={14} /><strong>{t('files.trash')}</strong></span>}</nav><div className="company-files-filters">{!trashOpen && <label className="company-file-search"><Search size={15} /><span className="sr-only">{t('files.search')}</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t('files.search')} /></label>}<DropdownSelect ariaLabel={t('files.sort')} value={sort} onChange={setSort} options={[{ value: 'name', label: t('files.sortName') }, { value: 'newest', label: t('files.sortNewest') }, { value: 'oldest', label: t('files.sortOldest') }, { value: 'size', label: t('files.sortSize') }]} />{!trashOpen && <div className="company-file-layout-toggle" aria-label={t('files.layout')}><button className={layout === 'list' ? 'active' : ''} onClick={() => chooseLayout('list')} aria-label={t('files.listView')}><List size={16} /></button><button className={layout === 'grid' ? 'active' : ''} onClick={() => chooseLayout('grid')} aria-label={t('files.gridView')}><Grid2X2 size={16} /></button></div>}{files.data?.can_manage && <button className={trashOpen ? 'secondary-action active' : 'secondary-action'} onClick={() => { setTrashOpen((value) => !value); setSearch('') }}><Trash2 size={15} />{trashOpen ? t('files.back') : t('files.trash')}</button>}</div></div>
      {!trashOpen && files.data?.current_folder && <div className="company-file-current-actions"><span>{files.data.current_folder.name}</span><button className="secondary-action" onClick={() => archive(files.data!.current_folder!)} disabled={archivePending}><Download size={15} />{t('files.downloadFolder')}</button></div>}
      {(uploadProgress !== null || archivePending) && <div className="file-upload-progress indeterminate"><span /><small>{archivePending ? t('files.archiving') : uploadProgress === 100 ? t('files.processing') : `${t('files.uploading')} ${uploadProgress}%`}</small>{uploadProgress !== null && <button type="button" onClick={() => uploadAbort.current?.abort()}>{t('files.cancelUpload')}</button>}</div>}
      {files.isLoading && <div className="company-files-state">{t('files.loading')}</div>}{files.isError && <div className="company-files-state error"><p>{t('files.loadError')}</p><button className="secondary-action" onClick={() => files.refetch()}>{t('files.retry')}</button></div>}{!files.isLoading && !files.isError && files.data?.items.length === 0 && <div className="company-files-state"><Folder size={42} strokeWidth={1.3} /><h3>{trashOpen ? t('files.emptyTrash') : search ? t('files.noResults') : t('files.emptyFolder')}</h3><p>{trashOpen ? t('files.emptyTrashHelp') : t('files.emptyHelp')}</p></div>}
      {!!files.data?.items.length && (layout === 'list' ? <div className="company-file-list" role="list"><div className="company-file-list-head" aria-hidden><span>{t('files.name')}</span><span>{t('files.size')}</span><span>{t('files.updated')}</span><span /></div>{files.data.items.map((item) => <article className="company-file-row" role="listitem" key={item.id}><button className="company-file-open" onClick={() => openFile(item)} disabled={trashOpen}><span className={`company-file-icon ${item.kind}`}><ItemIcon item={item} /></span><span><strong>{item.name}</strong><small>{item.kind === 'folder' ? t('files.folder') : item.content_type || t('files.file')}</small></span></button><span className="company-file-size">{formatSize(item.size)}</span><time dateTime={item.updated_at}>{new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium' }).format(new Date(item.updated_at))}</time><div className="company-file-actions">{!trashOpen && (item.kind === 'folder' ? <button onClick={() => archive(item)} disabled={archivePending} aria-label={`${item.name} download`}><Download size={16} /></button> : <button onClick={() => download(item)} aria-label={`${item.name} download`}><Download size={16} /></button>)}{files.data?.can_manage && trashOpen && <><button onClick={() => restoreItem.mutate(item.id)} aria-label={`${item.name} ${t('files.restore')}`}><ArchiveRestore size={16} /></button><button className="danger" onClick={() => deleteItem.mutate(item.id)} aria-label={`${item.name} ${t('files.deleteForever')}`}><Trash2 size={16} /></button></>} {actionMenu(item)}</div></article>)}</div> : <div className="company-file-grid" role="list">{files.data.items.map((item) => <div className="company-file-card-wrap" key={item.id}><GridCard item={item} disabled={trashOpen} onOpen={() => openFile(item)} onDownload={() => item.kind === 'folder' ? archive(item) : download(item)} onMenu={() => setActionItem(actionItem?.id === item.id ? null : item)} />{!trashOpen && actionMenu(item)}</div>)}</div>)}</section>
    {dialog && <div className="sheet-backdrop company-file-dialog-backdrop" onMouseDown={() => setDialog(null)}><form className="panel company-file-dialog" role="dialog" aria-modal="true" aria-labelledby="company-file-dialog-title" onSubmit={submitDialog} onMouseDown={(event) => event.stopPropagation()}><header><h3 id="company-file-dialog-title">{t(`files.${dialog.mode}`)}</h3><button type="button" onClick={() => setDialog(null)} aria-label={t('files.close')}><X size={18} /></button></header>{dialog.mode === 'move' ? <label>{t('files.destination')}<select autoFocus value={dialogValue} onChange={(event) => setDialogValue(event.target.value)}><option value="">{t('files.root')}</option>{files.data?.folders.filter((folder) => folder.id !== dialog.item.id).map((folder) => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select></label> : <label>{t('files.name')}<input autoFocus required maxLength={240} value={dialogValue} onChange={(event) => setDialogValue(event.target.value)} /></label>}<footer><button type="button" className="secondary-action" onClick={() => setDialog(null)}>{t('files.cancel')}</button><button className="primary-action" disabled={busy}>{t('files.save')}</button></footer></form></div>}
    {previewItem && <FilePreviewModal item={previewItem} onClose={() => setPreviewItem(null)} />}
  </div>
}
