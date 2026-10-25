import { Head } from '@inertiajs/react';
import { BrandingHead } from '@simple-module-py/ui/components/BrandingHead';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { useState } from 'react';

type Action = 'confirm' | 'unsubscribe';

type Copy = Record<string, string>;

interface Props {
  action: Action;
  /** The link's token, sent back as `{t}` when the button is pressed. */
  token: string;
  /** The subscriber's language (`l` in the link), already one records ships. */
  locale: string;
  /** `POST` target: `/api/records/submissions/{confirm|unsubscribe}`. */
  endpoint: string;
  /** Every string, in `locale`, from the server (`public_submissions_views.py`). */
  copy: Copy;
}

type State = 'ready' | 'sending' | 'done' | 'already' | 'expired' | 'failed';

/** What a `POST` answered, as one of the page's states. */
async function send(endpoint: string, token: string): Promise<State> {
  const response = await fetch(endpoint, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ t: token }),
  });
  if (response.status === 410) return 'expired';
  if (!response.ok) return 'failed';
  const body = (await response.json().catch(() => ({}))) as { status?: string };
  return body.status === 'already_confirmed' ? 'already' : 'done';
}

/**
 * The landing page of a newsletter's confirm or unsubscribe link (#101).
 *
 * Opening it changes nothing — mail scanners fetch every link — so it shows
 * one button, and only pressing it posts the token. Anonymous, outside the
 * console: no layout, the site's branding, and the subscriber's language for
 * every word (the server sends them as `copy`; the console's own language
 * plays no part).
 */
export default function SubmissionAction({ action, token, locale, endpoint, copy }: Props) {
  const [state, setState] = useState<State>('ready');

  const press = async () => {
    setState('sending');
    try {
      setState(await send(endpoint, token));
    } catch {
      setState('failed');
    }
  };

  const result: Partial<Record<State, string>> = {
    done: copy.done,
    already: copy.already,
    expired: copy.expired,
  };
  const finished = state === 'done' || state === 'already' || state === 'expired';

  return (
    <main
      lang={locale}
      className="flex min-h-screen items-center justify-center bg-background px-4 py-16 text-foreground"
    >
      <BrandingHead />
      <Head title={copy.title}>
        <meta name="robots" content="noindex" />
        {/* The address carries a capability; the host's own header policy
            may override the server's `no-referrer`, so the page asks too. */}
        <meta name="referrer" content="no-referrer" />
      </Head>
      <section
        data-testid={`submission-action-${action}`}
        className="w-full max-w-md rounded-lg border bg-card p-8 text-center shadow-sm"
      >
        <h1 className="text-balance font-semibold text-2xl tracking-tight">{copy.title}</h1>
        {finished ? (
          <p className="mt-4 text-pretty" role="status" data-testid="submission-action-result">
            {result[state]}
          </p>
        ) : (
          <>
            <p className="mt-4 text-pretty text-muted-foreground">{copy.intro}</p>
            <Button
              type="button"
              className="mt-6"
              disabled={state === 'sending' || !token}
              onClick={() => void press()}
            >
              {state === 'sending' ? copy.sending : copy.button}
            </Button>
            {state === 'failed' && (
              <p className="mt-4 text-destructive text-sm" role="alert">
                {copy.failed}
              </p>
            )}
          </>
        )}
      </section>
    </main>
  );
}
