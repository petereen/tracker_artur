import type { ReactNode } from 'react'
import { HStack } from '@astryxdesign/core/HStack'
import { ScrollableArea } from '@astryxdesign/core/ScrollableArea'
import { VStack } from '@astryxdesign/core/VStack'

/**
 * Body of a long Astryx `Dialog` form. The dialog clips its content at
 * `maxHeight`, so the fields scroll here while the header and the action
 * buttons stay visible (`minHeight={0}` lets the area shrink in the dialog's
 * flex column).
 */
export function DialogScrollBody({ label, children, actions }: { label: string; children: ReactNode; actions?: ReactNode }) {
  return <>
    <ScrollableArea label={label} minHeight={0} overscroll="contain">
      <VStack gap={4} padding={4}>{children}</VStack>
    </ScrollableArea>
    {actions && <HStack gap={2} hAlign="end" padding={4}>{actions}</HStack>}
  </>
}
