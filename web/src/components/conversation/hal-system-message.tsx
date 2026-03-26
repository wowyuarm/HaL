/**
 * HalSystemMessage — compact notification row for session-level events.
 *
 * Renders scope updates, brief completions, and injected messages as
 * centered notification rows, not conversation bubbles.
 */

import { MessagePrimitive, useMessage } from '@assistant-ui/react'

import { halPaperObjectVariants } from '@/components/ui/hal-patterns'
import type { HalMessageMeta } from '@/lib/session-adapter'
import { cn } from '@/lib/utils'

export function HalSystemMessage() {
  const custom = useMessage((s) => s.metadata?.custom as HalMessageMeta | undefined)
  const firstText = useMessage((s) => {
    const part = s.content[0]
    return part?.type === 'text' ? part.text : ''
  })

  const badgeState =
    custom?.systemTone ??
    (firstText.startsWith('Scope')
      ? 'warning'
      : firstText.startsWith('Brief')
        ? 'success'
        : 'muted')

  const title = firstText.startsWith('Scope')
    ? 'Scope'
    : firstText.startsWith('Brief')
      ? 'Brief'
      : 'System'

  const titleClass =
    badgeState === 'warning'
      ? 'text-warning font-semibold'
      : badgeState === 'success'
        ? 'text-success font-semibold'
        : 'text-hal-muted font-semibold'

  return (
    <MessagePrimitive.Root className={cn(halPaperObjectVariants(), 'flex items-center gap-2')}>
      <span className={`text-caption uppercase tracking-[0.08em] ${titleClass}`}>{title}</span>
      <span className="min-w-0 flex-1 truncate text-caption text-hal-muted">{firstText}</span>
    </MessagePrimitive.Root>
  )
}
