import type { StageState } from "@/api/types";
import { STAGE_LABEL, STAGE_STATUS } from "@/pipeline/labels";
import { StatusText } from "./ServerState";
import styles from "./server.module.css";

/** The seven stages of character.py in order, each with its status in words and the reason. */
export function StageStepper({ stages }: { stages: StageState[] }) {
  return (
    <ol className={styles.stepper} aria-label="Pipeline stages">
      {stages.map((s, i) => {
        const st = STAGE_STATUS[s.status];
        return (
          <li key={s.name} className={`${styles.step} ${styles[st.tone]}`} aria-current={s.status === "waiting" ? "step" : undefined}>
            <span className={styles.stepNo}>
              {i + 1}. <code>{s.name}</code>
            </span>
            <strong>{STAGE_LABEL[s.name]}</strong>
            <StatusText {...st} />
            <span className={styles.detail}>{s.detail}</span>
          </li>
        );
      })}
    </ol>
  );
}
