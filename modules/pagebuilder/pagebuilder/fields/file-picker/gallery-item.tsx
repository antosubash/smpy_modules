/** One thumbnail in the media picker: a button named by the file. */
import type { FileItem } from "./types";

export function GalleryItem({
	item,
	onPick,
}: {
	item: FileItem;
	onPick: (item: FileItem) => void;
}) {
	// The filename names the button; an adapter without one falls back to the
	// last segment of the URL, so no thumbnail is announced as just "button".
	const name = item.name || item.url.split("/").pop() || item.id;
	return (
		<button
			type="button"
			onClick={() => onPick(item)}
			className="w-full overflow-hidden rounded-md border text-left outline-none hover:ring-2 hover:ring-ring focus-visible:ring-2 focus-visible:ring-ring"
		>
			<div className="flex aspect-square items-center justify-center overflow-hidden bg-muted">
				{item.mimeType.startsWith("image/") ? (
					<img
						src={item.url}
						alt=""
						loading="lazy"
						className="h-full w-full object-cover"
					/>
				) : (
					<span className="p-2 text-center text-xs text-muted-foreground">
						{item.mimeType}
					</span>
				)}
			</div>
			<div className="space-y-0.5 p-2 text-xs">
				<div className="truncate font-medium" title={name}>
					{name}
				</div>
				<div className="text-muted-foreground">
					{formatFileSize(item.fileSize)}
				</div>
			</div>
		</button>
	);
}

function formatFileSize(bytes: number): string {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
