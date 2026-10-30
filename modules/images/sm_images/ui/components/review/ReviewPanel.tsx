import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import type { ReviewAction, ReviewItem } from '../../utils/api-review';
import { keys, useT } from '../../utils/i18n';
import { ResultView } from '../results/ResultView';
import { CorrectionForm } from './CorrectionForm';

const STATUS = {
  unreviewed: keys.images.review.status.unreviewed,
  accepted: keys.images.review.status.accepted,
  corrected: keys.images.review.status.corrected,
  rejected: keys.images.review.status.rejected,
} satisfies Record<string, string>;

type Props = {
  item: ReviewItem;
  editing: boolean;
  busy: boolean;
  formError: string | null;
  onAction: (action: ReviewAction) => void;
  onEdit: () => void;
  onCancel: () => void;
  onCorrect: (data: Record<string, unknown>) => void;
};

/** The result under review: the thing it is about, the model's answer (the
 *  same read-only view the viewer uses), the review so far and the actions. */
export function ReviewPanel({
  item,
  editing,
  busy,
  formError,
  onAction,
  onEdit,
  onCancel,
  onCorrect,
}: Props) {
  const { t } = useT();
  const output = item.result_data ?? (item.result_text ? { text: item.result_text } : null);
  const status = STATUS[item.review_status as keyof typeof STATUS];
  return (
    <section className="space-y-4" data-testid="images-review-panel" data-result-id={item.id}>
      <header className="flex flex-wrap items-center gap-3">
        {item.thumb_url && (
          <img src={item.thumb_url} alt="" className="size-16 rounded-md object-cover" />
        )}
        <div className="min-w-0">
          <p className="font-medium">{item.filename ?? item.group_key}</p>
          <p className="text-sm text-muted-foreground">
            {item.prompt_name} ·{' '}
            {t(item.image_id ? keys.images.review.image : keys.images.review.group)}
          </p>
        </div>
        {status && (
          <Badge variant="outline" data-testid="images-review-status">
            {t(status)}
          </Badge>
        )}
        {item.stale && (
          <span className="text-sm text-muted-foreground">
            {t(keys.images.review.stale_prompt)}
          </span>
        )}
      </header>
      <div>
        <h3 className="text-sm font-medium">{t(keys.images.review.model_output)}</h3>
        <ResultView
          kind="prompt_result"
          id={item.prompt_id}
          label={item.prompt_name}
          output={output}
          run={null}
          image={null}
        />
      </div>
      {item.reviewed_data && (
        <div data-testid="images-review-reviewed">
          <h3 className="text-sm font-medium">{t(keys.images.review.reviewed_value)}</h3>
          <ResultView
            kind="prompt_result"
            id={item.prompt_id}
            label={item.prompt_name}
            output={item.reviewed_data}
            run={null}
            image={null}
          />
        </div>
      )}
      {formError && (
        <p className="text-sm text-destructive" role="alert" data-testid="images-review-error">
          {formError}
        </p>
      )}
      {editing ? (
        <CorrectionForm
          key={`${item.id}:${item.version}`}
          schema={item.output_schema}
          initial={item.reviewed_data ?? item.result_data}
          initialText={item.result_text}
          busy={busy}
          onSubmit={onCorrect}
          onCancel={onCancel}
        />
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            disabled={busy}
            onClick={() => onAction('accept')}
            data-testid="images-review-accept"
          >
            {t(keys.images.review.accept)}
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={onEdit}
            data-testid="images-review-edit"
          >
            {t(keys.images.review.edit)}
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={() => onAction('reject')}
            data-testid="images-review-reject"
          >
            {t(keys.images.review.reject)}
          </Button>
        </div>
      )}
    </section>
  );
}
