import { router } from '@inertiajs/react';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@simple-module-py/ui/components/ui/dialog';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { useEffect, useRef, useState } from 'react';

import { api, errorMessage } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import { editorUrl } from './urls';

const NAME_ID = 'newsletter-new-campaign-name';
const LIST_ID = 'newsletter-new-campaign-list';

/** The server's column bound on a campaign's name. */
const MAX_NAME_LEN = 200;

/** "New campaign": a name and the list it goes to, then the editor.
 *
 *  The lists come from records through `api.lists()` and are fetched when the
 *  dialog opens. With none, there is nothing to choose, so the dialog says to
 *  create one in records first and offers no way to submit.
 */
export function NewCampaignDialog() {
  const { t } = useT();
  const copy = keys.newsletter.campaigns.new;
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [list, setList] = useState('');
  const [lists, setLists] = useState<string[] | null>(null);
  const [pending, setPending] = useState(false);
  // Synchronous: clicks in one tick all see the same `pending` state.
  const creating = useRef(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let current = true;
    setError(null);
    api
      .lists()
      .then((found) => {
        if (current) setLists(found);
      })
      .catch((e) => {
        if (!current) return;
        setLists([]);
        setError(errorMessage(e, t));
      });
    return () => {
      current = false;
    };
  }, [open, t]);

  const change = (next: boolean) => {
    if (pending) return;
    setOpen(next);
    if (!next) {
      setName('');
      setList('');
      setError(null);
    }
  };

  const canCreate = !pending && name.trim() !== '' && list !== '';

  const create = async () => {
    if (creating.current) return;
    creating.current = true;
    setPending(true);
    setError(null);
    const done = () => {
      creating.current = false;
      setPending(false);
    };
    try {
      const campaign = await api.createCampaign({ name: name.trim(), list_type_key: list });
      router.visit(editorUrl(campaign.id), { onFinish: done });
    } catch (e) {
      setError(errorMessage(e, t));
      done();
    }
  };

  return (
    <Dialog open={open} onOpenChange={change}>
      <DialogTrigger asChild>
        <Button type="button">{t(copy.trigger)}</Button>
      </DialogTrigger>
      <DialogContent>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (canCreate) void create();
          }}
        >
          <DialogHeader>
            <DialogTitle>{t(copy.title)}</DialogTitle>
            <DialogDescription>{t(copy.description)}</DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor={NAME_ID}>{t(copy.name_label)}</Label>
              <Input
                id={NAME_ID}
                value={name}
                autoFocus
                maxLength={MAX_NAME_LEN}
                disabled={pending}
                placeholder={t(copy.name_placeholder)}
                onChange={(e) => setName(e.target.value)}
              />
            </div>

            {lists === null ? (
              <p role="status" className="text-sm text-muted-foreground">
                {t(copy.loading_lists)}
              </p>
            ) : lists.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t(copy.no_lists)}</p>
            ) : (
              <div className="grid gap-2">
                <Label htmlFor={LIST_ID}>{t(copy.list_label)}</Label>
                <NativeSelect
                  id={LIST_ID}
                  value={list}
                  disabled={pending}
                  onChange={(e) => setList(e.target.value)}
                >
                  <option value="">{t(copy.list_placeholder)}</option>
                  {lists.map((key) => (
                    <option key={key} value={key}>
                      {key}
                    </option>
                  ))}
                </NativeSelect>
              </div>
            )}

            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={pending}
              onClick={() => change(false)}
            >
              {t(copy.cancel)}
            </Button>
            <Button type="submit" disabled={!canCreate}>
              {pending ? t(copy.creating) : t(copy.create)}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
