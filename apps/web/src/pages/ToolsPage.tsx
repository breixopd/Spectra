import { Download, Wrench } from "lucide-react";
import { useMemo, useState } from "react";

import { PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/common/StateViews";
import { ToolDetailSheet } from "@/components/tools/ToolDetailSheet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useInstallTool, useTools } from "@/hooks/useTools";
import { getApiErrorMessage } from "@/lib/api-helpers";
import type { ToolSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

function groupByCategory(tools: ToolSummary[]): Map<string, ToolSummary[]> {
  const map = new Map<string, ToolSummary[]>();
  for (const tool of tools) {
    const category = tool.category || "other";
    const list = map.get(category) ?? [];
    list.push(tool);
    map.set(category, list);
  }
  return new Map([...map.entries()].sort(([a], [b]) => a.localeCompare(b)));
}

export function ToolsPage() {
  const toolsQuery = useTools();
  const installMutation = useInstallTool();
  const [search, setSearch] = useState("");
  const [selectedToolId, setSelectedToolId] = useState<string | null>(null);

  const filteredTools = useMemo(() => {
    const tools = toolsQuery.data?.tools ?? [];
    if (!search.trim()) return tools;
    const needle = search.toLowerCase();
    return tools.filter(
      (t) =>
        t.name.toLowerCase().includes(needle) ||
        t.id.toLowerCase().includes(needle) ||
        t.description.toLowerCase().includes(needle),
    );
  }, [toolsQuery.data?.tools, search]);

  const grouped = useMemo(() => groupByCategory(filteredTools), [filteredTools]);

  return (
    <>
      <PageHeader
        title="Tools"
        description="Plugin registry, install status, and execution telemetry."
        meta={
          toolsQuery.data ? (
            <span className="text-xs text-muted-foreground">{toolsQuery.data.total} tools registered</span>
          ) : null
        }
      />

      <div className="mb-4">
        <Input
          placeholder="Search tools…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-sm"
        />
      </div>

      {toolsQuery.isLoading ? (
        <LoadingState label="Loading tool registry…" />
      ) : toolsQuery.isError ? (
        <ErrorState message={getApiErrorMessage(toolsQuery.error)} onRetry={() => void toolsQuery.refetch()} />
      ) : filteredTools.length === 0 ? (
        <EmptyState icon={Wrench} title="No tools found" description="Adjust your search or check the registry." />
      ) : (
        <div className="space-y-6">
          {[...grouped.entries()].map(([category, tools]) => (
            <section key={category}>
              <h2 className="mb-3 text-sm font-medium capitalize text-muted-foreground">{category.replace(/_/g, " ")}</h2>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {tools.map((tool) => (
                  <Card
                    key={tool.id}
                    className={cn(
                      "cursor-pointer transition-colors hover:border-border",
                      selectedToolId === tool.id && "border-primary/50",
                    )}
                    onClick={() => setSelectedToolId(tool.id)}
                  >
                    <CardHeader className="pb-2">
                      <div className="flex items-start justify-between gap-2">
                        <CardTitle className="text-sm">{tool.name}</CardTitle>
                        <StatusBadge status={tool.status} />
                      </div>
                      <CardDescription className="line-clamp-2 text-xs">{tool.description}</CardDescription>
                    </CardHeader>
                    <CardContent className="flex items-center justify-between gap-2 pt-0">
                      <div className="flex items-center gap-2">
                        <Badge variant="outline" className="font-mono text-2xs">
                          v{tool.version}
                        </Badge>
                        {!tool.enabled ? (
                          <Badge variant="outline" className="text-2xs">
                            disabled
                          </Badge>
                        ) : null}
                      </div>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={installMutation.isPending}
                        onClick={(e) => {
                          e.stopPropagation();
                          void installMutation.mutateAsync(tool.id);
                        }}
                      >
                        <Download className="mr-1 h-3 w-3" />
                        Install
                      </Button>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      <ToolDetailSheet toolId={selectedToolId} open={Boolean(selectedToolId)} onOpenChange={(open) => !open && setSelectedToolId(null)} />
    </>
  );
}
