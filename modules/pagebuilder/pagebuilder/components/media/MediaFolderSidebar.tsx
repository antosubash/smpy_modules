/** Folder navigation and the upload-target folder input. */

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
          active ? 'bg-blue-100 text-blue-900 font-medium' : 'hover:bg-gray-100 text-gray-700'
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
  return (
    <aside className="space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-gray-600 mb-2 uppercase tracking-wide">
          Folders
        </h2>
        <ul className="space-y-1 text-sm">
          <FolderItem
            label="All assets"
            active={activeFolder === null}
            onClick={() => onSelectFolder(null)}
          />
          <FolderItem
            label="Unfiled"
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
        <label className="block text-sm font-semibold text-gray-600 mb-1">Upload to folder</label>
        <input
          type="text"
          value={uploadFolder}
          onChange={(e) => onUploadFolderChange(e.target.value)}
          list="pagebuilder-folder-suggestions"
          placeholder="e.g. marketing/heros"
          className="w-full px-2 py-1.5 border rounded text-sm"
        />
        <datalist id="pagebuilder-folder-suggestions">
          {folderOptions.map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>
        <p className="text-xs text-gray-500 mt-1">Leave blank to upload into Unfiled.</p>
      </div>
    </aside>
  );
}
