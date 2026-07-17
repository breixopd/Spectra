import { useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { commandPaletteItems } from "@/config/navigation";
import { cn } from "@/lib/utils";

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!open) {
      setQuery("");
    }
  }, [open]);

  const filtered = commandPaletteItems.filter((item) => {
    const haystack = `${item.label} ${item.description ?? ""}`.toLowerCase();
    return haystack.includes(query.toLowerCase());
  });

  function goTo(href: string) {
    onOpenChange(false);
    void navigate({ to: href });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b border-border px-4 py-3">
          <DialogTitle className="text-base">Command palette</DialogTitle>
          <DialogDescription>Jump to any workspace section.</DialogDescription>
        </DialogHeader>
        <div className="border-b border-border px-4 py-2">
          <Input
            autoFocus
            placeholder="Type a destination…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="border-0 bg-transparent px-0 shadow-none focus-visible:ring-0"
            onKeyDown={(event) => {
              if (event.key === "Enter" && filtered[0]) {
                event.preventDefault();
                goTo(filtered[0].href);
              }
            }}
          />
        </div>
        <ScrollArea className="max-h-72">
          <div className="p-2">
            {filtered.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.href + item.label}
                  type="button"
                  className={cn(
                    "flex w-full items-start gap-3 rounded-md px-3 py-2 text-left transition-colors hover:bg-accent",
                  )}
                  onClick={() => goTo(item.href)}
                >
                  <Icon className="mt-0.5 h-4 w-4 text-muted-foreground" />
                  <span>
                    <span className="block text-sm font-medium">{item.label}</span>
                    {item.description ? (
                      <span className="block text-xs text-muted-foreground">{item.description}</span>
                    ) : null}
                  </span>
                </button>
              );
            })}
            {filtered.length === 0 ? (
              <p className="px-3 py-6 text-center text-sm text-muted-foreground">No matching destinations.</p>
            ) : null}
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}

export function useCommandPalette() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((current) => !current);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return { open, setOpen };
}
