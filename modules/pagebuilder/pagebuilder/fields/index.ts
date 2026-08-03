// Only the checkbox field is ported. The GCA widgets take image paths as plain
// text props, so the file-picker field (which needs a host-supplied adapter)
// isn't required. Wiring the module's own MediaPicker in here is future work.
export { createCheckboxField } from './checkbox-field';
