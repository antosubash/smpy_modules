// @vitest-environment happy-dom
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import '../../../pagebuilder-blocks';
import {
  button,
  cleanup,
  fakeApi,
  flush,
  input,
  mount,
  pickCover,
  requests,
  type,
  writes,
} from '../media/test-dom';
import { SeoCard } from './SeoCard';

beforeEach(fakeApi);
afterEach(cleanup);
const image = () => input('#article-og-image');

describe('share image media picker', () => {
  it('offers the gallery only with the server capability', async () => {
    await mount(<SeoCard articleId={7} mediaPicker />);
    expect(button('Choose from media library')).toBeDefined();
  });
  it('keeps the URL field without a capability and never lists media', async () => {
    await mount(<SeoCard articleId={7} />);
    expect(button('Choose from media library')).toBeUndefined();
    await type(image(), 'https://external.example/photo.png');
    expect(image().value).toBe('https://external.example/photo.png');
    expect(requests.some((url) => url.includes('/pagebuilder/'))).toBe(false);
  });
  it('cancels without replacing the URL and returns focus to the browse button', async () => {
    await mount(<SeoCard articleId={7} mediaPicker />);
    await type(image(), 'https://external.example/keep.png');
    const browse = button('Choose from media library');
    if (!browse) throw new Error('Missing media picker button');
    browse.focus();
    await act(async () => browse.click());
    await flush();
    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
    await act(async () => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    });
    await flush();
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(image().value).toBe('https://external.example/keep.png');
    expect(document.activeElement).toBe(browse);
  });
  it('saves the picked URL and still accepts an external URL', async () => {
    await mount(<SeoCard articleId={7} mediaPicker />);
    await pickCover();
    expect(image().value).toBe('/media/default/cover.webp');
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    await act(async () => button('Save search settings')?.click());
    expect(writes.at(-1)?.og_image).toBe('/media/default/cover.webp');
    await type(image(), 'https://external.example/photo.png');
    await act(async () => button('Save search settings')?.click());
    expect(writes.at(-1)?.og_image).toBe('https://external.example/photo.png');
  });
});
