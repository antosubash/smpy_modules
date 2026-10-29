import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { type FormEvent, useState } from 'react';
import { toast } from 'sonner';

import { useGeoJsonPreview } from '../../hooks/useGeoJsonPreview';
import { startGeoJsonImport, startZipImport } from '../../utils/api-imports';
import type { GeoJsonPreview } from '../../utils/geojsonPreview';
import { keys, useT } from '../../utils/i18n';
import type { ImportKind, ImportMapping } from '../../utils/types';
import { FilenamePattern, MappingFields, type MappingProp } from './MappingFields';
import { PreviewSummary } from './PreviewSummary';

const KINDS: ImportKind[] = ['geojson_base64', 'geojson_url', 'zip'];
const KIND_LABEL = {
  geojson_base64: keys.images.imports.wizard.type.geojson_base64,
  geojson_url: keys.images.imports.wizard.type.geojson_url,
  zip: keys.images.imports.wizard.type.zip,
} satisfies Record<ImportKind, string>;

const COMMON_FIELDS: MappingProp[] = [
  'lat_prop',
  'lng_prop',
  'datetime_prop',
  'external_id_prop',
  'group_key_prop',
  'group_role_prop',
];
const SOURCE_FIELD = { geojson_base64: 'image_prop', geojson_url: 'url_prop' } as const;

/** The kind a preview points to: embedded images only -> base64, an address -> URL. */
function kindFromDetection(detected: GeoJsonPreview['detected'], current: ImportKind): ImportKind {
  if (current === 'zip') return current;
  if (detected.image_prop && !detected.url_prop) return 'geojson_base64';
  if (detected.url_prop) return 'geojson_url';
  return current;
}

/** Drop the empty fields: the server's `Mapping` takes absent, not blank. */
function cleaned(mapping: ImportMapping, pattern: string, kind: ImportKind): ImportMapping {
  // Only the source property of the chosen kind: the other may be left over
  // from a suggestion made before the person switched kinds.
  const unused = kind === 'geojson_url' ? 'image_prop' : 'url_prop';
  const out: ImportMapping = {};
  for (const [name, value] of Object.entries(mapping)) {
    if (value && name !== unused) (out as Record<string, string>)[name] = value;
  }
  if (pattern.trim()) out.filename_pattern = pattern.trim();
  return out;
}

/**
 * The import wizard: pick a source, preview a local GeoJSON (its first
 * features only), review the suggested property mapping, start the import. A
 * ZIP goes up through the direct-upload parts and is then extracted.
 */
export function ImportWizard({
  collectionId,
  onStarted,
  onClose,
}: {
  collectionId: string;
  onStarted: () => void;
  onClose: () => void;
}) {
  const { t } = useT();
  const wizard = keys.images.imports.wizard;
  const geo = useGeoJsonPreview();
  const [kind, setKind] = useState<ImportKind>('geojson_base64');
  const [mapping, setMapping] = useState<ImportMapping>({});
  const [suggested, setSuggested] = useState<ReadonlySet<string>>(new Set());
  const [pattern, setPattern] = useState('');
  const [sourceUrl, setSourceUrl] = useState('');
  const [zip, setZip] = useState<File | null>(null);
  const [autoRun, setAutoRun] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isZip = kind === 'zip';
  const usesAddress = kind === 'geojson_url' && sourceUrl.trim() !== '';

  const onRead = (preview: GeoJsonPreview) => {
    if (preview.problem) return;
    // Suggestions replace the mapping, never the other way round: the person's
    // edits after this point are kept, since the file is not read again.
    const found = Object.fromEntries(
      Object.entries(preview.detected).filter(([, v]) => v !== null),
    ) as ImportMapping;
    setMapping(found);
    setSuggested(new Set(Object.keys(found)));
    setKind((current) => kindFromDetection(preview.detected, current));
  };

  const change = (field: MappingProp, value: string | undefined) => {
    setMapping((m) => ({ ...m, [field]: value }));
    setSuggested((s) => {
      const next = new Set(s);
      next.delete(field);
      return next;
    });
  };

  const sourceField = isZip ? null : SOURCE_FIELD[kind];
  const ready = isZip
    ? zip !== null
    : sourceField !== null &&
      Boolean(mapping[sourceField]) &&
      (usesAddress || (geo.file !== null && geo.preview !== null && !geo.preview.problem));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = cleaned(mapping, pattern, kind);
      if (isZip && zip) {
        await startZipImport(collectionId, zip, {
          mapping: body.filename_pattern ? { filename_pattern: body.filename_pattern } : undefined,
          autoRunPrompts: autoRun,
        });
      } else {
        await startGeoJsonImport(collectionId, {
          kind: kind as Exclude<ImportKind, 'zip'>,
          mapping: body,
          autoRunPrompts: autoRun,
          file: usesAddress ? undefined : (geo.file ?? undefined),
          sourceUrl: usesAddress ? sourceUrl.trim() : undefined,
        });
      }
      toast(t(wizard.started));
      onStarted();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const fields: MappingProp[] = sourceField ? [sourceField, ...COMMON_FIELDS] : [];

  return (
    <form
      onSubmit={submit}
      className="space-y-4 rounded-md border p-4"
      data-testid="images-import-wizard"
      aria-label={t(wizard.title)}
    >
      <div>
        <h2 className="text-base font-medium">{t(wizard.title)}</h2>
        <p className="text-sm text-muted-foreground">{t(wizard.description)}</p>
      </div>
      <div className="grid gap-1">
        <Label htmlFor="images-import-kind">{t(wizard.type.label)}</Label>
        <NativeSelect
          id="images-import-kind"
          data-testid="images-import-kind"
          value={kind}
          disabled={busy}
          onChange={(e) => setKind(e.target.value as ImportKind)}
        >
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {t(KIND_LABEL[k])}
            </option>
          ))}
        </NativeSelect>
      </div>
      {isZip ? (
        <div className="space-y-3">
          <div className="grid gap-1">
            <Label htmlFor="images-import-zip">{t(wizard.zip_file)}</Label>
            <input
              id="images-import-zip"
              data-testid="images-import-zip"
              type="file"
              accept=".zip,application/zip"
              disabled={busy}
              onChange={(e) => setZip(e.target.files?.[0] ?? null)}
            />
          </div>
          <p className="text-sm text-muted-foreground">{t(wizard.zip_hint)}</p>
          <FilenamePattern value={pattern} onChange={setPattern} />
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid gap-1">
            <Label htmlFor="images-import-file">{t(wizard.file)}</Label>
            <input
              id="images-import-file"
              data-testid="images-import-file"
              type="file"
              accept=".geojson,.json,application/geo+json,application/json"
              disabled={busy}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void geo.pick(file, onRead);
                else geo.clear();
              }}
            />
          </div>
          {kind === 'geojson_url' && (
            <div className="grid gap-1">
              <Label htmlFor="images-import-source-url">{t(wizard.source_url)}</Label>
              <Input
                id="images-import-source-url"
                data-testid="images-import-source-url"
                type="url"
                value={sourceUrl}
                maxLength={2000}
                disabled={busy}
                onChange={(e) => setSourceUrl(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">{t(wizard.source_url_hint)}</p>
            </div>
          )}
          {geo.reading && <p className="text-sm text-muted-foreground">{t(wizard.parsing)}</p>}
          {geo.preview && !usesAddress && <PreviewSummary preview={geo.preview} />}
          <div className="space-y-2">
            <h3 className="text-sm font-medium">{t(wizard.mapping)}</h3>
            <p className="text-xs text-muted-foreground">{t(wizard.mapping_hint)}</p>
            <MappingFields
              fields={fields}
              properties={geo.preview?.properties.map((p) => p.name) ?? []}
              mapping={mapping}
              suggested={suggested}
              onChange={change}
            />
            <FilenamePattern value={pattern} onChange={setPattern} />
          </div>
        </div>
      )}
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          data-testid="images-import-auto-run"
          checked={autoRun}
          disabled={busy}
          onChange={(e) => setAutoRun(e.target.checked)}
        />
        {t(wizard.auto_run)}
      </label>
      {error && (
        <p className="text-sm text-destructive" role="alert" data-testid="images-import-error">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={busy || !ready} data-testid="images-import-submit">
          {busy ? (isZip ? t(wizard.uploading) : t(wizard.submitting)) : t(wizard.submit)}
        </Button>
        <Button type="button" variant="outline" disabled={busy} onClick={onClose}>
          {t(keys.images.common.cancel)}
        </Button>
      </div>
    </form>
  );
}
