/**
 * HalComposer — local intervention composer owned by HaL instead of assistant-ui.
 *
 * assistant-ui still renders the working log, but intervention submission
 * during an active loop is a HaL-specific path and should not inherit chat-like
 * optimistic message behavior from the display library.
 */

import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ChangeEvent, type CompositionEvent, type FormEvent, type KeyboardEvent } from 'react'
import { ArrowUp, Plus } from 'lucide-react'

import { serializeLocalAttachmentFiles } from '@/lib/attachments'
import { submitSessionTurn } from '@/lib/api'
import { useHalStore } from '@/lib/store'
import { HAL_READING_COLUMN_CLASS } from '@/components/ui/hal-patterns'
import { cn } from '@/lib/utils'
import type { SocketState } from '@/lib/types'

type LocalComposerAttachment = {
  id: string
  file: File
  type: 'image' | 'document' | 'file'
  contentType?: string
}

const COMPOSER_MAX_HEIGHT_PX = 128

interface HalComposerProps {
  sessionId: string
  socketState: SocketState
}

export function HalComposer({ sessionId, socketState }: HalComposerProps) {
  const [draftText, setDraftText] = useState('')
  const [attachments, setAttachments] = useState<LocalComposerAttachment[]>([])
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const sessionStatus = useHalStore((s) => s.sessionManifests[sessionId]?.status ?? null)

  const threadDisabled = sessionStatus === 'briefing'
  const threadCanAttach = true
  const applySessionManifest = useHalStore((s) => s.applySessionManifest)
  const loadSessionEvents = useHalStore((s) => s.loadSessionEvents)
  const addOptimisticIntervention = useHalStore((s) => s.addOptimisticIntervention)
  const setError = useHalStore((s) => s.setError)

  const sendDisabled = useMemo(
    () => threadDisabled || (!draftText.trim() && attachments.length === 0),
    [attachments.length, draftText, threadDisabled],
  )

  useEffect(() => {
    setDraftText('')
    setAttachments([])
  }, [sessionId])

  useLayoutEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return

    textarea.style.height = 'auto'
    const nextHeight = Math.min(textarea.scrollHeight, COMPOSER_MAX_HEIGHT_PX)
    textarea.style.height = `${nextHeight}px`
    textarea.style.overflowY = textarea.scrollHeight > COMPOSER_MAX_HEIGHT_PX ? 'auto' : 'hidden'
  }, [draftText])

  const submitComposer = async () => {
    if (sendDisabled) return

    setError(null)
    const content = draftText.trim()
    const attachmentFiles = attachments.map((attachment) => attachment.file)

    if (!content && attachmentFiles.length === 0) return

    setDraftText('')
    setAttachments([])

    try {
      const serializedAttachments = await serializeLocalAttachmentFiles(attachmentFiles)
      const submission = await submitSessionTurn(sessionId, {
        content,
        attachments: serializedAttachments,
      })

      if (socketState !== 'live') {
        applySessionManifest(submission.session)
        await loadSessionEvents(sessionId)
      }

      if (submission.delivery === 'intervention_queued') {
        addOptimisticIntervention(sessionId, {
          content,
          attachments: attachmentFiles.map((file) => ({
            name: file.name,
            type: classifyAttachment(file),
            contentType: file.type || undefined,
          })),
        })
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to submit turn.')
    }
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await submitComposer()
  }

  const handleChange = (event: ChangeEvent<HTMLTextAreaElement>) => {
    setDraftText(event.target.value)
  }

  const handleCompositionEnd = (event: CompositionEvent<HTMLTextAreaElement>) => {
    setDraftText(event.currentTarget.value)
  }

  const handleKeyDown = async (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (threadDisabled || event.nativeEvent.isComposing) return
    if (event.key !== 'Enter' || event.shiftKey) return

    event.preventDefault()
    await submitComposer()
  }

  const handlePaste = async (event: React.ClipboardEvent<HTMLTextAreaElement>) => {
    if (!threadCanAttach) return
    const files = Array.from(event.clipboardData?.files || [])
    if (files.length === 0) return

    event.preventDefault()
    appendFiles(files)
  }

  const handlePickAttachment = () => {
    if (threadDisabled || !threadCanAttach) return
    fileInputRef.current?.click()
  }

  const handleAttachmentChange = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || [])
    if (files.length === 0) return
    appendFiles(files)
    event.target.value = ''
  }

  const removeAttachment = (attachmentId: string) => {
    setAttachments((current) => current.filter((attachment) => attachment.id !== attachmentId))
  }

  return (
    <form className={cn(HAL_READING_COLUMN_CLASS, 'shrink-0')} onSubmit={handleSubmit}>
      <div className="hal-paper rounded-[20px] border border-border bg-hal-float px-3 py-2 shadow-popover">
        <div className="flex flex-col">
          <LocalAttachmentShelf attachments={attachments} onRemove={removeAttachment} />
          <textarea
            ref={textareaRef}
            autoFocus
            placeholder="Continue collaborating..."
            className="max-h-[128px] min-h-[46px] w-full resize-none overflow-y-auto border-0 bg-transparent px-0 py-1 text-body leading-6 text-hal-primary placeholder:text-hal-muted focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
            rows={1}
            value={draftText}
            disabled={threadDisabled}
            onChange={handleChange}
            onCompositionEnd={handleCompositionEnd}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
          />

          <div className="-mx-1 mt-0.5 flex items-center justify-between">
            <button
              type="button"
              className="flex h-8 w-8 items-center justify-center text-hal-muted transition-colors duration-fast ease-standard hover:text-hal-primary disabled:cursor-not-allowed disabled:opacity-40"
              onClick={handlePickAttachment}
              disabled={threadDisabled || !threadCanAttach}
              aria-label="Add attachment"
            >
              <Plus className="h-5 w-5" />
            </button>

            <button
              type="submit"
              className="flex h-8 w-8 shrink-0 items-center justify-center text-accent transition-colors duration-fast ease-standard disabled:cursor-not-allowed disabled:text-hal-muted disabled:opacity-40"
              disabled={sendDisabled}
              aria-label="Send message"
            >
              <ArrowUp className="h-5 w-5" />
            </button>
          </div>
        </div>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        multiple
        onChange={handleAttachmentChange}
      />
    </form>
  )

  function appendFiles(files: File[]) {
    setAttachments((current) => {
      const next = new Map(current.map((attachment) => [attachment.id, attachment]))
      for (const file of files) {
        const id = `${file.name}:${file.size}:${file.lastModified}`
        if (!next.has(id)) {
          next.set(id, {
            id,
            file,
            type: classifyAttachment(file),
            contentType: file.type || undefined,
          })
        }
      }
      return [...next.values()]
    })
  }
}

function LocalAttachmentShelf({
  attachments,
  onRemove,
}: {
  attachments: LocalComposerAttachment[]
  onRemove: (attachmentId: string) => void
}) {
  if (attachments.length === 0) return null

  return (
    <div className="mb-2 flex flex-wrap gap-1.5">
      {attachments.map((attachment) => (
        <div
          key={attachment.id}
          className="flex w-[12rem] max-w-full min-w-0 items-center gap-2 rounded-[9px] bg-hal-inset px-2.5 py-1.5"
        >
          <div className="min-w-0 flex-1 leading-none">
            <div className="truncate text-meta text-hal-primary">{attachment.file.name}</div>
            <div className="mt-1 truncate text-caption uppercase tracking-[0.08em] text-hal-muted">
              {compactAttachmentDetail({
                name: attachment.file.name,
                contentType: attachment.contentType,
                type: attachment.type,
              })}
            </div>
          </div>
          <button
            type="button"
            className="flex h-6 w-6 shrink-0 items-center justify-center text-hal-muted transition-colors duration-fast ease-standard hover:text-hal-primary"
            onClick={() => onRemove(attachment.id)}
            aria-label={`Remove ${attachment.file.name}`}
          >
            <Plus className="h-3.5 w-3.5 rotate-45" />
          </button>
        </div>
      ))}
    </div>
  )
}

function classifyAttachment(file: File): 'image' | 'document' | 'file' {
  if (file.type.startsWith('image/')) return 'image'
  if (isTextLikeName(file.name, file.type)) return 'document'
  return 'file'
}

function compactAttachmentDetail(attachment: { name: string; contentType?: string; type: string }): string {
  const suffix = attachment.contentType?.split('/').pop()?.trim()
  if (suffix) return suffix.toUpperCase()
  if (attachment.type === 'image') return 'IMAGE'
  return fileExtension(attachment.name)
}

function fileExtension(name: string): string {
  const ext = name.split('.').pop()?.trim()
  if (!ext || ext === name) return 'FILE'
  return ext.slice(0, 4).toUpperCase()
}

function isTextLikeName(name: string, contentType?: string): boolean {
  if (
    contentType?.startsWith('text/') ||
    contentType === 'application/json' ||
    contentType === 'application/xml' ||
    contentType === 'text/csv'
  ) {
    return true
  }

  const lower = name.toLowerCase()
  return [
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
  ].some((suffix) => lower.endsWith(suffix))
}
