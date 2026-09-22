// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';

import { mount } from '../test-dom';
import { RecordListPublicUrl } from './RecordListPublicUrl';

describe('RecordListPublicUrl — U14/Missing-15: verifiable from the list, not only the type editor', () => {
  it('builds the URL from the given prefix and the type key', async () => {
    const view = await mount(
      <RecordListPublicUrl typeKey="product" publicRoutePrefix="/api/records/public" />,
    );
    const code = view.find('[data-testid="records-list-public-url"]');
    expect(code?.textContent).toBe('/api/records/public/product');
    await view.unmount();
  });

  it('falls back to the default prefix when none is given', async () => {
    const view = await mount(<RecordListPublicUrl typeKey="product" />);
    const code = view.find('[data-testid="records-list-public-url"]');
    expect(code?.textContent).toBe('/api/records/public/product');
    await view.unmount();
  });
});
