// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { mount } from '../../test-dom';

const { SidebarField } = await import('./SidebarField');

describe('SidebarField — hidden in multi-tenant mode (tenancy design §I, item 1)', () => {
  it('renders the toggle when tenancyMode is single', async () => {
    const view = await mount(
      <SidebarField
        showInMenu={false}
        labelPlural="Books"
        tenancyMode="single"
        onChange={vi.fn()}
      />,
    );
    expect(view.find('#type-editor-show-in-menu')).not.toBeNull();
    expect(view.find('[data-testid="records-show-in-menu-multi-note"]')).toBeNull();
    await view.unmount();
  });

  it('renders the toggle when tenancyMode is absent — an older fixture', async () => {
    const view = await mount(
      <SidebarField showInMenu={false} labelPlural="Books" onChange={vi.fn()} />,
    );
    expect(view.find('#type-editor-show-in-menu')).not.toBeNull();
    await view.unmount();
  });

  it('replaces the toggle with a note once tenancyMode is multi, and never calls onChange', async () => {
    const onChange = vi.fn();
    const view = await mount(
      <SidebarField
        showInMenu={true}
        labelPlural="Books"
        tenancyMode="multi"
        onChange={onChange}
      />,
    );
    expect(view.find('#type-editor-show-in-menu')).toBeNull();
    const note = view.find('[data-testid="records-show-in-menu-multi-note"]');
    expect(note).not.toBeNull();
    expect(onChange).not.toHaveBeenCalled();
    await view.unmount();
  });
});
