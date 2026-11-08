/**
 * The campaign's own fields: name, subject, preview text, sender name and
 * reply-to. Saved through `useCampaignEditor().saveMeta`, with the body's
 * debounce, so a burst of typing in both is one PATCH.
 *
 * The form keeps what is typed itself rather than reading the campaign back:
 * an autosave answer that lands mid-word would otherwise rewind the input.
 * Limits match `web/schemas/campaigns.py`.
 */

import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { useEffect, useId, useRef, useState } from 'react';

import type { MetaPatch } from '../../hooks/useCampaignEditor';
import { keys, useT } from '../../utils/i18n';
import type { CampaignDetail } from '../../utils/types';

const copy = keys.newsletter.editor.meta;

type MetaField = Exclude<keyof MetaPatch, 'audience'>;

const FIELDS: { name: MetaField; label: string; hint?: string; max: number; type?: string }[] = [
  { name: 'name', label: copy.name, max: 200 },
  { name: 'subject', label: copy.subject, max: 300 },
  { name: 'preheader', label: copy.preheader, hint: copy.preheader_hint, max: 300 },
  { name: 'from_name', label: copy.from_name, hint: copy.from_name_hint, max: 200 },
  { name: 'reply_to', label: copy.reply_to, hint: copy.reply_to_hint, max: 254, type: 'email' },
];

/** What a field sends: an optional sender field left blank is `null` (the
 *  settings' value applies). A blank name, and a reply-to the input itself
 *  finds invalid (`foo@` mid-typing), are not sent at all: the server would
 *  refuse the whole PATCH, and the body edits riding with it. */
export function toPatch(name: MetaField, value: string, valid = true): MetaPatch | null {
  if (!valid) return null;
  if (name === 'from_name' || name === 'reply_to') {
    return { [name]: value.trim() === '' ? null : value };
  }
  if (name === 'name' && value.trim() === '') return null;
  return { [name]: value };
}

/** Closer to the server's `EmailStr` than the browser's `type=email` (which
 *  accepts `a@b`, `.a@b.io`, `a@b.1`): a value the server refuses would make it
 *  refuse the whole PATCH. Stricter on international domains, never looser. */
const EMAIL = /^[^\s@.]+(\.[^\s@.]+)*@([A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]+$/;

export function isReplyTo(value: string): boolean {
  return value.trim() === '' || EMAIL.test(value);
}

/** Why a typed value cannot be saved, as a catalogue key; null when it can. */
export function fieldError(name: MetaField, value: string, valid = true): string | null {
  if (name === 'name' && value.trim() === '') return copy.name_required;
  if (!valid) return copy.reply_to_invalid;
  return null;
}

interface CampaignMetaProps {
  campaign: CampaignDetail;
  readOnly: boolean;
  onChange: (patch: MetaPatch) => void;
  /** A field's value cannot be saved (true) or was fixed (false). */
  onInvalid?: (field: MetaField, invalid: boolean) => void;
}

export function CampaignMeta({ campaign, readOnly, onChange, onInvalid }: CampaignMetaProps) {
  const { t } = useT();
  const idPrefix = useId();
  const [values, setValues] = useState<Record<MetaField, string>>(() => ({
    name: campaign.name,
    subject: campaign.subject,
    preheader: campaign.preheader,
    from_name: campaign.from_name ?? '',
    reply_to: campaign.reply_to ?? '',
  }));

  const [errors, setErrors] = useState<Partial<Record<MetaField, string>>>({});

  // A remount (card refresh, reload) drops the typed value and its message, so the
  // editor must not keep counting that field as unsaveable.
  const reported = useRef(new Set<MetaField>());
  useEffect(() => {
    const pending = reported.current;
    return () => {
      for (const field of pending) onInvalid?.(field, false);
    };
  }, [onInvalid]);

  function change(name: MetaField, input: HTMLInputElement) {
    const value = input.value;
    setValues((v) => ({ ...v, [name]: value }));
    const valid = input.checkValidity() && (name !== 'reply_to' || isReplyTo(value));
    const problem = fieldError(name, value, valid);
    setErrors((e) => ({ ...e, [name]: problem ?? undefined }));
    if (problem) reported.current.add(name);
    else reported.current.delete(name);
    onInvalid?.(name, problem !== null);
    const patch = toPatch(name, value, valid);
    if (patch) onChange(patch);
  }

  return (
    <section aria-label={t(copy.title)} className="grid gap-3 border-b px-4 py-3 md:grid-cols-5">
      {FIELDS.map((field) => {
        const id = `${idPrefix}-${field.name}`;
        return (
          <div key={field.name} className="space-y-1">
            <Label htmlFor={id}>{t(field.label)}</Label>
            <Input
              id={id}
              type={field.type ?? 'text'}
              value={values[field.name]}
              maxLength={field.max}
              readOnly={readOnly}
              aria-invalid={errors[field.name] ? true : undefined}
              aria-describedby={
                [errors[field.name] ? `${id}-error` : '', field.hint ? `${id}-hint` : '']
                  .filter(Boolean)
                  .join(' ') || undefined
              }
              onChange={(e) => change(field.name, e.target)}
            />
            {errors[field.name] && (
              <p id={`${id}-error`} role="alert" className="text-xs text-destructive">
                {t(errors[field.name] as string)}
              </p>
            )}
            {field.hint && (
              <p id={`${id}-hint`} className="text-xs text-muted-foreground">
                {t(field.hint)}
              </p>
            )}
          </div>
        );
      })}
    </section>
  );
}
