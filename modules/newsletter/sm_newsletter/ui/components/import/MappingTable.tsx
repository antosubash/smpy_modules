/** One row per column of the export: a target field or *Not imported*, and the tags switch. */

import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { Switch } from '@simple-module-py/ui/components/ui/switch';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';

import { keys, useT } from '../../utils/i18n';
import type {
  ImportColumn,
  ImportMapping,
  ImportTag,
  ImportTargets,
} from '../../utils/importTypes';

const copy = keys.newsletter.import;
const TAGS_ID = 'newsletter-import-tags';

interface Props {
  columns: ImportColumn[];
  targets: ImportTargets;
  mapping: ImportMapping;
  tagsFound?: ImportTag[];
  onChange: (mapping: ImportMapping) => void;
}

export function MappingTable({ columns, targets, mapping, tagsFound = [], onChange }: Props) {
  const { t } = useT();
  const chosen = new Set(Object.values(mapping.fields));
  const choose = (index: number, key: string) => {
    const fields = { ...mapping.fields };
    if (key === '') delete fields[String(index)];
    else fields[String(index)] = key;
    onChange({ ...mapping, fields });
  };
  const noTags = targets.tags === 'missing';

  return (
    <div className="grid gap-4">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t(copy.column)}</TableHead>
            <TableHead>{t(copy.target)}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {columns.map((column) => {
            const own = mapping.fields[String(column.index)] ?? '';
            return (
              <TableRow key={column.index}>
                <TableCell>{column.header}</TableCell>
                <TableCell>
                  <NativeSelect
                    aria-label={column.header}
                    value={own}
                    onChange={(e) => choose(column.index, e.target.value)}
                  >
                    <option value="">{t(copy.not_imported)}</option>
                    {targets.fields.map((field) => (
                      <option
                        key={field.key}
                        value={field.key}
                        disabled={field.key !== own && chosen.has(field.key)}
                      >
                        {field.label}
                      </option>
                    ))}
                  </NativeSelect>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>

      <div className="flex items-center gap-2">
        <Switch
          id={TAGS_ID}
          checked={mapping.tags && !noTags}
          disabled={noTags}
          onCheckedChange={(tags) => onChange({ ...mapping, tags })}
        />
        <Label htmlFor={TAGS_ID}>{t(copy.tags_switch)}</Label>
      </div>
      {noTags && <p className="text-sm text-muted-foreground">{t(copy.tags_missing_hint)}</p>}

      {tagsFound.length > 0 && (
        <div className="grid gap-2">
          <p className="text-sm font-medium">{t(copy.tags_found)}</p>
          <div className="flex flex-wrap gap-2">
            {tagsFound.map((tag) => (
              <Badge key={tag.value} variant="outline">
                {tag.label} ({tag.count})
              </Badge>
            ))}
          </div>
          <p className="text-sm text-muted-foreground">{t(copy.tags_hint_segments)}</p>
        </div>
      )}
    </div>
  );
}
