import { Button } from '@simple-module-py/ui/components/ui/button';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { useState } from 'react';

import { keys, useT } from '../../utils/i18n';
import {
  buildJsonSchema,
  fieldNameError,
  type SchemaField,
  schemaToFields,
} from '../../utils/schemaFields';
import type { JsonSchema } from '../../utils/types-prompts';
import { SchemaFieldBuilder } from './SchemaFieldBuilder';

/** What the editor holds: the schema to save, or `null` while the JSON does not parse. */
export type SchemaDraft = { schema: JsonSchema | null };

function parse(text: string): JsonSchema | null {
  try {
    const value = JSON.parse(text);
    return typeof value === 'object' && value !== null && !Array.isArray(value) ? value : null;
  } catch {
    return null;
  }
}

/**
 * A structured answer's JSON Schema, edited as fields or as JSON.
 *
 * Fields are offered only for a schema they express exactly; a richer one
 * (a preset's bounds or nesting) opens as JSON with a note, so saving never
 * weakens it. The server checks the schema again on save.
 */
export function SchemaEditor({
  initial,
  onChange,
  disabled = false,
}: {
  initial: JsonSchema;
  onChange: (draft: SchemaDraft) => void;
  disabled?: boolean;
}) {
  const { t } = useT();
  const [fields, setFields] = useState<SchemaField[] | null>(() => schemaToFields(initial));
  const [mode, setMode] = useState<'fields' | 'json'>(() => (fields ? 'fields' : 'json'));
  const [text, setText] = useState(() => JSON.stringify(initial, null, 2));
  const advanced = schemaToFields(initial) === null;
  const parsed = parse(text);
  const backToFields = parsed ? schemaToFields(parsed) : null;

  const editFields = (next: SchemaField[]) => {
    setFields(next);
    // A reserved name is refused: nothing to save until it is renamed.
    const refused = next.some((f) => fieldNameError(f.name));
    onChange({ schema: refused ? null : buildJsonSchema(next) });
  };
  const editText = (next: string) => {
    setText(next);
    onChange({ schema: parse(next) });
  };
  const toJson = () => {
    if (mode === 'json') return; // keep what was typed
    setText(JSON.stringify(buildJsonSchema(fields ?? []), null, 2));
    setMode('json');
  };
  const toFields = () => {
    if (!backToFields) return;
    setFields(backToFields);
    setMode('fields');
  };

  return (
    <div className="space-y-2" data-testid="images-schema-editor" data-mode={mode}>
      <div className="flex gap-2">
        <Button
          type="button"
          size="sm"
          variant={mode === 'fields' ? 'default' : 'outline'}
          disabled={disabled || (mode === 'json' && !backToFields)}
          data-testid="images-schema-mode-fields"
          onClick={toFields}
        >
          {t(keys.images.prompts.schema.fields)}
        </Button>
        <Button
          type="button"
          size="sm"
          variant={mode === 'json' ? 'default' : 'outline'}
          disabled={disabled}
          data-testid="images-schema-mode-json"
          onClick={toJson}
        >
          {t(keys.images.prompts.schema.json)}
        </Button>
      </div>
      {mode === 'fields' && fields ? (
        <SchemaFieldBuilder fields={fields} onChange={editFields} disabled={disabled} />
      ) : (
        <>
          {advanced && (
            <p className="text-sm text-muted-foreground" data-testid="images-schema-advanced">
              {t(keys.images.prompts.schema.advanced)}
            </p>
          )}
          <Textarea
            aria-label={t(keys.images.prompts.schema.json)}
            data-testid="images-schema-json"
            className="font-mono text-xs"
            rows={10}
            value={text}
            disabled={disabled}
            onChange={(e) => editText(e.target.value)}
          />
          {parsed === null && (
            <p className="text-sm text-destructive">{t(keys.images.prompts.schema.invalid_json)}</p>
          )}
        </>
      )}
    </div>
  );
}
