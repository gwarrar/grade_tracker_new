/**
 * Merging admin overrides into a message catalogue.
 *
 * Split from `request.ts` because it is pure: no fetch, no Next internals, no
 * path aliases. A test of this logic should not have to resolve an API client.
 */

export type Messages = Record<string, unknown>;

/**
 * Apply flat dotted overrides onto a nested message tree.
 *
 * @param messages - The shipped translations.
 * @param overrides - Dotted key to replacement text.
 * @returns A new tree with the overrides applied.
 */
export function applyOverrides(
  messages: Messages,
  overrides: Record<string, string>,
): Messages {
  if (!Object.keys(overrides).length) return messages;

  // Deep clone: mutating the imported module would leak one organisation's
  // overrides into every later request in the same process.
  const merged = structuredClone(messages);

  for (const [path, value] of Object.entries(overrides)) {
    const parts = path.split(".");
    let node = merged as Record<string, unknown>;
    let reachable = true;

    for (const part of parts.slice(0, -1)) {
      const next = node[part];
      // Only walk into objects. An override addressing a path that is a string in
      // the shipped file would otherwise replace a whole subtree with a fragment.
      if (typeof next !== "object" || next === null || Array.isArray(next)) {
        reachable = false;
        break;
      }
      node = next as Record<string, unknown>;
    }

    const leaf = parts.at(-1);
    if (reachable && leaf) node[leaf] = value;
  }

  return merged;
}
