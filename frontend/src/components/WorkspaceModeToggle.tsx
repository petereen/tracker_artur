import { BriefcaseBusiness, UserRound } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useWorkspaceMode } from './WorkspaceModeProvider'

export function WorkspaceModeToggle() {
  const { t } = useTranslation()
  const { isManagerMode, isEligible, isLoading, isSaving, setMode } = useWorkspaceMode()
  if (!isEligible) return null
  const nextMode = isManagerMode ? 'member' : 'manager'
  const currentLabel = isManagerMode ? t('workspaceMode.manager', 'Manager Mode') : t('workspaceMode.member', 'Member Mode')
  const nextLabel = nextMode === 'manager' ? t('workspaceMode.manager', 'Manager Mode') : t('workspaceMode.member', 'Member Mode')

  return <button
    type="button"
    className={`workspace-mode-toggle ${isManagerMode ? 'is-manager' : 'is-member'}`}
    role="switch"
    aria-checked={isManagerMode}
    aria-label={t('workspaceMode.toggleLabel', 'Switch workspace mode')}
    aria-describedby="workspace-mode-description"
    title={`${currentLabel} · ${t('workspaceMode.switchTo', { mode: nextLabel, defaultValue: `Switch to ${nextLabel}` })}`}
    disabled={isLoading || isSaving}
    onClick={() => void setMode(nextMode)}
  >
    <span className="workspace-mode-icon" aria-hidden="true">{isManagerMode ? <BriefcaseBusiness size={14} /> : <UserRound size={14} />}</span>
    <span className="workspace-mode-copy"><strong>{currentLabel}</strong><small id="workspace-mode-description">{isManagerMode ? t('workspaceMode.companyHint', 'Company view') : t('workspaceMode.personalHint', 'Personal view')}</small></span>
    <span className="workspace-mode-track" aria-hidden="true"><i /></span>
  </button>
}
