import { Link } from "@tanstack/react-router";
import { LogOut, Menu, Search, Settings } from "lucide-react";

import { BrandMark } from "@/components/brand/BrandMark";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useAuth } from "@/providers/AuthProvider";

interface TopBarProps {
  onOpenCommandPalette: () => void;
  onOpenMobileNav: () => void;
}

export function TopBar({ onOpenCommandPalette, onOpenMobileNav }: TopBarProps) {
  const { user, logout, isLoggingOut } = useAuth();

  return (
    <header className="sticky top-0 z-40 border-b border-border/80 bg-background/90 backdrop-blur-md">
      <div className="flex h-14 items-center gap-3 px-4">
        <Button variant="ghost" size="icon" className="md:hidden" onClick={onOpenMobileNav} aria-label="Open navigation">
          <Menu className="h-4 w-4" />
        </Button>

        <Link to="/dashboard" className="md:hidden">
          <BrandMark size="sm" showWordmark={false} />
        </Link>

        <button
          type="button"
          onClick={onOpenCommandPalette}
          className="hidden min-w-0 flex-1 items-center gap-2 rounded-md border border-border/80 bg-muted/30 px-3 py-2 text-left text-sm text-muted-foreground transition-colors hover:border-border hover:bg-muted/50 sm:flex"
        >
          <Search className="h-4 w-4 shrink-0" />
          <span className="truncate">Jump to a page…</span>
          <kbd className="ml-auto hidden rounded border border-border bg-background px-1.5 py-0.5 font-mono text-2xs text-muted-foreground lg:inline">
            ⌘K
          </kbd>
        </button>

        <div className="ml-auto flex items-center gap-2">
          {user ? (
            <>
              <div className="hidden text-right sm:block">
                <p className="text-sm font-medium leading-none">{user.username}</p>
                <p className="mt-0.5 font-mono text-2xs uppercase tracking-wider text-muted-foreground">{user.role}</p>
              </div>
              <Separator orientation="vertical" className="hidden h-6 sm:block" />
              <Button variant="ghost" size="icon" asChild className="hidden sm:inline-flex">
                <Link to="/settings">
                  <Settings className="h-4 w-4" />
                  <span className="sr-only">Settings</span>
                </Link>
              </Button>
              <Button variant="outline" size="sm" onClick={() => void logout()} disabled={isLoggingOut}>
                <LogOut className="h-4 w-4 sm:mr-2" />
                <span className="hidden sm:inline">Sign out</span>
              </Button>
            </>
          ) : null}
        </div>
      </div>
    </header>
  );
}
