import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@inertiajs/react', () => ({ router: { visit: vi.fn() } }));

import { TranslationsPanel } from './TranslationsPanel';

function html(disabled: boolean): string {
  return renderToStaticMarkup(
    <TranslationsPanel
      pageId={7}
      locale="en"
      translations={[
        { id: 7, locale: 'en', slug: 'about', title: 'About', status: 'draft', trashed: false },
      ]}
      locales={['en', 'de']}
      defaultLocale="en"
      publicPrefix="/p"
      onError={() => {}}
      disabled={disabled}
    />,
  );
}

const ADD = /<button[^>]*data-testid="add-translation-de"[^>]*>/;

describe('TranslationsPanel', () => {
  it('offers the missing language', () => {
    const button = html(false).match(ADD)?.[0] ?? '';
    expect(button).not.toBe('');
    expect(button).not.toContain(' disabled=""');
  });

  it('does not offer a translation of a page that is gone (#448)', () => {
    expect(html(true).match(ADD)?.[0]).toContain(' disabled=""');
  });
});
