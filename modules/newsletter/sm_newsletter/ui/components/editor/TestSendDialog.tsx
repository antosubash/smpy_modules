import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@simple-module-py/ui/components/ui/dialog';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { useState } from 'react';

import { api, errorMessage } from '../../utils/api';
import { HttpError, isHttpStatus } from '../../utils/http';
import { keys, useT } from '../../utils/i18n';
import type { TestSendResult } from '../../utils/types';

const copy = keys.newsletter.test_send;
const errorKeys = keys.newsletter.errors as Record<string, string>;
const FIELD_ID = 'newsletter-test-send-recipients';
const ADDRESS = /^[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+$/;

const OUTCOMES: Record<string, string> = {
  accepted: copy.outcome.accepted,
  rejected: copy.outcome.rejected,
  unknown: copy.outcome.unknown,
  failed: copy.outcome.failed,
};

/** Addresses separated by commas or line breaks, trimmed, lower-cased, deduplicated. */
function parseRecipients(text: string): string[] {
  const found = text
    .split(/[\n,;]+/)
    .map((a) => a.trim().toLowerCase())
    .filter(Boolean);
  return [...new Set(found)];
}

interface Props {
  campaignId: number;
  max: number;
  /** Saves what is pending; resolves false when something stayed unsaved. The
   *  server sends the saved campaign, so a test never runs on stale text. */
  beforeSend?: () => Promise<boolean>;
  /** A block is unfinished, so the saved draft lacks it. */
  incomplete?: boolean;
  /** The host has no public base URL, so the server will refuse every test send. */
  baseUrlMissing?: boolean;
}

/** "Send test": the saved campaign to up to `max` addresses, with each one's outcome. */
export function TestSendDialog({ campaignId, max, beforeSend, incomplete, baseUrlMissing }: Props) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<TestSendResult[] | null>(null);

  const recipients = parseRecipients(text);
  const invalid = recipients.find((a) => !ADDRESS.test(a));
  const tooMany = recipients.length > max;
  const problem = tooMany
    ? t(copy.too_many, { max })
    : invalid
      ? t(copy.invalid_address, { address: invalid })
      : null;
  const canSend = !pending && recipients.length > 0 && problem === null;

  const change = (next: boolean) => {
    if (pending) return;
    setOpen(next);
    if (!next) {
      setError(null);
      setResults(null);
    }
  };

  const send = async () => {
    setPending(true);
    setError(null);
    setResults(null);
    try {
      if (beforeSend && !(await beforeSend())) {
        setError(t(copy.unsaved));
        return;
      }
      setResults((await api.testSend(campaignId, recipients)).results);
    } catch (e) {
      // The server's code wins (`public_base_url_required`, `sender_not_configured`);
      // a 422 with no catalogue entry is a malformed recipient list.
      const named = e instanceof HttpError && e.code !== null && Object.hasOwn(errorKeys, e.code);
      setError(isHttpStatus(e, 422) && !named ? t(copy.invalid_recipients) : errorMessage(e, t));
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={change}>
      <DialogTrigger asChild>
        <Button type="button" size="sm" variant="outline">
          {t(copy.trigger)}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (canSend) void send();
          }}
        >
          <DialogHeader>
            <DialogTitle>{t(copy.title)}</DialogTitle>
            <DialogDescription>{t(copy.description, { max })}</DialogDescription>
          </DialogHeader>

          <div className="grid gap-3 py-4">
            <Label htmlFor={FIELD_ID}>{t(copy.recipients)}</Label>
            <Textarea
              id={FIELD_ID}
              rows={4}
              value={text}
              disabled={pending}
              placeholder={t(copy.placeholder)}
              onChange={(e) => setText(e.target.value)}
            />
            {baseUrlMissing && <p className="text-sm text-amber-900">{t(copy.no_base_url)}</p>}
            {incomplete && <p className="text-sm text-amber-900">{t(copy.incomplete)}</p>}
            {problem && <p className="text-sm text-destructive">{problem}</p>}
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
            {results && (
              <ul aria-label={t(copy.results)} className="space-y-1 text-sm">
                {results.map((r) => (
                  <li key={r.recipient} className="flex justify-between gap-3">
                    <span className="truncate">{r.recipient}</span>
                    <span>
                      {Object.hasOwn(OUTCOMES, r.outcome) ? t(OUTCOMES[r.outcome]) : r.outcome}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={pending}
              onClick={() => change(false)}
            >
              {t(copy.close)}
            </Button>
            <Button type="submit" disabled={!canSend}>
              {pending ? t(copy.sending) : t(copy.send)}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
