import type { ReactNode } from 'react'
import { Plus } from 'lucide-react'
import { Button } from '@astryxdesign/core/Button'

/**
 * The one "create / add" button of the platform: Astryx primary, medium height, leading icon.
 * Every page-level toolbar uses it so the blue create action looks and sits the same everywhere.
 */
export function CreateButton({ label, onClick, icon, isDisabled, isLoading, tooltip, type = 'button' }: {
  label: string
  onClick?: () => void
  icon?: ReactNode
  isDisabled?: boolean
  isLoading?: boolean
  tooltip?: string
  type?: 'button' | 'submit'
}) {
  return <Button label={label} variant="primary" size="md" type={type} icon={icon ?? <Plus size={16} />} onClick={onClick} isDisabled={isDisabled} isLoading={isLoading} tooltip={tooltip} />
}
