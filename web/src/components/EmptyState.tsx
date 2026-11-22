import styles from "./EmptyState.module.css";

export function EmptyState({ onOpen }: { onOpen: () => void }) {
  return (
    <main className={styles.empty}>
      <h1>Motion review</h1>
      <p>
        Drop files anywhere on this page, or <button type="button" onClick={onOpen}>open files…</button>. Nothing is
        uploaded: the files are read in this browser tab.
      </p>
      <ul>
        <li>
          <strong>the animated GLB</strong> the audit ran on (for example <code>prop_kf_s1.glb</code>);
        </li>
        <li>
          <strong>audit.json</strong> from <code>motion_audit.py</code> (a review folder&apos;s <code>data.json</code>{" "}
          works too);
        </li>
        <li>
          optionally <strong>audit_samples.json</strong> from the same folder, for the value of every metric over time.
        </li>
      </ul>
      <p className="muted">
        For local development: <code>?data=local/&lt;folder&gt;/</code> loads <code>manifest.json</code> from{" "}
        <code>public/local/&lt;folder&gt;/</code> (see web/README.md).
      </p>
    </main>
  );
}
