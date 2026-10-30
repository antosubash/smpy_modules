import { Button } from "@simple-module-py/ui/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
} from "@simple-module-py/ui/components/ui/dialog";
import { Input } from "@simple-module-py/ui/components/ui/input";
import { Label } from "@simple-module-py/ui/components/ui/label";
import { useEffect, useId, useRef, useState } from "react";
import { keys, useT } from "../../utils/i18n";
import { GalleryItem } from "./gallery-item";
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
const SEARCH_DEBOUNCE_MS = 250;

type ListState =
	| { status: "loading" }
	| { status: "error"; message: string }
	| { status: "ready"; items: FileItem[]; totalCount: number };

/**
 * The library as a modal dialog (#234): every file reachable through paging
 * and a filename search, each thumbnail named, focus held inside while it is
 * open and handed back to whatever opened it — Radix does both — and Escape
 * or the close button dismisses it.
 */
export function FileGallery({
	adapter,
	open,
	onClose,
	onSelect,
}: FileGalleryProps) {
	const { t } = useT();
	// Radix hands focus back to its own `DialogTrigger` on close, and the
	// pickers open this from a button of their own, so without this focus fell
	// to <body>. Recorded before Radix moves focus into the dialog.
	const opener = useRef<HTMLElement | null>(null);
	return (
		<Dialog
			open={open}
			onOpenChange={(next) => {
				if (!next) onClose();
			}}
		>
			<DialogContent
				className="flex max-h-[85dvh] flex-col sm:max-w-3xl"
				onOpenAutoFocus={() => {
					opener.current =
						document.activeElement instanceof HTMLElement
							? document.activeElement
							: null;
				}}
				onCloseAutoFocus={(event) => {
					if (opener.current?.isConnected) {
						event.preventDefault();
						opener.current.focus();
					}
				}}
			>
				<DialogHeader>
					<DialogTitle>{t(keys.pagebuilder.gallery.title)}</DialogTitle>
					<DialogDescription>
						{t(keys.pagebuilder.gallery.description)}
					</DialogDescription>
				</DialogHeader>
				<GalleryBody
					adapter={adapter}
					onPick={(item) => {
						onSelect(item.url, item);
						onClose();
					}}
				/>
			</DialogContent>
		</Dialog>
	);
}

/** The debounced search that goes to the server. */
function useDebounced(value: string): string {
	const [debounced, setDebounced] = useState(value);
	useEffect(() => {
		const timer = window.setTimeout(
			() => setDebounced(value.trim()),
			SEARCH_DEBOUNCE_MS,
		);
		return () => window.clearTimeout(timer);
	}, [value]);
	return debounced;
}

/** The dialog's contents. A component of its own because Radix unmounts it
 *  on close: every open starts on page one with an empty search, and a
 *  response still in flight is dropped rather than landing in a closed box. */
function GalleryBody({
	adapter,
	onPick,
}: {
	adapter: FilePickerAdapter;
	onPick: (item: FileItem) => void;
}) {
	const { t } = useT();
	const searchId = useId();
	const [page, setPage] = useState(0);
	const [query, setQuery] = useState("");
	const [attempt, setAttempt] = useState(0);
	const [list, setList] = useState<ListState>({ status: "loading" });
	const search = useDebounced(query);

	// biome-ignore lint/correctness/useExhaustiveDependencies: `attempt` is the Retry button
	useEffect(() => {
		// Only the latest request may land: typing "he" then "hero" must not
		// let a slow answer for "he" overwrite the one for "hero".
		let current = true;
		setList({ status: "loading" });
		adapter
			.list({ skip: page * PAGE_SIZE, take: PAGE_SIZE, search })
			.then(
				(result) => {
					if (current)
						setList({
							status: "ready",
							items: result.items,
							totalCount: result.totalCount,
						});
				},
				(error: unknown) => {
					if (current)
						setList({
							status: "error",
							message: error instanceof Error ? error.message : String(error),
						});
				},
			);
		return () => {
			current = false;
		};
	}, [adapter, page, search, attempt]);

	const totalCount = list.status === "ready" ? list.totalCount : 0;
	const hasPrev = page > 0;
	const hasMore = (page + 1) * PAGE_SIZE < totalCount;

	return (
		<>
			<div className="grid gap-1.5">
				<Label htmlFor={searchId}>
					{t(keys.pagebuilder.gallery.search_label)}
				</Label>
				<Input
					id={searchId}
					type="search"
					value={query}
					placeholder={t(keys.pagebuilder.gallery.search_placeholder)}
					onChange={(event) => {
						setQuery(event.target.value);
						setPage(0);
					}}
				/>
			</div>

			<div
				className="min-h-0 flex-1 overflow-y-auto"
				data-testid="pagebuilder-gallery-results"
			>
				{list.status === "loading" && (
					<p
						role="status"
						className="py-8 text-center text-sm text-muted-foreground"
					>
						{t(keys.pagebuilder.gallery.loading)}
					</p>
				)}
				{list.status === "error" && (
					<div
						role="alert"
						className="grid justify-items-start gap-2 py-4 text-sm"
					>
						<p className="text-destructive">
							{t(keys.pagebuilder.gallery.load_failed, {
								message: list.message,
							})}
						</p>
						<Button
							type="button"
							variant="outline"
							size="sm"
							onClick={() => setAttempt((n) => n + 1)}
						>
							{t(keys.pagebuilder.gallery.retry)}
						</Button>
					</div>
				)}
				{list.status === "ready" && list.items.length === 0 && (
					<p
						className="py-8 text-center text-sm text-muted-foreground"
						data-testid="pagebuilder-gallery-empty"
					>
						{search
							? t(keys.pagebuilder.gallery.no_matches)
							: t(keys.pagebuilder.gallery.empty)}
					</p>
				)}
				{list.status === "ready" && list.items.length > 0 && (
					<ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
						{list.items.map((item) => (
							<li key={item.id}>
								<GalleryItem item={item} onPick={onPick} />
							</li>
						))}
					</ul>
				)}
			</div>

			<div className="flex items-center justify-between gap-2 border-t pt-3">
				<span className="text-sm text-muted-foreground" aria-live="polite">
					{list.status === "ready"
						? t(keys.pagebuilder.gallery.file_count, { count: totalCount })
						: ""}
				</span>
				<nav
					className="flex gap-2"
					aria-label={t(keys.pagebuilder.gallery.pagination)}
				>
					<Button
						type="button"
						variant="outline"
						size="sm"
						onClick={() => setPage((p) => p - 1)}
						disabled={!hasPrev}
					>
						{t(keys.pagebuilder.gallery.prev)}
					</Button>
					<Button
						type="button"
						variant="outline"
						size="sm"
						onClick={() => setPage((p) => p + 1)}
						disabled={!hasMore}
					>
						{t(keys.pagebuilder.gallery.next)}
					</Button>
				</nav>
			</div>
		</>
	);
}
