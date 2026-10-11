import Finance from "@/components/finance";
export function generateStaticParams() {
  return ["transactions", "accounts", "categories", "budgets", "goals", "recurring", "members", "workspaces", "services", "assistant", "inbox", "settings"].map(
    (section) => ({ section }),
  );
}
export default function Page() {
  return <Finance />;
}
