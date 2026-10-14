// @vitest-environment happy-dom
import * as React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

let shared: Record<string, unknown> = {};
vi.mock('@inertiajs/react', () => ({
  usePage: () => ({ props: shared }),
}));

// The framework ui package ships JSX sources compiled with the classic runtime
// under vitest, so its components expect a global React.
(globalThis as { React?: unknown }).React = React;

import type { SiteHeaderWidgetProps } from './site-header-widget';

const { SiteHeaderRender, SiteHeaderWidget } = await import('./site-header-widget');
const { resolveCta } = await import('./site-header-account');

const base: Record<string, unknown> = {
  ...(SiteHeaderWidget.defaultProps as object),
  ctaLabel: 'Sign in',
  ctaHref: '/users/login',
};
const i18n = (supportedLocales: string[]) => ({
  locale: 'en',
  supportedLocales,
  messages: {},
});
const render = (props: Record<string, unknown> = {}) =>
  renderToStaticMarkup(
    <SiteHeaderRender {...({ ...base, ...props } as unknown as SiteHeaderWidgetProps)} />,
  );

beforeEach(() => {
  shared = { auth: { isAuthenticated: false }, i18n: i18n(['en', 'fr']) };
});

describe('SiteHeader locale switcher', () => {
  it('is hidden unless showLocaleSwitcher is set', () => {
    expect(render()).not.toContain('/i18n/set-locale');
  });

  it('renders the shared switcher when enabled on a multi-locale install', () => {
    const out = render({ showLocaleSwitcher: true });
    expect(out).toContain('/i18n/set-locale');
    expect(out).toContain('>EN<');
  });

  it('stays hidden on a single-locale install', () => {
    shared = { auth: {}, i18n: i18n(['en']) };
    expect(render({ showLocaleSwitcher: true })).not.toContain('>EN<');
  });

  it('exposes the toggle as an editor field defaulting to off', () => {
    expect(SiteHeaderWidget.fields).toHaveProperty('showLocaleSwitcher');
    expect(SiteHeaderWidget.defaultProps?.showLocaleSwitcher).toBe(false);
  });
});

describe('SiteHeader auth-aware CTA', () => {
  const props = { signedInLabel: 'Dashboard', signedInHref: '/dashboard/' };

  it('shows the anonymous CTA to a visitor', () => {
    const out = render(props);
    expect(out).toContain('Sign in');
    expect(out).not.toContain('Dashboard');
  });

  it('switches to the signed-in label and link with a session', () => {
    shared = { auth: { isAuthenticated: true } };
    const out = render(props);
    expect(out).toContain('Dashboard');
    expect(out).toContain('href="/dashboard/"');
    expect(out).not.toContain('>Sign in<');
  });

  it('keeps the CTA for a signed-in visitor when no signed-in label is set', () => {
    shared = { auth: { isAuthenticated: true } };
    expect(render()).toContain('>Sign in<');
  });

  it('falls back to the CTA link when only the label is set', () => {
    expect(resolveCta(true, { label: 'Sign in', href: '/x' }, { label: 'Hi', href: '' })).toEqual({
      label: 'Hi',
      href: '/x',
    });
  });
});
