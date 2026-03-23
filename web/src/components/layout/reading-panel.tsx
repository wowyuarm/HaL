import type { ReactNode } from 'react'

import { SideSheet } from '@/components/layout/side-sheet'
import { cn } from '@/lib/utils'

interface ReadingPanelProps {
  open: boolean
  title: string
  description?: string | null
  meta?: ReactNode
  widthClassName?: string
  zIndexClassName?: string
  onClose?: () => void
  contentClassName?: string
  children: ReactNode
}

export function ReadingPanel({
  open,
  title,
  description,
  meta,
  widthClassName,
  zIndexClassName,
  onClose,
  contentClassName,
  children,
}: ReadingPanelProps) {
  return (
    <SideSheet
      open={open}
      title={title}
      description={description}
      meta={meta}
      widthClassName={widthClassName}
      zIndexClassName={zIndexClassName}
      onClose={onClose}
    >
      <div className={cn('hal-side-sheet-content min-h-full', contentClassName)}>{children}</div>
    </SideSheet>
  )
}
