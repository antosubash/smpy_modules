export interface FileItem {
	id: string;
	mimeType: string;
	fileSize: number;
	url: string;
}

export interface FilePickerAdapter {
	upload(file: File): Promise<FileItem>;
	list(params: {
		skip?: number;
		take?: number;
	}): Promise<{ items: FileItem[]; totalCount: number }>;
	getViewUrl(id: string): string;
}
