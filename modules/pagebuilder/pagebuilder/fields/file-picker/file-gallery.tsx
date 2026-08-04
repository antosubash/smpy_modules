import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import type { FileItem, FilePickerAdapter } from "./types";

interface FileGalleryProps {
	adapter: FilePickerAdapter;
	open: boolean;
	onClose: () => void;
	/**
	 * The picked file. `url` is first so URL-only consumers (Puck widgets, the
	 * branding footer logos) keep working unchanged; `item` carries the full
	 * record for callers that need the file id instead — see the ImagePicker's
	 * `valueMode="id"`.
	 */
	onSelect: (url: string, item: FileItem) => void;
}

const PAGE_SIZE = 12;

export function FileGallery({
	adapter,
	open,
	onClose,
	onSelect,
}: FileGalleryProps) {
	const [items, setItems] = useState<FileItem[]>([]);
	const [totalCount, setTotalCount] = useState(0);
	const [loading, setLoading] = useState(false);
	const [page, setPage] = useState(0);

	useEffect(() => {
		if (!open) return;
		setLoading(true);
		adapter
			.list({ skip: page * PAGE_SIZE, take: PAGE_SIZE })
			.then((result) => {
				setItems(result.items);
				setTotalCount(result.totalCount);
			})
			.catch((err) => {
				// Log instead of letting the rejection go unhandled. Keep whatever
				// items are already displayed — wiping them on a failed page fetch
				// would misread as "your uploads are gone".
				console.error("[FileGallery] Failed to list files:", err);
			})
			.finally(() => setLoading(false));
	}, [adapter, open, page]);

	useEffect(() => {
		if (!open) return;
		const handleKeyDown = (e: KeyboardEvent) => {
			if (e.key === "Escape") onClose();
		};
		document.addEventListener("keydown", handleKeyDown);
		return () => document.removeEventListener("keydown", handleKeyDown);
	}, [open, onClose]);

	if (!open) return null;

	const hasMore = (page + 1) * PAGE_SIZE < totalCount;
	const hasPrev = page > 0;

	return createPortal(
		<div
			className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50"
			onClick={(e) => {
				if (e.target === e.currentTarget) onClose();
			}}
		>
			<div className="bg-white rounded-lg shadow-xl w-full max-w-3xl max-h-[80vh] flex flex-col m-4">
				<div className="flex items-center justify-between px-4 py-3 border-b">
					<h2 className="text-lg font-semibold">Select a file</h2>
					<button
						type="button"
						onClick={onClose}
						className="text-gray-500 hover:text-gray-700 text-xl leading-none"
					>
						&times;
					</button>
				</div>
				<div className="flex-1 overflow-y-auto p-4">
					{loading ? (
						<div className="text-center py-8 text-gray-500">Loading...</div>
					) : items.length === 0 ? (
						<div className="text-center py-8 text-gray-500">
							No files uploaded yet.
						</div>
					) : (
						<div className="grid grid-cols-3 sm:grid-cols-4 gap-3">
							{items.map((item) => (
								<button
									key={item.id}
									type="button"
									onClick={() => {
										onSelect(item.url, item);
										onClose();
									}}
									className="group relative aspect-square rounded-md overflow-hidden border hover:ring-2 hover:ring-blue-500 focus:ring-2 focus:ring-blue-500 outline-none"
								>
									{item.mimeType.startsWith("image/") ? (
										<img
											src={item.url}
											alt=""
											className="w-full h-full object-cover"
										/>
									) : (
										<div className="w-full h-full flex items-center justify-center bg-gray-100 text-xs text-gray-500 p-2 text-center">
											{item.mimeType}
										</div>
									)}
									<div className="absolute inset-x-0 bottom-0 bg-black/60 text-white text-xs px-1 py-0.5 opacity-0 group-hover:opacity-100 transition-opacity truncate">
										{formatFileSize(item.fileSize)}
									</div>
								</button>
							))}
						</div>
					)}
				</div>
				<div className="flex items-center justify-between px-4 py-3 border-t">
					<span className="text-sm text-gray-500">
						{totalCount} file{totalCount !== 1 ? "s" : ""}
					</span>
					<div className="flex gap-2">
						<button
							type="button"
							onClick={() => setPage((p) => p - 1)}
							disabled={!hasPrev}
							className="px-3 py-1 text-sm rounded border disabled:opacity-40 hover:bg-gray-50"
						>
							Prev
						</button>
						<button
							type="button"
							onClick={() => setPage((p) => p + 1)}
							disabled={!hasMore}
							className="px-3 py-1 text-sm rounded border disabled:opacity-40 hover:bg-gray-50"
						>
							Next
						</button>
					</div>
				</div>
			</div>
		</div>,
		document.body,
	);
}

function formatFileSize(bytes: number): string {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
