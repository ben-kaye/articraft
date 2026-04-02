import { lazy, Suspense, type JSX } from "react";

import { useRoute } from "@/lib/useRoute";
import { ViewerProvider } from "@/lib/viewer-context";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AppHeader } from "@/components/layout/AppHeader";
import { DashboardPage } from "@/components/dashboard/DashboardPage";

const ViewerShell = lazy(() => import("@/ViewerShell"));

function DashboardApp(): JSX.Element {
  return (
    <div className="flex h-screen flex-col bg-[var(--surface-2)]">
      <AppHeader />
      <div className="min-h-0 flex-1">
        <DashboardPage />
      </div>
    </div>
  );
}

function ViewerApp(): JSX.Element {
  return (
    <ViewerProvider>
      <div className="flex h-screen flex-col bg-[var(--surface-2)]">
        <AppHeader />
        <Suspense
          fallback={
            <div className="flex min-h-0 flex-1 items-center justify-center">
              <p className="text-[12px] text-[var(--text-quaternary)]">Loading viewer...</p>
            </div>
          }
        >
          <ViewerShell />
        </Suspense>
      </div>
    </ViewerProvider>
  );
}

export default function App(): JSX.Element {
  const route = useRoute();

  return (
    <TooltipProvider>
      {route.page === "dashboard" ? <DashboardApp /> : <ViewerApp />}
    </TooltipProvider>
  );
}
