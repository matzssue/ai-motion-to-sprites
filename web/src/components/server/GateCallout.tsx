import Link from "next/link";
import { urls } from "@/api/client";
import type { Gate, VerdictResult } from "@/api/types";
import styles from "./server.module.css";
import { VerdictPanel } from "./VerdictPanel";

/** The gate the pipeline waits at: what to look at, what to decide, and the verdict controls (the motion verdict
 *  is given on the review page, next to the motion). */
export function GateCallout({
  characterId,
  gate,
  configSha,
  onWritten,
}: {
  characterId: string;
  gate: Gate;
  configSha: string;
  onWritten: (result: VerdictResult) => void;
}) {
  const images = gate.images ?? [];
  return (
    <section className={styles.gate} aria-labelledby="gate-title">
      <h2 id="gate-title">
        <span aria-hidden="true">⏸ </span>Waiting for review: {gate.title}
      </h2>
      <p>{gate.needs}</p>
      {images.length > 0 && (
        <div className={styles.images}>
          {images.map((img) => (
            <figure key={img.id}>
              <a href={urls.image(img.id) ?? undefined} target="_blank" rel="noreferrer">
                {/* eslint-disable-next-line @next/next/no-img-element -- served by the local service, not optimizable */}
                <img src={urls.image(img.id) ?? undefined} alt={`Preview ${img.label}`} loading="lazy" />
              </a>
              <figcaption>{img.label}</figcaption>
            </figure>
          ))}
        </div>
      )}
      {gate.kind === "motion" && gate.action ? (
        <p>
          <Link href={{ pathname: "/review/", query: { character: characterId, action: gate.action, source: "choice" } }}>
            Watch “{gate.action}” with its audit and give the verdict →
          </Link>
        </p>
      ) : (
        <VerdictPanel key={gate.kind + (gate.action ?? "")} characterId={characterId} gate={gate} configSha={configSha} onWritten={onWritten} />
      )}
    </section>
  );
}
