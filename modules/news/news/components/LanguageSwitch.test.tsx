import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { LanguageSwitch, endonym } from './LanguageSwitch';

const alternates = [
  { locale: 'en', url: 'https://x.test/news/budget' },
  { locale: 'de', url: 'https://x.test/de/news/haushalt' },
  { locale: 'x-default', url: 'https://x.test/news/budget' },
];

describe('LanguageSwitch', () => {
  it('links the other languages, with hreflang and lang', () => {
    const html = renderToStaticMarkup(<LanguageSwitch alternates={alternates} current="en" />);

    expect(html).toContain('href="https://x.test/de/news/haushalt"');
    expect(html).toContain('hrefLang="de"');
    expect(html).toContain('lang="de"');
    expect(html).toContain('Deutsch');
  });

  it('leaves out the current language and x-default', () => {
    const html = renderToStaticMarkup(<LanguageSwitch alternates={alternates} current="en" />);

    expect(html).not.toContain('x-default');
    expect(html).not.toContain('/news/budget');
  });

  it('renders nothing for a monolingual article', () => {
    expect(renderToStaticMarkup(<LanguageSwitch alternates={[]} current="en" />)).toBe('');
    expect(renderToStaticMarkup(<LanguageSwitch alternates={undefined} />)).toBe('');
  });

  it('falls back to the code for an unknown tag', () => {
    expect(endonym('not a locale')).toBe('not a locale');
  });
});
