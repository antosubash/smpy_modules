import { useT } from '../../utils/i18n';
import type { ImportPlan, SectionPlanEntry } from '../../utils/snapshotsApi';
import { PlanGroup } from './PlanGroup';
import { lineItems, sectionLabel, sectionMarker, sectionNotes } from './sectionSummary';

/**
 * One contributed section of a restore (#80): its own card, below the pages.
 *
 * Everything on it comes from the section — its title, each line's label,
 * count, tone and rows — so pagebuilder renders news, or whatever registers
 * next, without knowing what it is. A reader who may not see the rows gets
 * the counts and a sentence saying why; the lines stay, because the counts
 * are what the decision turns on.
 */
export function SectionPlan({ entry }: { entry: SectionPlanEntry }) {
  const { t } = useT();
  const marker = sectionMarker(entry);
  const lines = entry.lines.filter((line) => line.count > 0);
  return (
    <section
      className="space-y-4 rounded-md border p-4"
      data-testid={`plan-section-${entry.section}`}
      aria-label={sectionLabel(entry.label_key, entry.section)}
    >
      <h3 className="font-medium">{sectionLabel(entry.label_key, entry.section)}</h3>
      {marker && (
        <p className="text-sm text-muted-foreground" data-testid="plan-section-marker">
          {marker}
        </p>
      )}
      {lines.map((line) => (
        <PlanGroup
          key={line.label_key}
          title={t(line.label_key)}
          count={line.count}
          items={lineItems(line)}
          tone={line.tone}
        />
      ))}
    </section>
  );
}

/** Every section card, then what the plan names without planning. */
export function SectionPlans({ plan }: { plan: ImportPlan }) {
  const notes = sectionNotes(plan);
  const sections = plan.sections ?? [];
  if (sections.length === 0 && notes.length === 0) return null;
  return (
    <div className="space-y-4">
      {sections.map((entry) => (
        <SectionPlan key={entry.section} entry={entry} />
      ))}
      {notes.length > 0 && (
        <ul className="space-y-1 text-sm" data-testid="plan-section-notes">
          {notes.map((note) => (
            <li
              key={note.key}
              className={note.tone === 'warning' ? 'text-amber-700' : 'text-muted-foreground'}
            >
              {note.text}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
