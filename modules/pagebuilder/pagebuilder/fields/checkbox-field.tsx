import type { CustomField } from "@puckeditor/core";

export function createCheckboxField(label: string): CustomField<boolean> {
	return {
		type: "custom",
		label,
		render: ({ name, onChange, value, field }) => (
			<div className="flex items-center gap-2 py-2">
				<input
					type="checkbox"
					id={name}
					checked={Boolean(value)}
					onChange={(event) => onChange(event.target.checked)}
					className="size-4 rounded border-gray-300"
				/>
				<label htmlFor={name} className="text-sm font-medium leading-none">
					{field.label || label}
				</label>
			</div>
		),
	};
}
