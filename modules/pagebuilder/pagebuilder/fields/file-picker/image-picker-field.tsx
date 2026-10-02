import type { CustomField } from "@puckeditor/core";
import { useCallback, useEffect, useRef, useState } from "react";
import { keys, useT } from "../../utils/i18n";
import { cn } from "../../utils/widgetUtils";
import { FileGallery } from "./file-gallery";
import type { FilePickerAdapter } from "./types";

/**
 * An image field backed by a media library.
 *
 * Generic over the prop type because widgets declare image props both as
 * `string` and as `string | undefined` (an optional icon, say), and Puck's
 * `CustomField` is invariant in its value — a single concrete type would fail
 * to assign at one call site or the other.
 */
export function createImageField<T extends string | undefined = string>(
	adapter: FilePickerAdapter,
	label: string = keys.pagebuilder.fields.image,
): CustomField<T> {
	return {
		type: "custom",
		label,
		render: ({ value, onChange }) => (
			<ImagePickerFieldRenderer
				value={value ?? ""}
				onChange={(next) => onChange(next as T)}
				adapter={adapter}
			/>
		),
	} as CustomField<T>;
}

interface ImagePickerFieldRendererProps {
	value: string;
	onChange: (value: string) => void;
	adapter: FilePickerAdapter;
	/**
	 * What `value`/`onChange` carry.
	 *
	 * `"url"` (default) — a ready-to-render view URL, which is what Puck stores
	 * verbatim in page content. `"id"` — the bare file id, for records that hold
	 * a FK to the file (e.g. News.ImageId) and build the URL at render time.
	 * Defaulting to `"url"` keeps every existing Puck widget untouched.
	 */
	valueMode?: "url" | "id";
	/** Marks the hidden file input + drop zone, so hosts can target them in tests. */
	testId?: string;
	disabled?: boolean;
}

export function ImagePickerFieldRenderer({
	value,
	onChange,
	adapter,
	valueMode = "url",
	testId,
	disabled = false,
}: ImagePickerFieldRendererProps) {
	const { t } = useT();
	const [galleryOpen, setGalleryOpen] = useState(false);
	const [uploading, setUploading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [isDragOver, setIsDragOver] = useState(false);

	// Any external or internal value change resolves a previous failure.
	// biome-ignore lint/correctness/useExhaustiveDependencies(value): the effect intentionally keys on value changes without reading it
	useEffect(() => {
		setError(null);
	}, [value]);
	const fileInputRef = useRef<HTMLInputElement>(null);

	const uploadFile = useCallback(
		async (file: File) => {
			setError(null);
			setUploading(true);
			try {
				const result = await adapter.upload(file);
				onChange(valueMode === "id" ? result.id : result.url);
			} catch (err) {
				console.error("[ImagePicker] Upload failed:", err);
				setError(t(keys.pagebuilder.picker.upload_failed));
			} finally {
				setUploading(false);
				if (fileInputRef.current) fileInputRef.current.value = "";
			}
		},
		[adapter, onChange, valueMode],
	);

	// In "id" mode `value` is a bare file id, so the preview has to resolve it
	// through the adapter; in "url" mode it is already renderable.
	const previewSrc = value
		? valueMode === "id"
			? adapter.getViewUrl(value)
			: value
		: null;

	const handleUpload = useCallback(
		(e: React.ChangeEvent<HTMLInputElement>) => {
			const file = e.target.files?.[0];
			if (!file) return;
			void uploadFile(file);
		},
		[uploadFile],
	);

	const handleDrop = useCallback(
		(e: React.DragEvent<HTMLDivElement>) => {
			e.preventDefault();
			setIsDragOver(false);
			if (uploading) return;
			const file = e.dataTransfer.files?.[0];
			if (!file) return;
			if (!file.type.startsWith("image/")) {
				setError(t(keys.pagebuilder.picker.not_an_image));
				return;
			}
			void uploadFile(file);
		},
		[uploading, uploadFile],
	);

	const handleDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
		e.preventDefault();
		setIsDragOver(true);
	}, []);

	const handleDragLeave = useCallback(() => {
		setIsDragOver(false);
	}, []);

	return (
		<div className="space-y-2">
			<div
				data-testid={testId ? `${testId}-drop-zone` : "image-drop-zone"}
				onDrop={handleDrop}
				onDragOver={handleDragOver}
				onDragLeave={handleDragLeave}
				className={cn(
					"w-full aspect-video rounded-md overflow-hidden",
					isDragOver
						? "border-2 border-blue-400 bg-blue-50"
						: value
							? "border bg-gray-50"
							: "border-2 border-dashed border-gray-300",
				)}
			>
				{previewSrc ? (
					<img
						src={previewSrc}
						alt=""
						className="w-full h-full object-contain"
					/>
				) : (
					<div className="w-full h-full flex items-center justify-center text-sm text-gray-400">
						{t(keys.pagebuilder.picker.empty)}
					</div>
				)}
			</div>
			<div className="flex gap-2">
				<button
					type="button"
					onClick={() => fileInputRef.current?.click()}
					disabled={uploading || disabled}
					className="flex-1 px-3 py-1.5 text-sm rounded border bg-white hover:bg-gray-50 disabled:opacity-50"
				>
					{uploading
						? t(keys.pagebuilder.picker.uploading)
						: t(keys.pagebuilder.picker.upload)}
				</button>
				<button
					type="button"
					onClick={() => setGalleryOpen(true)}
					disabled={disabled}
					className="flex-1 px-3 py-1.5 text-sm rounded border bg-white hover:bg-gray-50 disabled:opacity-50"
				>
					{t(keys.pagebuilder.picker.browse)}
				</button>
				{value && (
					<button
						type="button"
						onClick={() => {
							setError(null);
							onChange("");
						}}
						disabled={disabled}
						className="px-3 py-1.5 text-sm rounded border bg-white hover:bg-gray-50 text-red-600 disabled:opacity-50"
					>
						{t(keys.pagebuilder.picker.clear)}
					</button>
				)}
			</div>
			{error && (
				<div role="alert" className="text-sm text-red-600">
					{error}
				</div>
			)}
			<input
				ref={fileInputRef}
				type="file"
				accept="image/*"
				onChange={handleUpload}
				disabled={disabled}
				data-testid={testId}
				className="hidden"
			/>
			<FileGallery
				adapter={adapter}
				open={galleryOpen}
				onClose={() => setGalleryOpen(false)}
				onSelect={(url, item) => {
					setError(null);
					onChange(valueMode === "id" ? item.id : url);
				}}
			/>
		</div>
	);
}
