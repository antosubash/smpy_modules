/** Create or edit a segment: a name, up to ten rules and the live count they match. */

import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@simple-module-py/ui/components/ui/dialog';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { useEffect, useState } from 'react';

import { useSegmentPreview } from '../../hooks/useSegmentPreview';
import { api, errorMessage } from '../../utils/api';
import { HttpError, isCode } from '../../utils/http';
import { keys, useT } from '../../utils/i18n';
import { emptyRule } from '../../utils/rules';
import type { ListField, Rule, Segment } from '../../utils/types';
import { RuleRow } from './RuleRow';

const copy = keys.newsletter.segments;
export const MAX_RULES = 10;

/** The rule a 422 `rules[i]: …` detail names, if any. */
export function invalidRuleIndex(e: unknown): number | null {
  if (!isCode(e, 'invalid_segment') || !(e instanceof HttpError)) return null;
  const match = /^rules\[(\d+)\]/.exec(e.message);
  return match ? Number(match[1]) : null;
}

interface Props {
  listKey: string;
  segment: Segment | null;
  fields: ListField[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: (s: Segment) => void;
}

export function SegmentEditorDialog({
  listKey,
  segment,
  fields,
  open,
  onOpenChange,
  onSaved,
}: Props) {
  const { t } = useT();
  const [name, setName] = useState('');
  const [rules, setRules] = useState<Rule[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [badRow, setBadRow] = useState<number | null>(null);
  const preview = useSegmentPreview(listKey, rules);

  useEffect(() => {
    if (!open) return;
    setName(segment?.name ?? '');
    setRules(segment?.rules ?? []);
    setError(null);
    setBadRow(null);
  }, [open, segment]);

  const edit = (next: Rule[]) => {
    setRules(next);
    setBadRow(null);
  };

  const save = async () => {
    setPending(true);
    setError(null);
    setBadRow(null);
    try {
      const saved = segment
        ? await api.patchSegment(segment.id, { name: name.trim(), rules })
        : await api.createSegment({ name: name.trim(), list_type_key: listKey, rules });
      onSaved(saved);
      onOpenChange(false);
    } catch (e) {
      setBadRow(invalidRuleIndex(e));
      setError(errorMessage(e, t));
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent className="sm:max-w-3xl">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!pending && name.trim()) void save();
          }}
        >
          <DialogHeader>
            <DialogTitle>{t(segment ? copy.title_edit : copy.title_new)}</DialogTitle>
            <DialogDescription>{t(copy.description)}</DialogDescription>
          </DialogHeader>

          <div className="grid gap-3 py-4">
            <Label htmlFor="newsletter-segment-name">{t(copy.name_label)}</Label>
            <Input
              id="newsletter-segment-name"
              value={name}
              maxLength={200}
              disabled={pending}
              onChange={(e) => setName(e.target.value)}
            />

            <p className="text-sm font-medium">{t(copy.rules)}</p>
            <div className="space-y-2">
              {rules.map((rule, i) => (
                <RuleRow
                  // Rows have no identity of their own; an index key keeps focus while typing.
                  // biome-ignore lint/suspicious/noArrayIndexKey: see above
                  key={i}
                  rule={rule}
                  fields={fields}
                  disabled={pending}
                  invalid={badRow === i}
                  onChange={(r) => edit(rules.map((x, j) => (j === i ? r : x)))}
                  onRemove={() => edit(rules.filter((_, j) => j !== i))}
                />
              ))}
            </div>
            <div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={pending || fields.length === 0 || rules.length >= MAX_RULES}
                title={rules.length >= MAX_RULES ? t(copy.max_rules) : undefined}
                onClick={() => edit([...rules, emptyRule(fields[0])])}
              >
                {t(copy.add_rule)}
              </Button>
            </div>

            {preview.error ? (
              <p role="alert" className="text-sm text-destructive">
                {preview.error}
              </p>
            ) : (
              <p className="text-sm text-muted-foreground" aria-live="polite">
                {preview.count === null
                  ? t(copy.count_loading)
                  : t(copy.count, { count: preview.count })}
              </p>
            )}
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={pending}
              onClick={() => onOpenChange(false)}
            >
              {t(copy.cancel)}
            </Button>
            <Button type="submit" disabled={pending || !name.trim()}>
              {pending ? t(copy.saving) : t(copy.save)}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
