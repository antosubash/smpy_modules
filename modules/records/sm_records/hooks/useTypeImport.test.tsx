// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { act, mount } from '../test-dom';
import type { TypeRead } from '../utils/types';

const posted: Record<string, unknown>[] = [];
vi.mock('../utils/type-io', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../utils/type-io')>();
  return {
    ...actual,
    importTypeDefinition: (body: Record<string, unknown>) => {
      posted.push(body);
      return Promise.resolve({ key: body.key, version: 1 } as unknown as TypeRead);
    },
  };
});

const { useTypeImport } = await import('./useTypeImport');

const CURRENT = { key: 'book', version: 4 } as unknown as TypeRead;
const DEFINITION = { key: 'book', label: 'Book', fields: [] };

type Hook = ReturnType<typeof useTypeImport>;

describe('useTypeImport — M3: update through the schema pipeline, create beside it', () => {
  it('sends an update for this type through useSchemaApply, with its version', async () => {
    posted.length = 0;
    const calls: { body: Record<string, unknown> }[] = [];
    const reset = vi.fn();
    let hook: Hook | null = null;
    const run = async (
      attempt: (body: never) => Promise<TypeRead>,
      body: Record<string, unknown>,
    ) => {
      calls.push({ body });
      // `useSchemaApply` merges force/orphaned onto the body it was given.
      return attempt(body as never);
    };
    function Probe() {
      hook = useTypeImport({
        current: CURRENT,
        run: run as never,
        reset,
        onCreated: () => {
          throw new Error('should not create');
        },
      });
      return null;
    }
    const view = await mount(<Probe />);
    await act(async () => {
      await (hook as unknown as Hook).importDefinition(DEFINITION);
    });
    expect(reset).toHaveBeenCalledOnce();
    expect(calls[0].body).toEqual({ expected_version: 4 });
    expect(posted[0]).toMatchObject({ key: 'book', mode: 'update', expected_version: 4 });
    await view.unmount();
  });

  it('creates when the definition names another type, and hands it back', async () => {
    posted.length = 0;
    const created: TypeRead[] = [];
    let hook: Hook | null = null;
    function Probe() {
      hook = useTypeImport({
        current: CURRENT,
        run: (() => {
          throw new Error('should not update');
        }) as never,
        reset: vi.fn(),
        onCreated: (type) => created.push(type),
      });
      return null;
    }
    const view = await mount(<Probe />);
    await act(async () => {
      await (hook as unknown as Hook).importDefinition({ ...DEFINITION, key: 'author' });
    });
    expect(posted[0]).toMatchObject({ key: 'author', mode: 'create' });
    expect(posted[0]).not.toHaveProperty('expected_version');
    expect(created[0].key).toBe('author');
    await view.unmount();
  });
});
