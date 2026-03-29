import type { WebAttachmentInput } from '@/lib/types'

async function readFileAsDataUrl(file: File): Promise<string> {
  return await new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(reader.error ?? new Error(`Failed to read ${file.name}`))
    reader.readAsDataURL(file)
  })
}

export async function serializeLocalAttachmentFiles(
  files: readonly File[],
): Promise<WebAttachmentInput[]> {
  return await Promise.all(
    files.map(async (file) => {
      if (file.type.startsWith('image/')) {
        return {
          type: 'image' as const,
          name: file.name,
          ...(file.type ? { contentType: file.type } : undefined),
          content: [
            {
              type: 'image' as const,
              image: await readFileAsDataUrl(file),
              filename: file.name,
            },
          ],
        }
      }

      if (isTextLikeFile(file)) {
        return {
          type: 'document' as const,
          name: file.name,
          ...(file.type ? { contentType: file.type } : undefined),
          content: [
            {
              type: 'text' as const,
              text: `<attachment name=${file.name}>\n${await file.text()}\n</attachment>`,
            },
          ],
        }
      }

      return {
        type: 'file' as const,
        name: file.name,
        ...(file.type ? { contentType: file.type } : undefined),
        content: [
          {
            type: 'file' as const,
            filename: file.name,
            mimeType: file.type || 'application/octet-stream',
            data: await readFileAsDataUrl(file),
          },
        ],
      }
    }),
  )
}

function isTextLikeFile(file: File): boolean {
  if (
    file.type.startsWith('text/') ||
    file.type === 'application/json' ||
    file.type === 'application/xml' ||
    file.type === 'text/csv'
  ) {
    return true
  }

  const name = file.name.toLowerCase()
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
  ].some((suffix) => name.endsWith(suffix))
}
