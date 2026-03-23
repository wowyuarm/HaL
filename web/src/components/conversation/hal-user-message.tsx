/**
 * HalUserMessage — renders a user message in HaL's design language.
 *
 * Uses assistant-ui MessagePrimitive for context binding while applying
 * HaL design tokens (human-subtle background, human accent border).
 * Command messages render as compact inline rows without bubble chrome.
 */

import { MessagePrimitive, useMessage } from '@assistant-ui/react'

import { HalMarkdown } from '@/components/ui/hal-markdown'
import { halPaperObjectVariants } from '@/components/ui/hal-patterns'
import type { HalMessageMeta } from '@/lib/session-adapter'
import type { TextMessagePartProps } from '@assistant-ui/react'
import { cn } from '@/lib/utils'

export function HalUserMessage() {
  const custom = useMessage((s) => s.metadata?.custom as HalMessageMeta | undefined)
  const firstText = useMessage((s) => {
    const part = s.content[0]
    return part?.type === 'text' ? part.text : ''
  })
  const isCommand = custom?.isCommand === true

  // Command messages: compact inline row, no bubble.
  if (isCommand) {
    return (
      <MessagePrimitive.Root className="px-1 py-1.5">
        <div className="flex min-w-0 items-center gap-2 text-meta">
          <span className="shrink-0 text-hal-muted">›</span>
          <span className="truncate font-mono text-hal-primary">{firstText || '_No content_'}</span>
        </div>
      </MessagePrimitive.Root>
    )
  }

  return (
    <MessagePrimitive.Root
      className={cn(
        halPaperObjectVariants({ surface: 'panel', density: 'comfortable', seam: 'human' }),
      )}
    >
      <MessagePrimitive.Content components={USER_CONTENT_COMPONENTS} />
    </MessagePrimitive.Root>
  )
}

function UserTextPart({ text }: TextMessagePartProps) {
  return <HalMarkdown>{text || '_No content_'}</HalMarkdown>
}

const USER_CONTENT_COMPONENTS = { Text: UserTextPart } as const
