import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@simple-module-py/ui/components/ui/dropdown-menu';
import { ChevronDownIcon } from 'lucide-react';
import type React from 'react';
import { useRef, useState } from 'react';

import {
  type ParseFailure,
  parseTypeDefinition,
  type TypeDefinition,
  typeExportFilename,
  typeExportUrl,
} from '../../utils/type-io';
import { TypeImportDialog } from './TypeImportDialog';

/**
 * Export / import for one type's *definition* (missing-UI M3).
 *
 * `GET /types/{key}/export` and `POST /types/import` were implemented and
 * tested with no way to reach either from a browser, so moving a schema
 * between installs meant curl. Download is an ordinary link with `download`
 * on it; import picks a file, parses it here, and hands the definition to
 * the page — which routes an update through `useSchemaApply`, so a refusal
 * is the report and the "Apply anyway" the editor already has.
 */
export function TypeIoMenu({
  currentKey,
  pending,
  onImport,
}: {
  /** `null` on a type that has not been created yet — there is nothing to
   *  export, and an import would have nothing to update. */
  currentKey: string | null;
  pending: boolean;
  /** Resolves when the import has been applied (or refused and reported);
   *  the dialog stays open while it runs. */
  onImport: (definition: TypeDefinition) => Promise<unknown>;
}) {
  const { t } = useT();
  const input = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [definition, setDefinition] = useState<TypeDefinition | null>(null);
  const [failure, setFailure] = useState<ParseFailure | null>(null);
  const [applying, setApplying] = useState(false);

  const onPick = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const chosen = event.target.files?.[0] ?? null;
    // Reset immediately so picking the *same* file twice still fires change.
    event.target.value = '';
    if (!chosen) return;
    setFileName(chosen.name);
    const parsed = parseTypeDefinition(await chosen.text());
    setDefinition(parsed.ok ? parsed.definition : null);
    setFailure(parsed.ok ? null : parsed.reason);
  };

  const close = () => {
    setDefinition(null);
    setFailure(null);
    setFileName(null);
  };

  const apply = async () => {
    if (!definition) return;
    setApplying(true);
    try {
      await onImport(definition);
      close();
    } finally {
      setApplying(false);
    }
  };

  if (!currentKey) return null;

  return (
    <>
      <input
        ref={input}
        type="file"
        accept=".json,application/json"
        className="hidden"
        data-testid="records-type-import-input"
        onChange={onPick}
      />
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button type="button" variant="outline" data-testid="records-type-io-menu">
            {t('records.type_io.menu', { defaultValue: 'Definition' })}
            <ChevronDownIcon className="size-4 opacity-60" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem asChild>
            <a
              href={typeExportUrl(currentKey)}
              download={typeExportFilename(currentKey)}
              data-testid="records-type-export"
            >
              {t('records.type_io.export', { defaultValue: 'Download definition' })}
            </a>
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => input.current?.click()}>
            {t('records.type_io.import', { defaultValue: 'Import definition…' })}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <TypeImportDialog
        fileName={fileName}
        definition={definition}
        failure={failure}
        currentKey={currentKey}
        pending={pending || applying}
        onApply={() => void apply()}
        onClose={close}
      />
    </>
  );
}
