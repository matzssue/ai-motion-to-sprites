import type { Metadata } from "next";
import { CharactersPage } from "@/components/server/CharactersPage";

export const metadata: Metadata = { title: "Characters · Motion review" };

export default function Page() {
  return <CharactersPage />;
}
