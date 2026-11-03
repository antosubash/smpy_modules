import { settle } from '../../page-tests/test-dom';
import { API } from '../../utils/media-test-support';
import type { FieldDef } from '../../utils/types';
import { RecordCell } from '../RecordCell';
import { MediaApiProvider } from './MediaApiContext';

export const IMAGE: FieldDef = {
  key: 'image',
  type: 'media',
  label: 'Photo',
  required: false,
  unique: false,
  indexed: false,
  default: null,
  help: null,
  constraints: {},
  options: {},
};

export async function flush(): Promise<void> {
  for (let i = 0; i < 8; i += 1) await settle();
}

export function cell(value: unknown, withApi: boolean) {
  const inner = <RecordCell field={IMAGE} value={value} />;
  return withApi ? <MediaApiProvider value={API}>{inner}</MediaApiProvider> : inner;
}
