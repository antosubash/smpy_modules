// @vitest-environment happy-dom
import { type Data, Puck } from '@puckeditor/core';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import '../../../pagebuilder-blocks';
import { translate } from '../../utils/i18n';
import {
  button,
  cleanup,
  fakeApi,
  input,
  mount,
  pickCover,
  requests,
  type,
} from '../media/test-dom';
import { articlePuckConfig } from './articlePuckConfig';
import { localizeConfig } from './localizeConfig';
import { withMediaPicker } from './mediaPickerConfig';

beforeEach(fakeApi);
afterEach(cleanup);
let saved: Data;
async function editor(enabled: boolean, alt = '', readOnly = false) {
  const config = localizeConfig(withMediaPicker(articlePuckConfig, enabled), translate);
  saved = {
    root: { props: {} },
    content: [
      {
        type: 'Image',
        props: {
          id: 'image-1',
          url: '',
          alt,
          caption: '',
          credit: '',
        },
      },
    ],
  };
  await mount(
    <Puck
      config={config}
      data={saved}
      iframe={{ enabled: false }}
      permissions={{ edit: !readOnly }}
      ui={{ itemSelector: { index: 0 } }}
      onChange={(data) => {
        saved = data;
      }}
    >
      <Puck.Fields />
      <Puck.Preview />
    </Puck>,
  );
}
const url = () => input();

describe('article body Image picker', () => {
  it('offers the library alongside URL entry with the capability', async () => {
    await editor(true);
    expect(button('Choose from media library')).toBeDefined();
    await type(url(), 'https://external.example/photo.png');
    expect(saved.content[0].props.url).toBe('https://external.example/photo.png');
  });
  it('keeps the original URL field without the capability', async () => {
    await editor(false);
    expect(button('Choose from media library')).toBeUndefined();
    await type(url(), 'https://external.example/photo.png');
    expect(saved.content[0].props.url).toBe('https://external.example/photo.png');
    expect(requests.some((u) => u.includes('/pagebuilder/'))).toBe(false);
  });
  it('stores the chosen URL and fills an empty alt, preserving other block props', async () => {
    await editor(true);
    await pickCover();
    expect(saved.content[0].props).toMatchObject({
      id: 'image-1',
      url: '/media/default/cover.webp',
      alt: 'A green canopy',
      caption: '',
      credit: '',
    });
    await type(url(), 'https://external.example/photo.png');
    expect(saved.content[0].props.url).toBe('https://external.example/photo.png');
    expect(saved.content[0].props.alt).toBe('A green canopy');
  });
  it('preserves alt text an editor already wrote', async () => {
    await editor(true, 'My description');
    await pickCover();
    expect(saved.content[0].props.alt).toBe('My description');
    expect(saved.content[0].props.url).toBe('/media/default/cover.webp');
  });
  it('disables picking on a read-only block', async () => {
    await editor(true, '', true);
    expect(button('Choose from media library')?.disabled).toBe(true);
  });
});
