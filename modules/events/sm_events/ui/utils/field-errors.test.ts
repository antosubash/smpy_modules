import { describe, expect, it } from 'vitest';
import { ApiError } from './api';
import { fieldErrors } from './field-errors';
import { REGISTRATION_CAPACITY_MAX } from './limits';

const refused = (...fields: string[]) => new ApiError(422, 'invalid', fields);

describe('registration field messages', () => {
  it('says what is wrong with the closing time, apart from the opening time', () => {
    const got = fieldErrors(refused('registration.closes_at_local', 'registration.opens_at_local'));
    expect(got['registration.closes_at_local']).toContain('after it opens');
    expect(got['registration.opens_at_local']).not.toContain('after it opens');
  });

  it('states the capacity maximum, taken from the constant', () => {
    const got = fieldErrors(refused('registration.capacity'));
    expect(got['registration.capacity']).toContain('1 to');
    expect(got['registration.capacity']).toContain(
      new Intl.NumberFormat('en').format(REGISTRATION_CAPACITY_MAX),
    );
  });
});
