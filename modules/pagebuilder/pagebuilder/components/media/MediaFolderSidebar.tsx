/** Folder navigation and the upload-target folder input. */

import { Input } from '@simple-module-py/ui/components/ui/input';

import { keys, useT } from '../../utils/i18n';

interface FolderItemProps {
  label: string;
  active: boolean;
  onClick: () => void;
}

function FolderItem({ label, active, onClick }: FolderItemProps) {
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className={`w-full text-left px-2 py-1 rounded truncate ${
          active ? 'bg-accent font-medium text-accent-foreground' : 'hover:bg-accent/50'
        }`}
        title={label}
      >
        {label}
      </button>
    </li>
  );
}

interface Props {
  folders: string[];
  folderOptions: string[];
  activeFolder: string | null;
  onSelectFolder: (folder: string | null) => void;
  uploadFolder: string;
  onUploadFolderChange: (value: string) => void;
}

export function MediaFolderSidebar({
  folders,
  folderOptions,
  activeFolder,
  onSelectFolder,
  uploadFolder,
  onUploadFolderChange,
}: Props) {
  const { t } = useT();
  return (
    <aside className="space-y-4">
      <div>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          {t(keys.pagebuilder.folders.title)}
        </h2>
        <ul className="space-y-1 text-sm">
          <FolderItem
            label={t(keys.pagebuilder.folders.all_assets)}
            active={activeFolder === null}
            onClick={() => onSelectFolder(null)}
          />
          <FolderItem
            label={t(keys.pagebuilder.folders.unfiled)}
            active={activeFolder === ''}
            onClick={() => onSelectFolder('')}
          />
          {folders.map((name) => (
            <FolderItem
              key={name}
              label={name}
              active={activeFolder === name}
              onClick={() => onSelectFolder(name)}
            />
          ))}
        </ul>
      </div>
      <div>
        <label
          htmlFor="media-upload-folder"
          className="mb-1 block text-sm font-semibold text-muted-foreground"
        >
          {t(keys.pagebuilder.folders.upload_to)}
        </label>
        <Input
          id="media-upload-folder"
          type="text"
          value={uploadFolder}
          onChange={(e) => onUploadFolderChange(e.target.value)}
          list="pagebuilder-folder-suggestions"
          placeholder={t(keys.pagebuilder.folders.upload_placeholder)}
          className="w-full"
        />
        <datalist id="pagebuilder-folder-suggestions">
          {folderOptions.map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>
        <p className="mt-1 text-xs text-muted-foreground">
          {t(keys.pagebuilder.folders.upload_help)}
        </p>
      </div>
    </aside>
  );
}
