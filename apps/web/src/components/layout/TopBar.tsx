import { Link } from "@tanstack/react-router";
import { LogOut, Menu, Search, Shield } from "lucide-react";

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
    <header className="sticky top-0 z-40 flex h-14 items-center gap-3 border-b border-border bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/80">
      <Button variant="ghost" size="icon" className="md:hidden" onClick={onOpenMobileNav} aria-label="Open navigation">
        <Menu className="h-4 w-4" />
      </Button>
      <Link to="/dashboard" className="flex items-center gap-2 font-semibold tracking-tight">
        <span className="flex h-8 w-8 items-center justify-center rounded-md bg-primary/15 text-primary">
          <Shield className="h-4 w-4" />
        </span>
        <span className="hidden sm:inline">Spectra</span>
      </Link>
      <Separator orientation="vertical" className="hidden h-6 sm:block" />
      <button
        type="button"
        onClick={onOpenCommandPalette}
        className="hidden min-w-0 flex-1 items-center gap-2 rounded-md border border-input bg-muted/40 px-3 py-1.5 text-left text-sm text-muted-foreground transition-colors hover:bg-muted sm:flex"
      >
        <Search className="h-4 w-4 shrink-0" />
        <span className="truncate">Search missions, findings, evidence...</span>
        <kbd className="ml-auto hidden rounded border border-border bg-background px-1.5 py-0.5 text-2xs text-muted-foreground lg:inline">
          Ctrl K
        </kbd>
      </button>
      <div className="ml-auto flex items-center gap-2">
        {user ? (
          <>
            <div className="hidden text-right sm:block">
              <p className="text-sm font-medium leading-none">{user.username}</p>
              <p className="text-2xs uppercase tracking-wide text-muted-foreground">{user.role}</p>
            </div>
            <Button variant="outline" size="sm" onClick={() => void logout()} disabled={isLoggingOut}>
              <LogOut className="h-4 w-4" />
              <span className="hidden sm:inline">Sign out</span>
            </Button>
          </>
        ) : null}
      </div>
    </header>
  );
}
