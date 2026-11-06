/**
 * Who a campaign goes to: the whole list, one tag, or a saved segment, with a
 * live "about N subscribers" under it. A choice is saved through the editor's
 * `saveMeta` (`onChange({ audience })`), so it shares the debounce, the
 * revision and the flush of every other edit. A tag or segment not picked yet
 * saves nothing and asks for no count.
 */

import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { RadioGroup, RadioGroupItem } from '@simple-module-py/ui/components/ui/radio-group';
import { useEffect, useId, useState } from 'react';

import { useAudienceCount } from '../../hooks/useAudienceCount';
import { useListFields } from '../../hooks/useListFields';
import type { MetaPatch } from '../../hooks/usePendingEdits';
import { api } from '../../utils/api';
import { type AudienceChoice, formatAudience, parseAudience } from '../../utils/audience';
import { keys, useT } from '../../utils/i18n';
import type { CampaignDetail, Segment } from '../../utils/types';

const copy = keys.newsletter.audience;

type Kind = AudienceChoice['kind'];

interface Props {
  campaign: CampaignDetail;
  readOnly: boolean;
  onChange: (patch: MetaPatch) => void;
}

export function AudiencePicker({ campaign, readOnly, onChange }: Props) {
  const { t } = useT();
  const id = useId();
  const listKey = campaign.list_type_key;
  const { fields } = useListFields(listKey);
  const [segments, setSegments] = useState<Segment[] | null>(null);
  const [choice, setChoice] = useState<AudienceChoice>(() => parseAudience(campaign.audience));
  const [pending, setPending] = useState<Kind | null>(null);

  useEffect(() => {
    let live = true;
    api
      .listSegments(listKey)
      .then((s) => live && setSegments(s))
      .catch(() => live && setSegments([]));
    return () => {
      live = false;
    };
  }, [listKey]);

  const tagChoices = fields?.find((f) => f.key === 'tags')?.choices ?? [];
  const hasTags = fields === null || fields.some((f) => f.key === 'tags');
  const kind: Kind = pending ?? choice.kind;
  const complete = pending === null;
  const audience = complete ? formatAudience(choice) : '';
  const { count, loading } = useAudienceCount(listKey, audience);

  const apply = (next: AudienceChoice) => {
    setChoice(next);
    setPending(null);
    onChange({ audience: formatAudience(next) });
  };
  const pick = (next: Kind) => {
    if (next === 'all') return apply({ kind: 'all' });
    if (next === choice.kind) return setPending(null);
    setPending(next);
  };

  const missing =
    choice.kind === 'segment' &&
    segments !== null &&
    !segments.some((s) => s.id === choice.segmentId);

  const kinds: Kind[] = hasTags ? ['all', 'tag', 'segment'] : ['all', 'segment'];

  return (
    <section aria-label={t(copy.title)} className="space-y-2 border-b px-4 py-3">
      <p className="text-sm font-medium">{t(copy.title)}</p>
      <RadioGroup
        value={kind}
        onValueChange={(v) => pick(v as Kind)}
        disabled={readOnly}
        className="flex flex-wrap gap-4"
      >
        {kinds.map((k) => (
          <div key={k} className="flex items-center gap-2">
            <RadioGroupItem id={`${id}-${k}`} value={k} />
            <Label htmlFor={`${id}-${k}`}>{t(copy[k])}</Label>
          </div>
        ))}
      </RadioGroup>

      {kind === 'tag' && (
        <div className="flex items-center gap-2">
          <Label htmlFor={`${id}-tag`}>{t(copy.tag_label)}</Label>
          {tagChoices.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t(copy.no_tags)}</p>
          ) : (
            <NativeSelect
              id={`${id}-tag`}
              disabled={readOnly}
              value={choice.kind === 'tag' && !pending ? choice.tag : ''}
              onChange={(e) => e.target.value && apply({ kind: 'tag', tag: e.target.value })}
            >
              <option value="" disabled>
                —
              </option>
              {tagChoices.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </NativeSelect>
          )}
        </div>
      )}

      {kind === 'segment' && (
        <div className="flex items-center gap-2">
          <Label htmlFor={`${id}-segment`}>{t(copy.segment_label)}</Label>
          {segments !== null && segments.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t(copy.no_segments)}</p>
          ) : (
            <NativeSelect
              id={`${id}-segment`}
              disabled={readOnly}
              value={choice.kind === 'segment' && !pending && !missing ? choice.segmentId : ''}
              onChange={(e) =>
                e.target.value && apply({ kind: 'segment', segmentId: Number(e.target.value) })
              }
            >
              <option value="" disabled>
                —
              </option>
              {(segments ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </NativeSelect>
          )}
        </div>
      )}

      {missing && (
        <p role="alert" className="text-sm text-destructive">
          {t(copy.segment_missing)}
        </p>
      )}
      {complete && !missing && (
        <p className="text-sm text-muted-foreground" aria-live="polite">
          {count !== null && !loading ? t(copy.count, { count }) : t(copy.count_loading)}
        </p>
      )}
    </section>
  );
}
