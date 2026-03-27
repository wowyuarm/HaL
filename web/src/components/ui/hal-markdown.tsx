import {
  Children,
  isValidElement,
  useEffect,
  useState,
  type ComponentPropsWithoutRef,
  type ReactNode,
} from 'react'

import { Check, Copy } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import rehypeHighlight from 'rehype-highlight'
import remarkGfm from 'remark-gfm'

import { cn } from '@/lib/utils'

type HalMarkdownTone = 'conversation' | 'brief'

const PROTECTED_MARKDOWN_SEGMENT_RE = /(```[\s\S]*?```|`[^`\n]*`)/g
const INLINE_LINK_RE = /\[([^\]]+)\]\(([^)]+)\)/g
const INLINE_CODE_RE = /(`+)(.*?)\1/g
const INLINE_STRONG_RE = /(\*\*|__)([\s\S]+?)\1/g
const INLINE_EM_STAR_RE = /(^|[^*])\*(\S(?:[\s\S]*?\S)?)\*(?!\*)/g
const INLINE_EM_UNDERSCORE_RE = /(^|[^_])_(\S(?:[\s\S]*?\S)?)_(?!_)/g
const CJK_EDGE_PUNCTUATION = '：；，。！？、…'
const ASCII_EDGE_PUNCTUATION = ':;,.!?'
const EDGE_PUNCTUATION_CLASS = escapeForCharClass(
  `${CJK_EDGE_PUNCTUATION}${ASCII_EDGE_PUNCTUATION}`,
)
const CONTEXT_BOUNDARY_CLASS = '\\s\\p{P}'
const CONTEXT_BOUNDARY_CHAR_RE = new RegExp(`^[${CONTEXT_BOUNDARY_CLASS}]$`, 'u')
const SAFE_STRONG_SEGMENT_RE = /(\*\*|__)(?=\S)([\s\S]*?\S)\1/g
const PROTECTED_STRONG_TOKEN_PREFIX = '\u0000HAL_MD_STRONG_'
const PROTECTED_STRONG_TOKEN_SUFFIX = '\u0000'
const EDGE_PUNCTUATION_AT_START_RE = new RegExp(`^[${EDGE_PUNCTUATION_CLASS}]`, 'u')
const EDGE_PUNCTUATION_AT_END_RE = new RegExp(`[${EDGE_PUNCTUATION_CLASS}]$`, 'u')

interface HalMarkdownProps {
  children: string
  tone?: HalMarkdownTone
  className?: string
  onLinkClick?: (href: string) => void
}

export function HalMarkdown({
  children,
  tone = 'conversation',
  className,
  onLinkClick,
}: HalMarkdownProps) {
  const normalizedMarkdown = normalizeMarkdownEmphasis(children)

  return (
    <div
      className={cn(
        'hal-markdown max-w-none',
        tone === 'brief' ? 'hal-markdown-brief' : 'hal-markdown-conversation',
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={buildMarkdownComponents(onLinkClick)}
      >
        {normalizedMarkdown}
      </ReactMarkdown>
    </div>
  )
}

export function normalizeMarkdownEmphasis(source: string): string {
  return source
    .split(PROTECTED_MARKDOWN_SEGMENT_RE)
    .map((segment, index) => (index % 2 === 1 ? segment : normalizeEmphasisInTextSegment(segment)))
    .join('')
}

export function compactMarkdownPreviewText(source: string): string {
  const normalized = normalizeMarkdownEmphasis(source)

  return normalized
    .replace(INLINE_LINK_RE, '$1')
    .replace(INLINE_CODE_RE, '$2')
    .replace(INLINE_STRONG_RE, '$2')
    .replace(INLINE_EM_STAR_RE, '$1$2')
    .replace(INLINE_EM_UNDERSCORE_RE, '$1$2')
    .replace(/\s+/g, ' ')
    .trim()
}

function normalizeEmphasisInTextSegment(segment: string): string {
  const { text: mutableText, protectedSegments } = protectSafeStrongSegments(segment)
  let current = mutableText

  for (const delimiter of ['**', '__']) {
    current = normalizeDelimiterEdges(current, delimiter)
  }

  return restoreProtectedStrongSegments(current, protectedSegments)
}

function normalizeDelimiterEdges(text: string, delimiter: string): string {
  const escaped = escapeForRegExp(delimiter)
  const contentWithoutDelimiter = `((?:(?!${escaped})[\\s\\S])+?)`
  const leadingPunctuationRe = new RegExp(
    `(?<![${CONTEXT_BOUNDARY_CLASS}])(${escaped})([${EDGE_PUNCTUATION_CLASS}]+)(\\s*)${contentWithoutDelimiter}(?<!\\s)\\1`,
    'gu',
  )
  const trailingPunctuationRe = new RegExp(
    `(${escaped})(?=\\S)${contentWithoutDelimiter}(\\s*)([${EDGE_PUNCTUATION_CLASS}]+)(?<!\\s)\\1(?![${CONTEXT_BOUNDARY_CLASS}]|$)`,
    'gu',
  )

  let current = text

  for (let i = 0; i < 3; i += 1) {
    const next = current
      .replace(leadingPunctuationRe, '$2$3$1$4$1')
      .replace(trailingPunctuationRe, '$1$2$1$3$4')

    if (next === current) {
      break
    }

    current = next
  }

  return current
}

function escapeForRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function escapeForCharClass(value: string): string {
  return value.replace(/[\\\]\[-^]/g, '\\$&')
}

function protectSafeStrongSegments(segment: string): {
  text: string
  protectedSegments: string[]
} {
  const protectedSegments: string[] = []

  const text = segment.replace(
    SAFE_STRONG_SEGMENT_RE,
    (fullMatch, _delimiter, content: string, offset: number, source: string) => {
      const previousChar = offset > 0 ? source[offset - 1] : ''
      const nextCharIndex = offset + fullMatch.length
      const nextChar = nextCharIndex < source.length ? source[nextCharIndex] : ''
      const previousIsBoundary = previousChar === '' || CONTEXT_BOUNDARY_CHAR_RE.test(previousChar)
      const nextIsBoundary = nextChar === '' || CONTEXT_BOUNDARY_CHAR_RE.test(nextChar)
      const needsLeadingNormalization =
        EDGE_PUNCTUATION_AT_START_RE.test(content) && !previousIsBoundary
      const needsTrailingNormalization =
        EDGE_PUNCTUATION_AT_END_RE.test(content) && !nextIsBoundary

      if (needsLeadingNormalization || needsTrailingNormalization) {
        return fullMatch
      }

      const token = `${PROTECTED_STRONG_TOKEN_PREFIX}${protectedSegments.length}${PROTECTED_STRONG_TOKEN_SUFFIX}`
      protectedSegments.push(fullMatch)
      return token
    },
  )

  return { text, protectedSegments }
}

function restoreProtectedStrongSegments(text: string, protectedSegments: string[]): string {
  let current = text

  for (let index = 0; index < protectedSegments.length; index += 1) {
    const token = `${PROTECTED_STRONG_TOKEN_PREFIX}${index}${PROTECTED_STRONG_TOKEN_SUFFIX}`
    current = current.replaceAll(token, protectedSegments[index]!)
  }

  return current
}

function MarkdownPre({ className, children, ...props }: ComponentPropsWithoutRef<'pre'>) {
  const codeText = extractTextContent(children).replace(/\n$/, '')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return undefined
    const timer = window.setTimeout(() => setCopied(false), 1600)
    return () => window.clearTimeout(timer)
  }, [copied])

  async function handleCopy() {
    if (!codeText.trim()) return
    try {
      await navigator.clipboard.writeText(codeText)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="hal-markdown-pre-wrap">
      <button
        type="button"
        onClick={handleCopy}
        className="hal-markdown-copy-button"
        aria-label={copied ? 'Copied code' : 'Copy code'}
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </button>
      <pre className={cn('hal-markdown-pre', className)} {...props}>
        {children}
      </pre>
    </div>
  )
}

function MarkdownCode({
  className,
  inline,
  children,
  ...props
}: ComponentPropsWithoutRef<'code'> & { inline?: boolean }) {
  const text = String(children ?? '')
  const hasLanguageClass = Boolean(className && /language-/.test(className))
  const isInlineCode = inline === true || (!hasLanguageClass && !text.includes('\n'))

  if (isInlineCode) {
    return (
      <code className={cn('hal-markdown-inline-code', className)} {...props}>
        {children}
      </code>
    )
  }

  return (
    <code className={cn('hal-markdown-block-code', className)} {...props}>
      {children}
    </code>
  )
}

function MarkdownTable({ className, children, ...props }: ComponentPropsWithoutRef<'table'>) {
  return (
    <div className="hal-markdown-table-wrap">
      <table className={cn('hal-markdown-table', className)} {...props}>
        {children}
      </table>
    </div>
  )
}

function MarkdownLink({
  className,
  href,
  children,
  onLinkClick,
  ...props
}: ComponentPropsWithoutRef<'a'> & { onLinkClick?: (href: string) => void }) {
  const openInNewTab = Boolean(href && !href.startsWith('#'))
  const isEpisodeLink = Boolean(href && isEpisodeLinkHref(href))

  return (
    <a
      href={href}
      target={openInNewTab && !isEpisodeLink ? '_blank' : undefined}
      rel={openInNewTab && !isEpisodeLink ? 'noreferrer noopener' : undefined}
      onClick={
        isEpisodeLink && href && onLinkClick
          ? (event) => {
              event.preventDefault()
              onLinkClick(href)
            }
          : undefined
      }
      className={cn('hal-markdown-link', className)}
      {...props}
    >
      {children}
    </a>
  )
}

function buildMarkdownComponents(onLinkClick?: (href: string) => void) {
  return {
    pre: MarkdownPre,
    code: MarkdownCode,
    table: MarkdownTable,
    a: (props: ComponentPropsWithoutRef<'a'>) => (
      <MarkdownLink {...props} onLinkClick={onLinkClick} />
    ),
  } as const
}

function isEpisodeLinkHref(href: string): boolean {
  const normalized = href.startsWith('./') ? href.slice(2) : href
  return normalized.startsWith('episodes/')
}

function extractTextContent(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') {
    return String(node)
  }

  if (Array.isArray(node)) {
    return node.map(extractTextContent).join('')
  }

  if (isValidElement(node)) {
    return extractTextContent(node.props.children as ReactNode)
  }

  return Children.toArray(node).map(extractTextContent).join('')
}
