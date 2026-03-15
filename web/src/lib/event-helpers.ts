/**
 * Safe payload access helpers for SessionEvent records.
 *
 * Extracted from view-models.ts as a shared utility — used by both
 * the session-adapter (Phase 0) and the evidence inspector (Phase 4).
 */

import type { SessionEvent } from "@/lib/types";

// ---------------------------------------------------------------------------
// Typed accessors
// ---------------------------------------------------------------------------

/** Extract a non-empty string value from a JSON record. */
export function getString(record: Record<string, unknown>, key: string): string | undefined {
  const value = record[key];
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

/** Extract a finite number from a JSON record, or null. */
export function getFiniteNumber(record: Record<string, unknown>, key: string): number | null {
  const value = record[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Extract a string array from a JSON record, filtering out non-strings. */
export function getStringArray(record: Record<string, unknown>, key: string): string[] {
  const value = record[key];
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.length > 0);
}

/** Extract an arbitrary JSON object from a record. */
export function getObject(
  record: Record<string, unknown>,
  key: string,
): Record<string, unknown> | undefined {
  const value = record[key];
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

// ---------------------------------------------------------------------------
// Sorting
// ---------------------------------------------------------------------------

/** Compare two SessionEvents by sequence number (ascending). */
export function bySeq(a: SessionEvent, b: SessionEvent): number {
  return a.seq - b.seq;
}
