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
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { type FormEvent, useState } from 'react';

import { createCollection } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import type { Visibility } from '../../utils/types';
import { VisibilitySelect } from './VisibilitySelect';

/** "New collection": creates through the API, then opens the new collection. */
export function CreateCollectionDialog({ canPublish }: { canPublish: boolean }) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [visibility, setVisibility] = useState<Visibility>('private');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const made = await createCollection({
        name: name.trim(),
        description: description.trim() || undefined,
        visibility,
      });
      setOpen(false);
      router.visit(`/admin/images/${made.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : t(keys.images.create.failed));
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && setOpen(next)}>
      <DialogTrigger asChild>
        <Button type="button" data-testid="images-new-collection">
          {t(keys.images.collections.new)}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{t(keys.images.create.title)}</DialogTitle>
            <DialogDescription>{t(keys.images.create.description)}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor="images-create-name">{t(keys.images.create.name)}</Label>
            <Input
              id="images-create-name"
              value={name}
              required
              maxLength={200}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="images-create-details">{t(keys.images.create.details)}</Label>
            <Textarea
              id="images-create-details"
              value={description}
              maxLength={2000}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="images-create-visibility">{t(keys.images.create.visibility)}</Label>
            <VisibilitySelect
              id="images-create-visibility"
              value={visibility}
              canPublish={canPublish}
              onChange={setVisibility}
            />
          </div>
          {error && (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={pending}
              onClick={() => setOpen(false)}
            >
              {t(keys.images.common.cancel)}
            </Button>
            <Button type="submit" disabled={pending || !name.trim()}>
              {pending ? t(keys.images.common.saving) : t(keys.images.create.submit)}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
