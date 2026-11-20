/** Sample index from its name (`body_s2`, `kf_s0`): what `character.py --sample <action>=N` takes; null for other names. */
export function sampleIndex(name: string): number | null {
  const m = /_s(\d+)$/.exec(name);
  return m ? Number(m[1]) : null;
}
