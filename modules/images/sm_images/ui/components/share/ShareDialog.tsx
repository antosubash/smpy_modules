import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@simple-module-py/ui/components/ui/dialog';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { useState } from 'react';
import { toast } from 'sonner';

import { useShares } from '../../hooks/useShares';
import { errorText } from '../../utils/api-net';
import { keys, useT } from '../../utils/i18n';
import type { Share, ShareCandidate, ShareRole } from '../../utils/types';

function roleLabel(t: ReturnType<typeof useT>['t'], role: string): string {
  return role === 'edit' ? t(keys.images.share.role_edit) : t(keys.images.share.role_view);
}

/** Share a collection: who has access now, a picker for who could, and a role
 *  (view or edit). The owner (or `images.manage`) opens it; the server enforces
 *  that again on every call. */
export function ShareDialog({ collectionId }: { collectionId: string }) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [role, setRole] = useState<ShareRole>('view');
  const state = useShares(collectionId, open);

  const report = (e: unknown) => toast.error(errorText(e));

  const grant = async (candidate: ShareCandidate) => {
    try {
      await state.grant(candidate, role);
      toast(t(keys.images.share.granted, { name: candidate.display_name }));
    } catch (e) {
      report(e);
    }
  };

  const revoke = async (share: Share) => {
    try {
      await state.revoke(share);
      toast(t(keys.images.share.revoked));
    } catch (e) {
      report(e);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button type="button" variant="outline" data-testid="images-share">
          {t(keys.images.share.button)}
        </Button>
      </DialogTrigger>
      <DialogContent data-testid="images-share-dialog">
        <DialogHeader>
          <DialogTitle>{t(keys.images.share.title)}</DialogTitle>
          <DialogDescription>{t(keys.images.share.description)}</DialogDescription>
        </DialogHeader>

        <section className="space-y-2" aria-label={t(keys.images.share.current)}>
          <h3 className="text-sm font-medium">{t(keys.images.share.current)}</h3>
          {state.shares.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {state.loading ? t(keys.images.common.loading) : t(keys.images.share.none)}
            </p>
          ) : (
            <ul className="divide-y rounded-md border">
              {state.shares.map((share) => {
                const name = share.subject_label ?? share.subject_id;
                return (
                  <li
                    key={share.id}
                    className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
                    data-testid="images-share-row"
                  >
                    <span className="min-w-0 break-words">
                      {name} · {roleLabel(t, share.role)}
                      {share.expired ? ` · ${t(keys.images.share.expired)}` : ''}
                    </span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-label={t(keys.images.share.revoke_for, { name })}
                      onClick={() => void revoke(share)}
                    >
                      {t(keys.images.share.revoke)}
                    </Button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section className="space-y-2">
          <div className="grid gap-2">
            <Label htmlFor="images-share-search">{t(keys.images.share.search_label)}</Label>
            <Input
              id="images-share-search"
              type="search"
              value={state.query}
              placeholder={t(keys.images.share.search_placeholder)}
              onChange={(e) => state.setQuery(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="images-share-role">{t(keys.images.share.role)}</Label>
            <NativeSelect
              id="images-share-role"
              value={role}
              onChange={(e) => setRole(e.target.value as ShareRole)}
            >
              <option value="view">{t(keys.images.share.role_view)}</option>
              <option value="edit">{t(keys.images.share.role_edit)}</option>
            </NativeSelect>
          </div>
          {state.candidates.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t(keys.images.share.no_candidates)}</p>
          ) : (
            <ul className="max-h-48 divide-y overflow-auto rounded-md border">
              {state.candidates.map((candidate) => (
                <li
                  key={candidate.id}
                  className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
                  data-testid="images-share-candidate"
                >
                  <span className="min-w-0 break-words">
                    {candidate.display_name}
                    <span className="block text-xs text-muted-foreground">{candidate.email}</span>
                  </span>
                  <Button type="button" size="sm" onClick={() => void grant(candidate)}>
                    {t(keys.images.share.grant)}
                  </Button>
                </li>
              ))}
            </ul>
          )}
          {state.error && (
            <p className="text-sm text-destructive" role="alert">
              {state.error}
            </p>
          )}
        </section>
      </DialogContent>
    </Dialog>
  );
}
