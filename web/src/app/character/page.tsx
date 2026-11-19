import type { Metadata } from "next";
import { Suspense } from "react";
import { CharacterPage } from "@/components/server/CharacterPage";

export const metadata: Metadata = { title: "Pipeline · Motion review" };

// useSearchParams() needs a Suspense boundary in a static export: the page is prerendered without its query
export default function Page() {
  return (
    <Suspense>
      <CharacterPage />
    </Suspense>
  );
}
