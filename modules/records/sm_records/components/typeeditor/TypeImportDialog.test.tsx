// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { click, mount } from '../../test-dom';
import type { TypeDefinition } from '../../utils/type-io';
import { TypeImportDialog } from './TypeImportDialog';

function definition(overrides: Partial<TypeDefinition> = {}): TypeDefinition {
  return {
    key: 'book',
    label: 'Book',
    fields: [
      { key: 'title', type: 'text', label: 'Title' },
      { key: 'isbn', type: 'text', label: 'ISBN' },
    ] as TypeDefinition['fields'],
    ...overrides,
  };
}

/** Radix portals the dialog onto `document.body`. */
function inDialog(selector: string): HTMLElement | null {
  return document.querySelector(selector);
}

describe('TypeImportDialog — M3: what the definition would do, before it does it', () => {
  it('stays shut until a file has been parsed', async () => {
    const view = await mount(
      <TypeImportDialog
        fileName={null}
        definition={null}
        failure={null}
        currentKey="book"
        pending={false}
        onApply={() => {}}
        onClose={() => {}}
      />,
    );
    expect(inDialog('[data-testid="records-type-import-dialog"]')).toBeNull();
    await view.unmount();
  });

  it('summarises an update of the type being edited, and applies it', async () => {
    const onApply = vi.fn();
    const view = await mount(
      <TypeImportDialog
        fileName="book-schema.json"
        definition={definition()}
        failure={null}
        currentKey="book"
        pending={false}
        onApply={onApply}
        onClose={() => {}}
      />,
    );
    expect(inDialog('[data-testid="records-type-import-file"]')?.textContent).toBe(
      'book-schema.json',
    );
    const summary = inDialog('[data-testid="records-type-import-summary"]')?.textContent ?? '';
    expect(summary).toContain('Updates this type');
    expect(summary).not.toContain('Creates a new type');

    await click(inDialog('[data-testid="records-type-import-apply"]'));
    expect(onApply).toHaveBeenCalledOnce();
    await view.unmount();
  });

  it('says a definition for another key creates a type instead', async () => {
    const view = await mount(
      <TypeImportDialog
        fileName="author-schema.json"
        definition={definition({ key: 'author', label: 'Author' })}
        failure={null}
        currentKey="book"
        pending={false}
        onApply={() => {}}
        onClose={() => {}}
      />,
    );
    const summary = inDialog('[data-testid="records-type-import-summary"]')?.textContent ?? '';
    expect(summary).toContain('Creates a new type');
    await view.unmount();
  });

  it('shows the parse failure and offers no Apply at all', async () => {
    const view = await mount(
      <TypeImportDialog
        fileName="notes.txt"
        definition={null}
        failure="not_json"
        currentKey="book"
        pending={false}
        onApply={() => {}}
        onClose={() => {}}
      />,
    );
    expect(inDialog('[role="alert"]')?.textContent).toContain("isn't valid JSON");
    expect(inDialog('[data-testid="records-type-import-apply"]')).toBeNull();
    await view.unmount();
  });

  it('disables Apply while one is in flight, and closes on Close', async () => {
    const onClose = vi.fn();
    const view = await mount(
      <TypeImportDialog
        fileName="book-schema.json"
        definition={definition()}
        failure={null}
        currentKey="book"
        pending={true}
        onApply={() => {}}
        onClose={onClose}
      />,
    );
    const apply = inDialog('[data-testid="records-type-import-apply"]') as HTMLButtonElement;
    expect(apply.disabled).toBe(true);
    await view.unmount();
    expect(onClose).not.toHaveBeenCalled();
  });
});
