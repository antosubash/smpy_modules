/**
 * The CAPTCHA a host may require on website submissions (#101, design §5).
 *
 * Rendered only when the form's definition names a provider, so a page whose
 * forms need none never loads a third-party script. Both providers have the
 * same explicit-render API (`render(element, {sitekey, callback})`); the
 * response reaches the form through `onToken` and is checked server-side.
 * `round` changes when the widget must start over — a fresh definition, or a
 * response the provider rejected — since a response is good for one check.
 *
 * The provider's host has to be allowed by the public pages' CSP
 * (`script-src` and `frame-src`); records logs a warning at startup when
 * pagebuilder's `public_csp` does not name it.
 */

import { useEffect, useRef } from 'react';

type Provider = 'turnstile' | 'hcaptcha';

type Api = {
  render: (element: HTMLElement, options: Record<string, unknown>) => string | number;
  remove?: (id: string | number) => void;
};

const SCRIPTS: Record<Provider, { src: string; global: string }> = {
  turnstile: {
    src: 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit',
    global: 'turnstile',
  },
  hcaptcha: { src: 'https://js.hcaptcha.com/1/api.js?render=explicit', global: 'hcaptcha' },
};

const loading = new Map<Provider, Promise<Api>>();

/** The provider's API, loading its script once per page. */
export function loadCaptcha(provider: Provider): Promise<Api> {
  const known = loading.get(provider);
  if (known) return known;
  const { src, global } = SCRIPTS[provider];
  const promise = new Promise<Api>((resolve, reject) => {
    const ready = () => {
      const api = (window as unknown as Record<string, Api | undefined>)[global];
      if (api) resolve(api);
      else reject(new Error(`${provider} did not load`));
    };
    const script = document.createElement('script');
    script.src = src;
    script.async = true;
    script.onload = ready;
    script.onerror = () => {
      loading.delete(provider);
      reject(new Error(`${provider} could not be loaded`));
    };
    document.head.appendChild(script);
  });
  loading.set(provider, promise);
  return promise;
}

export function CaptchaWidget({
  provider,
  siteKey,
  round,
  lang,
  onToken,
}: {
  provider: Provider;
  siteKey: string;
  round: number;
  lang?: string;
  onToken: (token: string) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const callback = useRef(onToken);
  callback.current = onToken;

  // biome-ignore lint/correctness/useExhaustiveDependencies: `round` re-renders the widget on purpose
  useEffect(() => {
    let cancelled = false;
    let id: string | number | undefined;
    let api: Api | undefined;
    loadCaptcha(provider)
      .then((loaded) => {
        if (cancelled || !box.current) return;
        api = loaded;
        box.current.replaceChildren();
        id = loaded.render(box.current, {
          sitekey: siteKey,
          ...(lang ? (provider === 'turnstile' ? { language: lang } : { hl: lang }) : {}),
          callback: (token: string) => callback.current(token),
          'expired-callback': () => callback.current(''),
        });
      })
      .catch(() => callback.current(''));
    return () => {
      cancelled = true;
      if (api?.remove && id !== undefined) api.remove(id);
    };
  }, [provider, siteKey, round, lang]);

  return <div ref={box} className="min-h-[65px]" data-testid="records-form-captcha" />;
}
