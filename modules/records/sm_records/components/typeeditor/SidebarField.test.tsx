// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { click, mount } from '../../test-dom';

const { SidebarField } = await import('./SidebarField');

describe('SidebarField', () => {
  it('renders the toggle, with help naming the entry', async () => {
    const view = await mount(
      <SidebarField showInMenu={false} labelPlural="Books" onChange={vi.fn()} />,
    );
    expect(view.find('#type-editor-show-in-menu')).not.toBeNull();
    expect(view.host.textContent).toContain('Books');
    // Multi-tenant hosts get the toggle too since the per-request menu
    // provider (#92): the note that used to replace it there is gone.
    expect(view.find('[data-testid="records-show-in-menu-multi-note"]')).toBeNull();
    await view.unmount();
  });

  it('reports a flip through onChange', async () => {
    const onChange = vi.fn();
    const view = await mount(
      <SidebarField showInMenu={false} labelPlural="Books" onChange={onChange} />,
    );
    await click(view.find('#type-editor-show-in-menu'));
    expect(onChange).toHaveBeenCalledWith(true);
    await view.unmount();
  });
});
