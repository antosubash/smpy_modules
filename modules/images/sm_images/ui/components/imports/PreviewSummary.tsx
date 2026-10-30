import type { GeoJsonPreview, PreviewProblem } from '../../utils/geojsonPreview';
import { keys, type Translate, useT } from '../../utils/i18n';

const PROBLEM = {
  not_object: keys.images.imports.wizard.problem.not_object,
  no_features: keys.images.imports.wizard.problem.no_features,
  not_feature_collection: keys.images.imports.wizard.problem.not_feature_collection,
  no_complete_feature: keys.images.imports.wizard.problem.no_complete_feature,
  empty: keys.images.imports.wizard.problem.empty,
  invalid_json: keys.images.imports.wizard.problem.invalid_json,
} satisfies Record<PreviewProblem['code'], string>;

export function problemText(t: Translate, problem: PreviewProblem): string {
  const params =
    problem.code === 'not_feature_collection'
      ? { found: problem.found }
      : problem.code === 'invalid_json'
        ? { detail: problem.detail }
        : undefined;
  return t(PROBLEM[problem.code], params);
}

/** What the start of the file holds: the count, the geometry and the properties. */
export function PreviewSummary({ preview }: { preview: GeoJsonPreview }) {
  const { t } = useT();
  const wizard = keys.images.imports.wizard;
  if (preview.problem) {
    return (
      <p className="text-sm text-destructive" role="alert" data-testid="images-import-problem">
        {problemText(t, preview.problem)}
      </p>
    );
  }
  return (
    <div className="space-y-2 text-sm" data-testid="images-import-preview">
      <p className="font-medium">
        {t(preview.isPartial ? wizard.count_partial : wizard.count_exact, {
          count: preview.featureCount,
        })}
      </p>
      {preview.geometryTypes.length > 0 && (
        <p className="text-muted-foreground">
          {t(wizard.geometry, { types: preview.geometryTypes.join(', ') })}
        </p>
      )}
      {preview.properties.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="text-muted-foreground">
                <th className="pr-3 font-medium">{t(wizard.properties)}</th>
                <th className="font-medium">{t(wizard.sample)}</th>
              </tr>
            </thead>
            <tbody>
              {preview.properties.map((p) => (
                <tr key={p.name}>
                  <td className="pr-3 font-mono">{p.name}</td>
                  <td className="max-w-xs truncate">{p.sampleValue}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
