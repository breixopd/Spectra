import { Link, Navigate, Outlet } from "@tanstack/react-router";
import { useState } from "react";

import { CommandPalette, useCommandPalette } from "@/components/layout/CommandPalette";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { primaryNav } from "@/config/navigation";
import { cn } from "@/lib/utils";
import { useAuth } from "@/providers/AuthProvider";

export function AppShell() {
  const { isAuthenticated } = useAuth();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const { open, setOpen } = useCommandPalette();

  // Router beforeLoad guards protect initial navigation. This reactive boundary
  // also protects the already-rendered shell when a user signs out or expires.
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div className="relative flex min-h-screen flex-col bg-background">
      <div className="pointer-events-none absolute inset-0 bg-grid-fade opacity-60" aria-hidden />
      <TopBar onOpenCommandPalette={() => setOpen(true)} onOpenMobileNav={() => setMobileNavOpen(true)} />
      <div className="relative flex min-h-0 flex-1">
        <Sidebar collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed((value) => !value)} />
        <main className="min-w-0 flex-1">
          <div className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8">
            <Outlet />
          </div>
        </main>
      </div>
      <CommandPalette open={open} onOpenChange={setOpen} />
      <Dialog open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
        <DialogContent className="max-w-sm gap-0 overflow-hidden p-0 sm:hidden">
          <DialogHeader className="border-b border-border px-4 py-3">
            <DialogTitle>Navigation</DialogTitle>
          </DialogHeader>
          <ScrollArea className="max-h-[70vh]">
            <nav className="flex flex-col gap-1 p-2">
              {primaryNav.map((item) => {
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    to={item.href}
                    className={cn("flex items-center gap-3 rounded-md px-3 py-2.5 text-sm hover:bg-accent")}
                    onClick={() => setMobileNavOpen(false)}
                  >
                    <Icon className="h-4 w-4 text-primary" />
                    <div>
                      <p className="font-medium">{item.label}</p>
                      {item.description ? (
                        <p className="text-2xs text-muted-foreground">{item.description}</p>
                      ) : null}
                    </div>
                  </Link>
                );
              })}
            </nav>
          </ScrollArea>
          <div className="border-t border-border p-3">
            <Button variant="outline" className="w-full" onClick={() => setMobileNavOpen(false)}>
              Close
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
