import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useDocumentLang } from './useDocumentLang';

// No DOM and no React renderer in this environment: run the effect at once and
// hand back its cleanup, against a stand-in `<html>` element.
let cleanup: (() => void) | undefined;
vi.mock('react', () => ({
  useEffect: (effect: () => (() => void) | undefined) => {
    cleanup = effect();
  },
}));

const root = { lang: '', dataset: {} as Record<string, string> };

beforeEach(() => {
  cleanup = undefined;
  root.lang = 'en';
  root.dataset = { shellLang: 'en' };
  vi.stubGlobal('document', { documentElement: root });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('useDocumentLang', () => {
  it("sets the page's language, and gives back the shell's on leaving", () => {
    useDocumentLang('de');
    expect(root.lang).toBe('de');

    cleanup?.();
    expect(root.lang).toBe('en');
  });

  it("restores the shell's language even when the server already rewrote it", () => {
    // A German page reached directly: the server served `lang="de"` and kept
    // the shell's own value beside it.
    root.lang = 'de';
    useDocumentLang('de');

    cleanup?.();
    expect(root.lang).toBe('en');
  });

  it('leaves the document alone without a locale', () => {
    useDocumentLang(undefined);
    expect(root.lang).toBe('en');
    expect(cleanup).toBeUndefined();
  });
});
