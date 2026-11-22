import type { Metadata } from "next";
import { Suspense } from "react";
import { ActionReviewPage } from "@/components/server/ActionReviewPage";

export const metadata: Metadata = { title: "Action review · Motion review" };

// useSearchParams() needs a Suspense boundary in a static export: the page is prerendered without its query
export default function Page() {
  return (
    <Suspense>
      <ActionReviewPage />
    </Suspense>
  );
}
