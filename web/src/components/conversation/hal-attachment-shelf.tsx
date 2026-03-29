import {
  AttachmentPrimitive,
  MessagePrimitive,
  useAuiState,
  useMessage,
} from '@assistant-ui/react'
import { X } from 'lucide-react'

export function HalMessageAttachmentShelf() {
  const count = useMessage((s) => (s.role === 'user' ? s.attachments.length : 0))
  if (count === 0) return null

  return (
    <div className="flex flex-wrap gap-1.5">
      <MessagePrimitive.Attachments
        components={{
          Image: HalMessageAttachmentItem,
          Document: HalMessageAttachmentItem,
          File: HalMessageAttachmentItem,
          Attachment: HalMessageAttachmentItem,
        }}
      />
    </div>
  )
}

function HalMessageAttachmentItem() {
  const attachment = useAuiState((s) => s.attachment)
  return <HalAttachmentItem attachment={attachment} />
}

function HalAttachmentItem({
  attachment,
  removable = false,
}: {
  attachment: { name: string; contentType?: string; type: string }
  removable?: boolean
}) {
  const detail = compactAttachmentDetail(attachment)
  return (
    <AttachmentPrimitive.Root className="flex w-[12rem] max-w-full min-w-0 items-center gap-2 rounded-[9px] bg-hal-inset px-2.5 py-1.5">
      <div className="min-w-0 flex-1 leading-none">
        <div className="truncate text-meta text-hal-primary">{attachment.name}</div>
        <div className="mt-1 truncate text-caption uppercase tracking-[0.08em] text-hal-muted">
          {detail}
        </div>
      </div>

      {removable ? (
        <AttachmentPrimitive.Remove className="flex h-6 w-6 shrink-0 items-center justify-center text-hal-muted transition-colors duration-fast ease-standard hover:text-hal-primary">
          <X className="h-3.5 w-3.5" />
        </AttachmentPrimitive.Remove>
      ) : null}
    </AttachmentPrimitive.Root>
  )
}

function fileExtension(name: string): string {
  const ext = name.split('.').pop()?.trim()
  if (!ext || ext === name) return 'FILE'
  return ext.slice(0, 4).toUpperCase()
}

function compactAttachmentDetail(attachment: { name: string; contentType?: string; type: string }): string {
  const suffix = attachment.contentType?.split('/').pop()?.trim()
  if (suffix) return suffix.toUpperCase()
  if (attachment.type === 'image') return 'IMAGE'
  return fileExtension(attachment.name)
}
