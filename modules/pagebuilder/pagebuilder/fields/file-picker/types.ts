export interface FileItem {
	id: string;
	mimeType: string;
	fileSize: number;
	url: string;
	/** What the picker shows and announces for the file (its original name). */
	name?: string;
}

export interface FilePickerAdapter {
	upload(file: File): Promise<FileItem>;
	list(params: {
		skip?: number;
		take?: number;
		/** Filter by file name; an adapter that cannot search ignores it. */
		search?: string;
	}): Promise<{ items: FileItem[]; totalCount: number }>;
	getViewUrl(id: string): string;
}
