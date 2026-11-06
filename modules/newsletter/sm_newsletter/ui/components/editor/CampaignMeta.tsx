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
import { useId, useState } from 'react';

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

interface CampaignMetaProps {
  campaign: CampaignDetail;
  readOnly: boolean;
  onChange: (patch: MetaPatch) => void;
}

export function CampaignMeta({ campaign, readOnly, onChange }: CampaignMetaProps) {
  const { t } = useT();
  const idPrefix = useId();
  const [values, setValues] = useState<Record<MetaField, string>>(() => ({
    name: campaign.name,
    subject: campaign.subject,
    preheader: campaign.preheader,
    from_name: campaign.from_name ?? '',
    reply_to: campaign.reply_to ?? '',
  }));

  function change(name: MetaField, input: HTMLInputElement) {
    const value = input.value;
    setValues((v) => ({ ...v, [name]: value }));
    const patch = toPatch(name, value, input.checkValidity());
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
              aria-describedby={field.hint ? `${id}-hint` : undefined}
              onChange={(e) => change(field.name, e.target)}
            />
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
