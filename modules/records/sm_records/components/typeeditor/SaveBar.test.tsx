import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import '../../test-dom';
import { SaveBar } from './SaveBar';

function html(overrides: Partial<Parameters<typeof SaveBar>[0]> = {}): string {
  return renderToStaticMarkup(
    <SaveBar
      errors={[]}
      fieldKeys={[]}
      pending={false}
      dirty={false}
      onSave={() => {}}
      {...overrides}
    />,
  );
}

describe('SaveBar — U29: "No changes to save" belongs on the edit screen only', () => {
  it('shows the message on a clean existing type', () => {
    expect(html({ isNew: false })).toContain('No changes to save');
  });

  it('says nothing on a brand-new type, which has nothing yet to have changed', () => {
    expect(html({ isNew: true })).not.toContain('No changes to save');
  });

  it('defaults to the edit-screen behaviour when isNew is not passed', () => {
    expect(html()).toContain('No changes to save');
  });

  it('says nothing on either screen while a save is pending or the draft is dirty', () => {
    expect(html({ isNew: false, pending: true })).not.toContain('No changes to save');
    expect(html({ isNew: false, dirty: true })).not.toContain('No changes to save');
  });
});
