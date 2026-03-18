import {
  Children,
  isValidElement,
  useEffect,
  useState,
  type ComponentPropsWithoutRef,
  type ReactNode,
} from "react";

import { Check, Copy } from "lucide-react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

type HalMarkdownTone = "conversation" | "brief";

interface HalMarkdownProps {
  children: string;
  tone?: HalMarkdownTone;
  className?: string;
}

export function HalMarkdown({
  children,
  tone = "conversation",
  className,
}: HalMarkdownProps) {
  return (
    <div
      className={cn(
        "hal-markdown max-w-none",
        tone === "brief" ? "hal-markdown-brief" : "hal-markdown-conversation",
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={MARKDOWN_COMPONENTS}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

function MarkdownPre({
  className,
  children,
  ...props
}: ComponentPropsWithoutRef<"pre">) {
  const codeText = extractTextContent(children).replace(/\n$/, "");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return undefined;
    const timer = window.setTimeout(() => setCopied(false), 1600);
    return () => window.clearTimeout(timer);
  }, [copied]);

  async function handleCopy() {
    if (!codeText.trim()) return;
    try {
      await navigator.clipboard.writeText(codeText);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="hal-markdown-pre-wrap">
      <button
        type="button"
        onClick={handleCopy}
        className="hal-markdown-copy-button"
        aria-label={copied ? "Copied code" : "Copy code"}
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </button>
      <pre className={cn("hal-markdown-pre", className)} {...props}>
        {children}
      </pre>
    </div>
  );
}

function MarkdownCode({
  className,
  inline,
  children,
  ...props
}: ComponentPropsWithoutRef<"code"> & { inline?: boolean }) {
  const text = String(children ?? "");
  const hasLanguageClass = Boolean(className && /language-/.test(className));
  const isInlineCode = inline === true || (!hasLanguageClass && !text.includes("\n"));

  if (isInlineCode) {
    return (
      <code className={cn("hal-markdown-inline-code", className)} {...props}>
        {children}
      </code>
    );
  }

  return (
    <code className={cn("hal-markdown-block-code", className)} {...props}>
      {children}
    </code>
  );
}

function MarkdownTable({
  className,
  children,
  ...props
}: ComponentPropsWithoutRef<"table">) {
  return (
    <div className="hal-markdown-table-wrap">
      <table className={cn("hal-markdown-table", className)} {...props}>
        {children}
      </table>
    </div>
  );
}

function MarkdownLink({
  className,
  href,
  children,
  ...props
}: ComponentPropsWithoutRef<"a">) {
  const openInNewTab = Boolean(href && !href.startsWith("#"));

  return (
    <a
      href={href}
      target={openInNewTab ? "_blank" : undefined}
      rel={openInNewTab ? "noreferrer noopener" : undefined}
      className={cn("hal-markdown-link", className)}
      {...props}
    >
      {children}
    </a>
  );
}

const MARKDOWN_COMPONENTS = {
  pre: MarkdownPre,
  code: MarkdownCode,
  table: MarkdownTable,
  a: MarkdownLink,
} as const;

function extractTextContent(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }

  if (Array.isArray(node)) {
    return node.map(extractTextContent).join("");
  }

  if (isValidElement(node)) {
    return extractTextContent(node.props.children as ReactNode);
  }

  return Children.toArray(node)
    .map(extractTextContent)
    .join("");
}
