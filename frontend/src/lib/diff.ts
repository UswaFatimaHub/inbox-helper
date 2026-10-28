export type DiffPart = { text: string; kind: "same" | "added" | "removed" };

/** Word-level difference between two texts (longest common subsequence). Whitespace stays attached to its word,
 *  so joining the parts of one side gives that text back. Drafts are short, so the O(n·m) table is fine. */
export function diffWords(before: string, after: string): DiffPart[] {
  const a = before.match(/\S+\s*|\s+/g) ?? [];
  const b = after.match(/\S+\s*|\s+/g) ?? [];
  const key = (t: string) => t.trim();
  const lcs = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--)
    for (let j = b.length - 1; j >= 0; j--)
      lcs[i][j] = key(a[i]) === key(b[j]) ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);

  const parts: DiffPart[] = [];
  const push = (text: string, kind: DiffPart["kind"]) => {
    const last = parts[parts.length - 1];
    if (last?.kind === kind) last.text += text;
    else parts.push({ text, kind });
  };
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (key(a[i]) === key(b[j])) {
      push(b[j], "same");
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) push(a[i++], "removed");
    else push(b[j++], "added");
  }
  while (i < a.length) push(a[i++], "removed");
  while (j < b.length) push(b[j++], "added");
  return parts;
}
