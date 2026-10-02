import type { CustomField } from "@puckeditor/core";

import { useT } from "../utils/i18n";

/**
 * A checkbox field whose label is given as a catalogue key.
 *
 * A block config is a module-scope constant, so it cannot resolve its own
 * labels where they are written — `localizeConfig` does that on the way into
 * Puck, which is why `field.label` is already the viewer's language here. The
 * closure below is the fallback for a config that never went through it, and
 * translating both is what makes either path correct.
 */
export function createCheckboxField(label: string): CustomField<boolean> {
	return {
		type: "custom",
		label,
		// Puck calls a field's `render` as a plain function, not as a component,
		// so the hook has to sit one level down.
		render: ({ name, onChange, value, field }) => (
			<CheckboxField
				name={name}
				value={value}
				onChange={onChange}
				label={field.label || label}
			/>
		),
	};
}

function CheckboxField({
	name,
	value,
	onChange,
	label,
}: {
	name: string;
	value: boolean | undefined;
	onChange: (value: boolean) => void;
	label: string;
}) {
	const { t } = useT();
	return (
		<div className="flex items-center gap-2 py-2">
			<input
				type="checkbox"
				id={name}
				checked={Boolean(value)}
				onChange={(event) => onChange(event.target.checked)}
				className="size-4 rounded border-gray-300"
			/>
			<label htmlFor={name} className="text-sm font-medium leading-none">
				{t(label)}
			</label>
		</div>
	);
}
