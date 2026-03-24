import {
  type AttachmentAdapter,
  type CompleteAttachment,
  type PendingAttachment,
  CompositeAttachmentAdapter,
} from '@assistant-ui/react'

import type { WebAttachmentInput, WebAttachmentPart } from '@/lib/types'

const TEXT_ATTACHMENT_ACCEPT = [
  'text/plain',
  'text/html',
  'text/markdown',
  'text/csv',
  'text/xml',
  'application/json',
  '.txt',
  '.md',
  '.markdown',
  '.json',
  '.yaml',
  '.yml',
  '.csv',
  '.log',
  '.py',
  '.js',
  '.jsx',
  '.ts',
  '.tsx',
  '.css',
  '.html',
  '.xml',
].join(',')

function buildAttachmentId(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`
}

async function readFileAsDataUrl(file: File): Promise<string> {
  return await new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(reader.error ?? new Error(`Failed to read ${file.name}`))
    reader.readAsDataURL(file)
  })
}

class HalImageAttachmentAdapter implements AttachmentAdapter {
  accept = 'image/*'

  async add({ file }: { file: File }) {
    return {
      id: buildAttachmentId(file),
      type: 'image' as const,
      name: file.name,
      contentType: file.type,
      file,
      status: { type: 'requires-action' as const, reason: 'composer-send' as const },
    }
  }

  async send(attachment: PendingAttachment): Promise<CompleteAttachment> {
    return {
      ...attachment,
      type: 'image' as const,
      status: { type: 'complete' as const },
      content: [
        {
          type: 'image' as const,
          image: await readFileAsDataUrl(attachment.file),
          filename: attachment.name,
        },
      ],
    }
  }

  async remove() {}
}

class HalTextAttachmentAdapter implements AttachmentAdapter {
  accept = TEXT_ATTACHMENT_ACCEPT

  async add({ file }: { file: File }) {
    return {
      id: buildAttachmentId(file),
      type: 'document' as const,
      name: file.name,
      contentType: file.type,
      file,
      status: { type: 'requires-action' as const, reason: 'composer-send' as const },
    }
  }

  async send(attachment: PendingAttachment): Promise<CompleteAttachment> {
    return {
      ...attachment,
      type: 'document' as const,
      status: { type: 'complete' as const },
      content: [
        {
          type: 'text' as const,
          text: `<attachment name=${attachment.name}>\n${await attachment.file.text()}\n</attachment>`,
        },
      ],
    }
  }

  async remove() {}
}

class HalBinaryFileAttachmentAdapter implements AttachmentAdapter {
  accept = '*'

  async add({ file }: { file: File }) {
    return {
      id: buildAttachmentId(file),
      type: 'file' as const,
      name: file.name,
      contentType: file.type || 'application/octet-stream',
      file,
      status: { type: 'requires-action' as const, reason: 'composer-send' as const },
    }
  }

  async send(attachment: PendingAttachment): Promise<CompleteAttachment> {
    return {
      ...attachment,
      type: 'file' as const,
      status: { type: 'complete' as const },
      content: [
        {
          type: 'file' as const,
          filename: attachment.name,
          mimeType: attachment.contentType || 'application/octet-stream',
          data: await readFileAsDataUrl(attachment.file),
        },
      ],
    }
  }

  async remove() {}
}

export function createHalAttachmentAdapter(): AttachmentAdapter {
  return new CompositeAttachmentAdapter([
    new HalImageAttachmentAdapter(),
    new HalTextAttachmentAdapter(),
    new HalBinaryFileAttachmentAdapter(),
  ])
}

function serializeAttachmentPart(
  part: CompleteAttachment['content'][number],
): WebAttachmentPart | null {
  switch (part.type) {
    case 'text':
      return { type: 'text', text: part.text }
    case 'image':
      return {
        type: 'image',
        image: part.image,
        ...(part.filename ? { filename: part.filename } : undefined),
      }
    case 'file':
      return {
        type: 'file',
        data: part.data,
        mimeType: part.mimeType,
        ...(part.filename ? { filename: part.filename } : undefined),
      }
    default:
      return null
  }
}

export function serializeComposerAttachments(
  attachments: readonly CompleteAttachment[] | undefined,
): WebAttachmentInput[] {
  if (!attachments?.length) return []

  return attachments
    .map((attachment) => {
      const content = attachment.content
        .map((part) => serializeAttachmentPart(part))
        .filter((part): part is WebAttachmentPart => part !== null)

      if (content.length === 0) return null

      return {
        type: normalizeAttachmentType(attachment.type),
        name: attachment.name,
        ...(attachment.contentType ? { contentType: attachment.contentType } : undefined),
        content,
      } satisfies WebAttachmentInput
    })
    .filter((attachment): attachment is WebAttachmentInput => attachment !== null)
}

function normalizeAttachmentType(type: string): WebAttachmentInput['type'] {
  return type === 'image' || type === 'document' || type === 'file' ? type : 'file'
}
