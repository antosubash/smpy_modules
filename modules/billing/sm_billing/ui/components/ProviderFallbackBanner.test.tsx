// @vitest-environment happy-dom

import * as React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ProviderFallbackBanner } from './ProviderFallbackBanner';

(globalThis as unknown as { React: unknown }).React = React;

const REASON = "provider is 'stripe' but stripe_secret_key is not set";
const render = (error: string) => renderToStaticMarkup(<ProviderFallbackBanner error={error} />);

describe('ProviderFallbackBanner', () => {
  it('says why Stripe fell back to manual (#200)', () => {
    const html = render(REASON);
    expect(html).toContain('Stripe is configured but not in use');
    expect(html).toContain('stripe_secret_key is not set');
    expect(html).toContain('Stripe connection');
    expect(html).not.toContain('`');
  });

  it('renders nothing when the chosen provider is the one running', () => {
    expect(render('')).toBe('');
  });
});
