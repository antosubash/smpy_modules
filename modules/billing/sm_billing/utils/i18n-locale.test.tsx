// @vitest-environment happy-dom
import { updateI18n } from '@simple-module-py/i18n';
import * as React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it } from 'vitest';

import { useT } from './i18n';

(globalThis as unknown as { React: unknown }).React = React;

function Probe() {
  return <span>{useT().locale}</span>;
}

describe('useT().locale', () => {
  afterEach(() => updateI18n({ locale: 'en', messages: {} }));

  it('is the console language, for Intl formatting (#189)', () => {
    expect(renderToStaticMarkup(<Probe />)).toBe('<span>en</span>');
    updateI18n({ locale: 'de', messages: {} });
    expect(renderToStaticMarkup(<Probe />)).toBe('<span>de</span>');
  });
});
