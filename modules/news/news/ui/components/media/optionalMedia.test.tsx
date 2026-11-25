// @vitest-environment happy-dom
import { Puck } from '@puckeditor/core';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { articlePuckConfig } from '../body/articlePuckConfig';
import { withMediaPicker } from '../body/mediaPickerConfig';
import { SeoCard } from '../editor/SeoCard';
import { button, cleanup, directWrite, fakeApi, input, mount, requests, type } from './test-dom';

// Deliberately no pagebuilder-blocks import: a host without that package.
beforeEach(fakeApi);
afterEach(cleanup);

describe('news without the optional media UI', () => {
  it('keeps share image URL entry even with a stale server capability', async () => {
    await mount(<SeoCard articleId={7} writeArticle={directWrite} mediaPicker />);
    expect(button('Choose from media library')).toBeUndefined();
    const image = input('#article-og-image');
    await type(image, 'https://external.example/photo.png');
    expect(image.value).toBe('https://external.example/photo.png');
    expect(requests.some((url) => url.includes('/pagebuilder/'))).toBe(false);
  });
  it('keeps the Image URL field with no registered picker', async () => {
    let picked = '';
    await mount(
      <Puck
        config={withMediaPicker(articlePuckConfig, true)}
        data={{
          content: [
            {
              type: 'Image',
              props: {
                id: 'image-1',
                url: '',
                alt: '',
                caption: '',
                credit: '',
              },
            },
          ],
          root: { props: {} },
        }}
        iframe={{ enabled: false }}
        ui={{ itemSelector: { index: 0 } }}
        onChange={(data) => {
          const item = data.content[0];
          if (item.type === 'Image') picked = item.props.url;
        }}
      >
        <Puck.Fields />
        <Puck.Preview />
      </Puck>,
    );
    expect(button('Choose from media library')).toBeUndefined();
    await type(input(), 'https://external.example/body.png');
    expect(picked).toBe('https://external.example/body.png');
    expect(requests).toEqual([]);
  });
});
