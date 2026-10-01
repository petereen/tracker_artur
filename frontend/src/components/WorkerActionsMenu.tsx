import { useTranslation } from 'react-i18next'
import { useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { MoreVertical, Pencil, Trash2, UserCheck, UserRoundX, XCircle } from 'lucide-react'

export type WorkerActionRecord = { id: number; name: string; is_active: boolean; deleted_at?: string | null }

const MENU_GAP = 5
const VIEWPORT_MARGIN = 8

/**
 * Row actions for a worker. The menu is portalled to ``document.body`` with
 * fixed positioning: worker tables sit in cards with ``overflow: hidden`` and
 * page-enter animations create stacking contexts, both of which clipped or
 * buried an absolutely positioned menu.
 */
export function WorkerActionsMenu({ worker, open, onOpen, onClose, onEdit, onDelete, onSetActive, onPermanentDelete }: {
  worker: WorkerActionRecord
  open: boolean
  onOpen: () => void
  /** Closes the menu (outside click, Escape, scroll). Defaults to ``onOpen`` (a toggle). */
  onClose?: () => void
  onEdit: () => void
  onDelete: () => void
  onSetActive: (active: boolean) => void
  /** Shown only for archived workers; hard-deletes a record created by mistake. */
  onPermanentDelete?: () => void
}) {
  const { t } = useTranslation()
  const archived = Boolean(worker.deleted_at)
  const trigger = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null)
  const close = onClose ?? onOpen

  useLayoutEffect(() => {
    if (!open) { setPosition(null); return }
    const place = () => {
      const button = trigger.current?.getBoundingClientRect()
      if (!button) return
      const width = menu.current?.offsetWidth || 200
      const height = menu.current?.offsetHeight || 0
      const below = button.bottom + MENU_GAP
      // Open upwards when the menu would run past the bottom of the viewport.
      const top = height && below + height > window.innerHeight - VIEWPORT_MARGIN && button.top - MENU_GAP - height > VIEWPORT_MARGIN
        ? button.top - MENU_GAP - height
        : below
      const left = Math.min(Math.max(VIEWPORT_MARGIN, button.right - width), window.innerWidth - width - VIEWPORT_MARGIN)
      setPosition({ top, left })
    }
    place()
    // Measure again once the menu has rendered with its real size.
    const frame = requestAnimationFrame(place)
    const dismiss = (event: Event) => {
      const target = event.target as Node
      if (menu.current?.contains(target) || trigger.current?.contains(target)) return
      close()
    }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') close() }
    document.addEventListener('mousedown', dismiss)
    document.addEventListener('keydown', escape)
    window.addEventListener('resize', close)
    window.addEventListener('scroll', dismiss, true)
    return () => {
      cancelAnimationFrame(frame)
      document.removeEventListener('mousedown', dismiss)
      document.removeEventListener('keydown', escape)
      window.removeEventListener('resize', close)
      window.removeEventListener('scroll', dismiss, true)
    }
  }, [open, close])

  return <div className="employee-menu-wrap">
    <button ref={trigger} type="button" className="employee-more-button" aria-label={t('hr.workerActions.menuLabel', { name: worker.name })} aria-haspopup="menu" aria-expanded={open} onClick={onOpen}><MoreVertical size={18} /></button>
    {open && createPortal(<div ref={menu} className="employee-action-menu employee-action-menu-floating" role="menu"
      style={{ position: 'fixed', top: position?.top ?? -9999, left: position?.left ?? -9999, right: 'auto', visibility: position ? 'visible' : 'hidden' }}
      onClick={(event) => event.stopPropagation()}>
      <button role="menuitem" onClick={onEdit}><Pencil size={15} />{t('hr.workerActions.edit')}</button>
      <button role="menuitem" onClick={() => onSetActive(!worker.is_active)}>{worker.is_active ? <UserRoundX size={15} /> : <UserCheck size={15} />}{worker.is_active ? t('hr.workerActions.deactivate') : t('hr.workerActions.activate')}</button>
      {!archived && <button role="menuitem" className="danger" onClick={onDelete}><Trash2 size={15} />{t('hr.workerActions.archive')}</button>}
      {archived && onPermanentDelete && <button role="menuitem" className="danger" onClick={onPermanentDelete}><XCircle size={15} />{t('hr.workerActions.deleteForever')}</button>}
    </div>, document.body)}
  </div>
}
