import type { ArrayField, Config, Field } from '@puckeditor/core';

import { isTranslatableField } from './translatable-fields';

/** One step of a {@link FieldPath}: an object key or an array index. */
export type PathSegment = string | number;

/**
 * Locates one translatable string inside a parsed Puck document, as the list
 * of segments walked from the root. Examples:
 * - `["content", 2, "props", "text"]`
 * - `["content", 0, "props", "items", 1, "links", 0, "label"]`
 * - `["root", "props", "title"]`
 *
 * Depth-agnostic, so an array nested inside an array item is addressable.
 * `applyTranslatedStrings` is the exact inverse.
 */
export type FieldPath = PathSegment[];

export interface ExtractResult {
  strings: string[];
  paths: FieldPath[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

/**
 * Pull every human-readable string out of a serialized Puck document.
 *
 * Walks `content[]`, each `zones[*][]`, and `root.props`, resolving each
 * block's field shape from `config` so non-copy props — URLs, colours, ids,
 * enums, image pickers — are left alone. Recurses into array fields to any
 * depth. Pure: no network, no React, no DOM.
 *
 * Both halves take and return the serialized JSON rather than parsed data,
 * so a caller can hand a translated document straight back to storage without
 * a re-serialize that might reorder keys.
 */
export function extractTranslatableStrings(puckJson: string, config: Config): ExtractResult {
  const strings: string[] = [];
  const paths: FieldPath[] = [];

  let parsed: unknown;
  try {
    parsed = JSON.parse(puckJson);
  } catch {
    return { strings, paths };
  }
  if (!isRecord(parsed)) return { strings, paths };

  function visitFields(
    container: Record<string, unknown>,
    fields: Record<string, Field>,
    basePath: FieldPath,
  ): void {
    for (const [key, field] of Object.entries(fields)) {
      const value = container[key];

      // A slot holds whole *blocks*, not field-shaped items, so it recurses
      // through `visitBlock` (which resolves each child's own field shape)
      // rather than through `visitFields`. Without this, everything an author
      // nested inside a Columns or Container would be invisible to the
      // translator — the blocks are there, but nothing walks into them.
      if (field?.type === 'slot') {
        if (!Array.isArray(value)) continue;
        value.forEach((child: unknown, index: number) =>
          visitBlock(child, [...basePath, key, index]),
        );
        continue;
      }

      if (field?.type === 'array') {
        if (!Array.isArray(value)) continue;
        const arrayFields = (field as ArrayField).arrayFields as
          | Record<string, Field>
          | undefined;
        if (!arrayFields) continue;
        value.forEach((item: unknown, index: number) => {
          if (!isRecord(item)) return;
          // An array item's own fields may themselves include a slot —
          // `Columns.columns[].content` is exactly that shape.
          visitFields(item, arrayFields, [...basePath, key, index]);
        });
        continue;
      }

      if (isTranslatableField(key, field) && typeof value === 'string' && value.trim() !== '') {
        strings.push(value);
        paths.push([...basePath, key]);
      }
    }
  }

  function visitBlock(block: unknown, blockPath: FieldPath): void {
    if (!isRecord(block)) return;
    const props = block.props;
    if (!isRecord(props)) return;

    const type = typeof block.type === 'string' ? block.type : undefined;
    const fields = type ? config.components?.[type]?.fields : config.root?.fields;
    if (!fields) return;

    visitFields(props, fields as Record<string, Field>, [...blockPath, 'props']);
  }

  const content = parsed.content;
  if (Array.isArray(content)) {
    content.forEach((block: unknown, index: number) => visitBlock(block, ['content', index]));
  }

  // Pre-slots documents keep nested blocks here. `migrateContent` folds these
  // into slot props on load, but extraction runs against whatever is stored,
  // which may not have been through the editor since.
  const zones = parsed.zones;
  if (isRecord(zones)) {
    for (const [zoneKey, zoneBlocks] of Object.entries(zones)) {
      if (!Array.isArray(zoneBlocks)) continue;
      zoneBlocks.forEach((block: unknown, index: number) =>
        visitBlock(block, ['zones', zoneKey, index]),
      );
    }
  }

  const root = parsed.root;
  if (isRecord(root)) visitBlock(root, ['root']);

  return { strings, paths };
}
