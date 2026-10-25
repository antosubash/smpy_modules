// @vitest-environment happy-dom
import * as React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

let shared: Record<string, unknown> = {};
vi.mock('@inertiajs/react', () => ({
  usePage: () => ({ props: shared, url: '/p/printed?x=1' }),
  Head: () => null,
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock('@simple-module-py/ui/components/BrandingHead', () => ({ BrandingHead: () => null }));

// The framework ui package ships JSX compiled with the classic runtime under
// vitest, so its components expect a global React.
(globalThis as { React?: unknown }).React = React;

const { PublicShell } = await import('./PublicShell');
const { default: PublicNotFound } = await import('../../pages/PublicNotFound');

type ShellProps = Parameters<typeof PublicShell>[0];

function mount(props: Partial<ShellProps> = {}): HTMLElement {
  document.body.innerHTML = renderToStaticMarkup(
    <PublicShell {...props}>
      <p>Author content</p>
    </PublicShell>,
  );
  return document.body.firstElementChild as HTMLElement;
}

beforeEach(() => {
  shared = { branding: { designPack: null } };
});

describe('PublicShell', () => {
  it('puts the skip link first, pointing at a focusable main', () => {
    const root = mount();
    const first = root.querySelector('a, button, [tabindex]');
    expect(first?.getAttribute('href')).toBe('#main');
    expect(first?.textContent).toBe('Skip to content');
    const main = root.querySelector('main');
    expect(main?.id).toBe('main');
    expect(main?.getAttribute('tabindex')).toBe('-1');
    expect(main?.textContent).toContain('Author content');
  });

  it('is a full-height column whose main takes the slack', () => {
    const root = mount();
    expect(root.className).toContain('min-h-dvh');
    expect(root.className).toContain('flex-col');
    expect(root.querySelector('main')?.className).toContain('flex-1');
  });

  it('puts the design pack class on the root, around the chrome too', () => {
    shared = { branding: { designPack: 'clinic' } };
    const root = mount();
    expect(root.classList.contains('clinic-root')).toBe(true);
    expect(root.classList.contains('pb-public')).toBe(true);
  });

  it('shows the draft bar only when the preview prop is set', () => {
    expect(mount().querySelector('[data-testid="preview-bar"]')).toBeNull();
    const root = mount({ preview: { editor_href: '/pagebuilder/7/edit', status: 'draft' } });
    const bar = root.querySelector('[data-testid="preview-bar"]');
    expect(bar?.getAttribute('role')).toBe('status');
    expect(bar?.textContent).toContain('Preview — this draft is not published');
    const back = bar?.querySelector('a');
    expect(back?.getAttribute('href')).toBe('/pagebuilder/7/edit');
    expect(back?.textContent).toBe('Back to editor');
  });

  it("prints the current Inertia page's absolute address", () => {
    const printed = mount().querySelector('.pb-print-url')?.textContent ?? '';
    expect(printed).toBe(new URL('/p/printed?x=1', window.location.origin).href);
  });

  it('renders no header or footer without a layout', () => {
    const root = mount();
    expect(root.querySelector('[data-testid="site-header"]')).toBeNull();
    expect(root.querySelector('[data-testid="site-footer"]')).toBeNull();
  });
});

describe('PublicNotFound', () => {
  it('says the page does not exist and links home, inside the shell', () => {
    document.body.innerHTML = renderToStaticMarkup(
      <PublicNotFound locale="en" home_href="/" site_name="Acme" />,
    );
    const block = document.querySelector('[data-testid="public-not-found"]');
    expect(block?.closest('main')?.id).toBe('main');
    expect(block?.querySelector('h1')?.textContent).toBe("This page doesn't exist");
    const home = block?.querySelector('a');
    expect(home?.getAttribute('href')).toBe('/');
    expect(home?.textContent).toBe('Go to the home page');
  });

  it("speaks the address's language when the server sends its copy", () => {
    const copy = {
      skip_to_content: 'Zum Inhalt springen',
      not_found: { title: 'Diese Seite gibt es nicht', body: 'Weg.', home: 'Zur Startseite' },
    };
    document.body.innerHTML = renderToStaticMarkup(
      <PublicNotFound locale="de" home_href="/" copy={copy} />,
    );
    expect(document.querySelector('a[href="#main"]')?.textContent).toBe('Zum Inhalt springen');
    expect(document.querySelector('h1')?.textContent).toBe('Diese Seite gibt es nicht');
    expect(document.querySelector('[data-testid="public-not-found"] a')?.textContent).toBe(
      'Zur Startseite',
    );
  });

  it('links to the home address the server names', () => {
    document.body.innerHTML = renderToStaticMarkup(
      <PublicNotFound locale="de" home_href="/site" />,
    );
    expect(document.querySelector('[data-testid="public-not-found"] a')?.getAttribute('href')).toBe(
      '/site',
    );
  });
});
