/**
 * HalComposer — message input using assistant-ui ComposerPrimitive.
 *
 * Keeps attachment preview, writing area, and actions inside one restrained
 * paper object, with the action row separated so spacing stays calm and even.
 */

import { ComposerPrimitive } from '@assistant-ui/react'
import { ArrowUp, Plus } from 'lucide-react'

import { HalComposerAttachmentShelf } from '@/components/conversation/hal-attachment-shelf'
import { HAL_READING_COLUMN_CLASS } from '@/components/ui/hal-patterns'
import { cn } from '@/lib/utils'

export function HalComposer() {
  return (
    <ComposerPrimitive.Root className={cn(HAL_READING_COLUMN_CLASS, 'shrink-0')}>
      <div className="hal-paper rounded-[20px] border border-border bg-hal-float px-3 py-2 shadow-popover">
        <div className="flex flex-col">
          <HalComposerAttachmentShelf />
          <ComposerPrimitive.Input
            autoFocus
            placeholder="Continue collaborating..."
            className="max-h-[128px] min-h-[46px] w-full resize-none overflow-y-auto border-0 bg-transparent px-0 py-1 text-body leading-6 text-hal-primary placeholder:text-hal-muted focus:outline-none"
            rows={1}
          />

          <div className="-mx-1 mt-0.5 flex items-center justify-between">
            <ComposerPrimitive.AddAttachment className="flex h-8 w-8 items-center justify-center text-hal-muted transition-colors duration-fast ease-standard hover:text-hal-primary">
              <Plus className="h-5 w-5" />
            </ComposerPrimitive.AddAttachment>

            <ComposerPrimitive.Send className="flex h-8 w-8 shrink-0 items-center justify-center text-accent transition-colors duration-fast ease-standard disabled:cursor-not-allowed disabled:text-hal-muted disabled:opacity-40">
              <ArrowUp className="h-5 w-5" />
            </ComposerPrimitive.Send>
          </div>
        </div>
      </div>
    </ComposerPrimitive.Root>
  )
}
