import { describe, expect, it } from 'vitest';

import { buildJsonSchema, emptyField, fieldNameError, schemaToFields } from './schemaFields';

describe('schemaFields', () => {
  it('round-trips what the field editor can express', () => {
    const schema = {
      type: 'object',
      properties: {
        label: { type: 'string', enum: ['tree', 'road'], description: 'What it shows' },
        count: { type: 'integer' },
        score: { type: 'number' },
        sure: { type: 'boolean' },
        tags: { type: 'array', items: { type: 'string', enum: ['a', 'b'] } },
        notes: { type: 'array', items: { type: 'string' } },
      },
      required: ['label', 'count'],
    };
    const fields = schemaToFields(schema);
    expect(fields?.map((f) => f.type)).toEqual([
      'string',
      'integer',
      'number',
      'boolean',
      'string_list',
      'string_list',
    ]);
    expect(fields?.[0]).toMatchObject({ choices: ['tree', 'road'], required: true });
    expect(buildJsonSchema(fields ?? [])).toEqual(schema);
  });

  it('refuses a schema the fields would weaken (the portal bug)', () => {
    for (const schema of [
      { type: 'object', properties: { n: { type: 'integer', minimum: 0 } } },
      { type: 'object', properties: { o: { type: 'object', properties: {} } } },
      { type: 'object', properties: { s: { type: 'string' } }, additionalProperties: false },
      { type: 'object', $defs: {}, properties: {} },
      { type: 'object', properties: { n: { type: 'integer', enum: [1, 2] } } },
      { type: 'array' },
      null,
    ]) {
      expect(schemaToFields(schema as never)).toBeNull();
    }
  });

  it('builds properties with no prototype and refuses prototype key names', () => {
    const built = buildJsonSchema([{ ...emptyField(), name: 'toString' }]);
    expect(Object.getPrototypeOf(built.properties)).toBeNull();
    for (const name of ['__proto__', 'constructor', 'prototype', ' __proto__ ']) {
      expect(fieldNameError(name)).not.toBeNull();
    }
    expect(fieldNameError('kind')).toBeNull();
    const own = JSON.parse('{"type":"object","properties":{"__proto__":{"type":"string"}}}');
    expect(schemaToFields(own)).toBeNull();
  });

  it('leaves out an unnamed field and adds required only when set', () => {
    const named = { ...emptyField(), name: ' kind ', choices: ['x'] };
    expect(buildJsonSchema([named, emptyField()])).toEqual({
      type: 'object',
      properties: { kind: { type: 'string', enum: ['x'] } },
    });
  });
});
