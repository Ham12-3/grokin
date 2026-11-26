/** Compares versions like "0.1.10" and "0.2.0". Extra labels ("-beta") are ignored. */
export function isOlder(version: string, minimum: string): boolean {
  const parts = (text: string) =>
    text
      .split("-")[0]
      .split(".")
      .map((part) => Number.parseInt(part, 10) || 0);
  const [current, wanted] = [parts(version), parts(minimum)];
  for (let index = 0; index < Math.max(current.length, wanted.length); index += 1) {
    const difference = (current[index] ?? 0) - (wanted[index] ?? 0);
    if (difference !== 0) return difference < 0;
  }
  return false;
}
