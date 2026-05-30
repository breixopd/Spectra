import { Play } from "lucide-react";
import { useState } from "react";

import { KeyValue } from "@/components/common/DisplayPrimitives";
import { StatusBadge } from "@/components/common/StatusBadge";
import { ErrorState, LoadingState } from "@/components/common/StateViews";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useInstallTool, useTestTool, useTool } from "@/hooks/useTools";
import { getApiErrorMessage } from "@/lib/api-helpers";

interface ToolDetailSheetProps {
  toolId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ToolDetailSheet({ toolId, open, onOpenChange }: ToolDetailSheetProps) {
  const toolQuery = useTool(toolId ?? "");
  const installMutation = useInstallTool();
  const testMutation = useTestTool();
  const [testTarget, setTestTarget] = useState("127.0.0.1");

  const tool = toolQuery.data;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{tool?.name ?? "Tool detail"}</SheetTitle>
          <SheetDescription>{tool?.description ?? "Loading…"}</SheetDescription>
        </SheetHeader>

        {toolQuery.isLoading ? (
          <LoadingState label="Loading tool…" />
        ) : toolQuery.isError ? (
          <ErrorState message={getApiErrorMessage(toolQuery.error)} onRetry={() => void toolQuery.refetch()} />
        ) : tool ? (
          <div className="mt-6 space-y-6">
            <div className="flex items-center gap-2">
              <StatusBadge status={tool.status} />
              <span className="font-mono text-xs text-muted-foreground">{tool.id}</span>
            </div>

            <div className="space-y-2">
              <KeyValue label="Category" value={tool.category} />
              <KeyValue label="Version" value={tool.version} mono />
              <KeyValue label="Installed" value={tool.installed_version ?? "—"} mono />
              <KeyValue label="Timeout" value={`${tool.timeout}s`} />
              {tool.status_message ? <KeyValue label="Status" value={tool.status_message} /> : null}
              {tool.error_message ? (
                <p className="text-xs text-destructive">{tool.error_message}</p>
              ) : null}
            </div>

            <Separator />

            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={installMutation.isPending}
                onClick={() => void installMutation.mutateAsync(tool.id)}
              >
                Install / Reinstall
              </Button>
            </div>

            <div className="space-y-2">
              <Label htmlFor="test-target">Test target</Label>
              <div className="flex gap-2">
                <Input
                  id="test-target"
                  value={testTarget}
                  onChange={(e) => setTestTarget(e.target.value)}
                  className="font-mono text-xs"
                />
                <Button
                  size="sm"
                  disabled={testMutation.isPending}
                  onClick={() => void testMutation.mutateAsync({ toolId: tool.id, target: testTarget })}
                >
                  <Play className="mr-1 h-3 w-3" />
                  Test
                </Button>
              </div>
            </div>

            {tool.install_logs.length > 0 ? (
              <div className="space-y-2">
                <Label>Install logs</Label>
                <ScrollArea className="h-32 rounded-md border border-border bg-muted/20 p-2 font-mono text-2xs">
                  {tool.install_logs.map((line, i) => (
                    <div key={i}>{line}</div>
                  ))}
                </ScrollArea>
              </div>
            ) : null}
          </div>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
