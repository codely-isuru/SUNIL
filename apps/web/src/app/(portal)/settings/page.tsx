/**
 * `/settings` — PORTAL_SHELL_SPEC.md §9. Marked `MINIMAL` in the navigation, and it is.
 */
import type { JSX } from "react";
import type { Metadata } from "next";
import { SettingsView } from "../../../components/SettingsView";

export const metadata: Metadata = { title: "Settings" };

export default function SettingsPage(): JSX.Element {
  return <SettingsView />;
}
