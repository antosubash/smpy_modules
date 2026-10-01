import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Plus, X } from 'lucide-react';

interface Row {
  key: string;
  value: string;
}

interface Props {
  rows: Row[];
  knownKeys: string[];
  onChange: (rows: Row[]) => void;
}

/** Key/number rows for a plan's limits. An absent key is unlimited; 0 forbids. */
export function LimitRows({ rows, knownKeys, onChange }: Props) {
  const update = (index: number, patch: Partial<Row>) =>
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  const missing = knownKeys.filter((key) => !rows.some((row) => row.key === key));

  return (
    <div className="space-y-2">
      {rows.map((row, index) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: rows have no identity until saved
        <div key={index} className="flex items-center gap-2">
          <Input
            aria-label="Limit key"
            placeholder="tenants.seats"
            value={row.key}
            onChange={(e) => update(index, { key: e.target.value })}
            list="billing-known-limit-keys"
          />
          <Input
            aria-label={`Limit for ${row.key || 'new key'}`}
            className="w-28"
            inputMode="numeric"
            value={row.value}
            onChange={(e) => update(index, { value: e.target.value })}
          />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={`Remove ${row.key || 'row'}`}
            onClick={() => onChange(rows.filter((_, i) => i !== index))}
          >
            <X aria-hidden="true" />
          </Button>
        </div>
      ))}
      <datalist id="billing-known-limit-keys">
        {knownKeys.map((key) => (
          <option key={key} value={key} />
        ))}
      </datalist>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => onChange([...rows, { key: '', value: '' }])}
        >
          <Plus aria-hidden="true" /> Add limit
        </Button>
        {missing.map((key) => (
          <Button
            key={key}
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => onChange([...rows, { key, value: '' }])}
          >
            <Plus aria-hidden="true" /> {key}
          </Button>
        ))}
      </div>
    </div>
  );
}
