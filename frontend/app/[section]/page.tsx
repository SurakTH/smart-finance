import Finance from "@/components/finance";
export function generateStaticParams() {
  return ["insights", "transactions", "accounts", "categories", "budgets", "goals", "recurring", "members", "workspaces", "services", "assistant", "inbox", "settings", "ai-settings"].map(
    (section) => ({ section }),
  );
}
export default function Page() {
  return <Finance />;
}
