// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { mount } from '../../test-dom';
import type { TypeMetadataValues } from './types';

const { TypeMetadataForm } = await import('./TypeMetadataForm');

const values = (over: Partial<TypeMetadataValues>): TypeMetadataValues => ({
  key: '',
  label: '',
  labelPlural: '',
  description: '',
  icon: '',
  isPublic: false,
  allowedRoles: [],
  displayField: '',
  slugField: '',
  translatable: false,
  collection: '',
  showInMenu: false,
  publicSubmissions: null,
  ...over,
});

const render = (over: Partial<TypeMetadataValues>) =>
  mount(
    <TypeMetadataForm
      isNew
      roles={[]}
      values={values(over)}
      onChange={vi.fn()}
      errors={[]}
      publicRoutePrefix="p"
      contentLocales={['en']}
      collections={[]}
    />,
  );

describe('TypeMetadataForm — the key length limit is announced (#143)', () => {
  it('says so once the key reaches the limit', async () => {
    const view = await render({ key: 'a'.repeat(64) });
    expect(view.find('[data-testid="records-type-key-limit"]')).not.toBeNull();
    await view.unmount();
  });

  it('is silent below the limit', async () => {
    const view = await render({ key: 'a'.repeat(10) });
    expect(view.find('[data-testid="records-type-key-limit"]')).toBeNull();
    await view.unmount();
  });
});
