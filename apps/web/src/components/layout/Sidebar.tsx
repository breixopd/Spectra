import { Link, useRouterState } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { BrandMark } from "@/components/brand/BrandMark";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { navGroups } from "@/config/navigation";
import { cn } from "@/lib/utils";

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const pathname = useRouterState({ select: (state) => state.location.pathname });

  return (
    <aside
      className={cn(
        "hidden shrink-0 border-r border-sidebar-border bg-sidebar/95 backdrop-blur md:flex md:flex-col",
        collapsed ? "w-[4.25rem]" : "w-64",
      )}
    >
      <div className={cn("flex h-14 items-center border-b border-sidebar-border/80 px-3", collapsed && "justify-center")}>
        {collapsed ? (
          <BrandMark size="sm" showWordmark={false} />
        ) : (
          <div className="flex min-w-0 flex-1 items-center justify-between gap-2">
            <BrandMark size="sm" subtitle="Ops console" />
            <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0" onClick={onToggle} aria-label="Collapse sidebar">
              <ChevronLeft className="h-4 w-4" />
            </Button>
          </div>
        )}
      </div>

      {collapsed ? (
        <div className="flex justify-center py-2">
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onToggle} aria-label="Expand sidebar">
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      ) : null}

      <ScrollArea className="flex-1">
        <nav className="space-y-4 p-2">
          {navGroups.map((group) => (
            <div key={group.label}>
              {!collapsed ? (
                <p className="mb-1 px-3 text-2xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
                  {group.label}
                </p>
              ) : (
                <Separator className="my-2" />
              )}
              <div className="flex flex-col gap-0.5">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const active = pathname === item.href || (item.href !== "/dashboard" && pathname.startsWith(item.href));
                  return (
                    <Link
                      key={item.href}
                      to={item.href}
                      className={cn(
                        "group flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                        active
                          ? "bg-primary/12 text-foreground ring-1 ring-primary/20"
                          : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-foreground",
                        collapsed && "justify-center px-2",
                      )}
                      title={collapsed ? item.label : undefined}
                    >
                      <Icon className={cn("h-4 w-4 shrink-0", active && "text-primary")} />
                      {!collapsed ? <span className="truncate">{item.label}</span> : null}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
      </ScrollArea>
    </aside>
  );
}
