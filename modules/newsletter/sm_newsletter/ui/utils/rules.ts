/** What a segment rule's value is, per field type and operator (mirrors `segments/rules.py`). */

import { HttpError, isCode } from './http';
import type { ListField, Rule, RuleOp } from './types';

type ValueInput = 'choices' | 'choice' | 'text' | 'number' | 'date' | 'boolean';

const LIST_OPS: readonly RuleOp[] = ['any', 'all', 'none'];

export function valueInput(field: ListField, op: RuleOp): ValueInput {
  if (LIST_OPS.includes(op)) return 'choices';
  switch (field.type) {
    case 'number':
    case 'integer':
      return 'number';
    case 'date':
    case 'datetime':
      return 'date';
    case 'boolean':
      return 'boolean';
    default:
      return field.choices.length > 0 ? 'choice' : 'text';
  }
}

export function emptyRule(field: ListField): Rule {
  const op = field.ops[0] ?? 'is';
  return { field: field.key, op, value: valueInput(field, op) === 'choices' ? [] : '' };
}

export function ruleComplete(rule: Rule): boolean {
  if (!rule.field) return false;
  return Array.isArray(rule.value) ? rule.value.length > 0 : rule.value.trim() !== '';
}

/** The rule a 422 `rules[i]: …` detail names, if any. */
export function invalidRuleIndex(e: unknown): number | null {
  if (!isCode(e, 'invalid_segment') || !(e instanceof HttpError)) return null;
  const match = /^rules\[(\d+)\]/.exec(e.message);
  return match ? Number(match[1]) : null;
}
