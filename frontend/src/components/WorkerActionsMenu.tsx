import { MoreVertical, Pencil, Trash2, UserCheck, UserRoundX } from 'lucide-react'

export type WorkerActionRecord = { id: number; name: string; is_active: boolean; deleted_at?: string | null }

export function WorkerActionsMenu({ worker, open, onOpen, onEdit, onDelete, onSetActive }: {
  worker: WorkerActionRecord
  open: boolean
  onOpen: () => void
  onEdit: () => void
  onDelete: () => void
  onSetActive: (active: boolean) => void
}) {
  const archived = Boolean(worker.deleted_at)
  return <div className="employee-menu-wrap">
    <button type="button" className="employee-more-button" aria-label={`${worker.name} үйлдлүүд`} aria-expanded={open} onClick={onOpen}><MoreVertical size={18} /></button>
    {open && <div className="employee-action-menu" role="menu">
      <button role="menuitem" onClick={onEdit}><Pencil size={15} />Засах</button>
      <button role="menuitem" onClick={() => onSetActive(!worker.is_active)}>{worker.is_active ? <UserRoundX size={15} /> : <UserCheck size={15} />}{worker.is_active ? 'Идэвхгүй болгох' : 'Идэвхжүүлэх'}</button>
      {!archived && <button role="menuitem" className="danger" onClick={onDelete}><Trash2 size={15} />Архивлах</button>}
    </div>}
  </div>
}
