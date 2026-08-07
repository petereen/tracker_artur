import { useDeferredValue, useRef, useState } from 'react'
import { ArchiveRestore, ChevronRight, Download, File, Folder, FolderPlus, HardDrive, MoreHorizontal, Pencil, Search, Trash2, Upload, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import {
  CompanyLibraryItem,
  downloadCompanyFile,
  useCompanyFiles,
  useCreateCompanyFolder,
  useDeleteCompanyItemPermanently,
  useRestoreCompanyItem,
  useTrashCompanyItem,
  useUpdateCompanyItem,
  useUploadCompanyFile,
} from '../api/enterprise'

type DialogState = { mode: 'create' } | { mode: 'rename' | 'move'; item: CompanyLibraryItem } | null

function formatSize(bytes: number | null) {
  if (bytes === null) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function CompanyFilesPage() {
  const { t, i18n } = useTranslation()
  const [parentId, setParentId] = useState<number>()
  const [search, setSearch] = useState('')
  const deferredSearch = useDeferredValue(search)
  const [sort, setSort] = useState('name')
  const [trashOpen, setTrashOpen] = useState(false)
  const [dialog, setDialog] = useState<DialogState>(null)
  const [dialogValue, setDialogValue] = useState('')
  const [uploadProgress, setUploadProgress] = useState<number | null>(null)
  const uploadInput = useRef<HTMLInputElement>(null)
  const files = useCompanyFiles({ parentId: trashOpen ? undefined : parentId, search: trashOpen ? '' : deferredSearch, sort, trash: trashOpen })
  const createFolder = useCreateCompanyFolder()
  const uploadFile = useUploadCompanyFile()
  const updateItem = useUpdateCompanyItem()
  const trashItem = useTrashCompanyItem()
  const restoreItem = useRestoreCompanyItem()
  const deleteItem = useDeleteCompanyItemPermanently()
  const busy = createFolder.isPending || updateItem.isPending

  const navigateTo = (id?: number) => { setParentId(id); setSearch(''); setTrashOpen(false) }
  const openDialog = (next: DialogState) => {
    setDialog(next)
    setDialogValue(next?.mode === 'rename' ? next.item.name : next?.mode === 'move' ? String(next.item.parent_id ?? '') : '')
  }
  const submitDialog = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!dialog) return
    if (dialog.mode === 'create') await createFolder.mutateAsync({ name: dialogValue, parent_id: parentId ?? null })
    if (dialog.mode === 'rename') await updateItem.mutateAsync({ id: dialog.item.id, name: dialogValue })
    if (dialog.mode === 'move') await updateItem.mutateAsync({ id: dialog.item.id, parent_id: dialogValue ? Number(dialogValue) : undefined, move_to_root: !dialogValue })
    setDialog(null)
  }
  const upload = async (files?: FileList | null) => {
    if (!files?.length) return
    setUploadProgress(0)
    try {
      await uploadFile.mutateAsync({ files: Array.from(files), parent_id: parentId ?? null, onProgress: setUploadProgress })
    } finally {
      setUploadProgress(null)
      if (uploadInput.current) uploadInput.current.value = ''
    }
  }
  const download = async (item: CompanyLibraryItem) => {
    try { await downloadCompanyFile(item) } catch (error: any) { toast.error(error.response?.data?.detail || t('files.downloadError')) }
  }
  const moveToTrash = (item: CompanyLibraryItem) => {
    if (window.confirm(t(item.kind === 'folder' ? 'files.confirmTrashFolder' : 'files.confirmTrashFile'))) trashItem.mutate(item.id)
  }
  const deleteForever = (item: CompanyLibraryItem) => {
    if (window.confirm(t('files.confirmPermanent'))) deleteItem.mutate(item.id)
  }

  return <div className="company-files-page">
    <div className="view-toolbar company-files-heading">
      <div><span className="eyebrow">OYUNS / Workspace</span><h2>{t('files.title')}</h2><p>{t('files.subtitle')}</p></div>
      {files.data?.can_manage && !trashOpen && <div className="company-files-primary-actions">
        <button className="secondary-action" onClick={() => openDialog({ mode: 'create' })}><FolderPlus size={16} />{t('files.newFolder')}</button>
        <button className="primary-action" onClick={() => uploadInput.current?.click()} disabled={uploadFile.isPending}><Upload size={16} />{t('files.upload')}</button>
        <input ref={uploadInput} className="sr-only" type="file" multiple onChange={(event) => upload(event.target.files)} />
      </div>}
    </div>

    <section className="panel company-files-browser" aria-busy={files.isLoading || uploadFile.isPending}>
      <div className="company-files-toolbar">
        <nav className="file-breadcrumbs" aria-label={t('files.breadcrumbs')}>
          <button onClick={() => navigateTo()}><HardDrive size={15} />{t('files.root')}</button>
          {!trashOpen && files.data?.breadcrumbs.map((crumb) => <span key={crumb.id}><ChevronRight size={14} /><button onClick={() => navigateTo(crumb.id)}>{crumb.name}</button></span>)}
          {trashOpen && <span><ChevronRight size={14} /><strong>{t('files.trash')}</strong></span>}
        </nav>
        <div className="company-files-filters">
          {!trashOpen && <label className="company-file-search"><Search size={15} /><span className="sr-only">{t('files.search')}</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t('files.search')} /></label>}
          <select aria-label={t('files.sort')} value={sort} onChange={(event) => setSort(event.target.value)}><option value="name">{t('files.sortName')}</option><option value="newest">{t('files.sortNewest')}</option><option value="oldest">{t('files.sortOldest')}</option><option value="size">{t('files.sortSize')}</option></select>
          {files.data?.can_manage && <button className={trashOpen ? 'secondary-action active' : 'secondary-action'} onClick={() => { setTrashOpen((value) => !value); setSearch('') }}><Trash2 size={15} />{trashOpen ? t('files.back') : t('files.trash')}</button>}
        </div>
      </div>

      {uploadProgress !== null && <div className="file-upload-progress"><span style={{ width: `${uploadProgress}%` }} /><small>{t('files.uploading')} {uploadProgress}%</small></div>}
      {files.isLoading && <div className="company-files-state">{t('files.loading')}</div>}
      {files.isError && <div className="company-files-state error"><p>{t('files.loadError')}</p><button className="secondary-action" onClick={() => files.refetch()}>{t('files.retry')}</button></div>}
      {!files.isLoading && !files.isError && files.data?.items.length === 0 && <div className="company-files-state"><Folder size={42} strokeWidth={1.3} /><h3>{trashOpen ? t('files.emptyTrash') : search ? t('files.noResults') : t('files.emptyFolder')}</h3><p>{trashOpen ? t('files.emptyTrashHelp') : t('files.emptyHelp')}</p></div>}
      {!!files.data?.items.length && <div className="company-file-list" role="list">
        <div className="company-file-list-head" aria-hidden><span>{t('files.name')}</span><span>{t('files.size')}</span><span>{t('files.updated')}</span><span /></div>
        {files.data.items.map((item) => <article className="company-file-row" role="listitem" key={item.id}>
          <button className="company-file-open" onClick={() => item.kind === 'folder' ? navigateTo(item.id) : download(item)} disabled={trashOpen}>
            <span className={`company-file-icon ${item.kind}`}>{item.kind === 'folder' ? <Folder size={20} /> : <File size={20} />}</span>
            <span><strong>{item.name}</strong><small>{item.kind === 'folder' ? t('files.folder') : item.content_type || t('files.file')}</small></span>
          </button>
          <span className="company-file-size">{formatSize(item.size)}</span>
          <time dateTime={item.updated_at}>{new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium' }).format(new Date(item.updated_at))}</time>
          <div className="company-file-actions">
            {!trashOpen && item.kind === 'file' && <button onClick={() => download(item)} aria-label={`${item.name} ${t('files.download')}`}><Download size={16} /></button>}
            {files.data?.can_manage && !trashOpen && <><button onClick={() => openDialog({ mode: 'rename', item })} aria-label={`${item.name} ${t('files.rename')}`}><Pencil size={15} /></button><button onClick={() => openDialog({ mode: 'move', item })} aria-label={`${item.name} ${t('files.move')}`}><MoreHorizontal size={16} /></button><button className="danger" onClick={() => moveToTrash(item)} aria-label={`${item.name} ${t('files.trash')}`}><Trash2 size={15} /></button></>}
            {files.data?.can_manage && trashOpen && <><button onClick={() => restoreItem.mutate(item.id)} aria-label={`${item.name} ${t('files.restore')}`}><ArchiveRestore size={16} /></button><button className="danger" onClick={() => deleteForever(item)} aria-label={`${item.name} ${t('files.deleteForever')}`}><Trash2 size={16} /></button></>}
          </div>
        </article>)}
      </div>}
    </section>

    {dialog && <div className="sheet-backdrop company-file-dialog-backdrop" onMouseDown={() => setDialog(null)}><form className="panel company-file-dialog" role="dialog" aria-modal="true" aria-labelledby="company-file-dialog-title" onSubmit={submitDialog} onMouseDown={(event) => event.stopPropagation()}>
      <header><h3 id="company-file-dialog-title">{t(`files.${dialog.mode}`)}</h3><button type="button" onClick={() => setDialog(null)} aria-label={t('files.close')}><X size={18} /></button></header>
      {dialog.mode === 'move' ? <label>{t('files.destination')}<select autoFocus value={dialogValue} onChange={(event) => setDialogValue(event.target.value)}><option value="">{t('files.root')}</option>{files.data?.folders.filter((folder) => folder.id !== dialog.item.id).map((folder) => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select></label> : <label>{t('files.name')}<input autoFocus required maxLength={240} value={dialogValue} onChange={(event) => setDialogValue(event.target.value)} /></label>}
      <footer><button type="button" className="secondary-action" onClick={() => setDialog(null)}>{t('files.cancel')}</button><button className="primary-action" disabled={busy}>{t('files.save')}</button></footer>
    </form></div>}
  </div>
}
