import Link from "next/link";
import styles from "./TopNav.module.css";

type Page = "viewer" | "characters";

/** The two entry points: the file viewer (works without a server) and the server-backed characters list. */
export function TopNav({ current }: { current?: Page }) {
  return (
    <nav className={styles.nav} aria-label="Main">
      <span className={styles.brand}>ai-motion-to-sprites</span>
      <Link href="/characters/" aria-current={current === "characters" ? "page" : undefined}>
        Characters
      </Link>
      <Link href="/" aria-current={current === "viewer" ? "page" : undefined}>
        Viewer (open files)
      </Link>
    </nav>
  );
}
