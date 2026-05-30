import { RelativeTime } from "@/components/common/DisplayPrimitives";
import { StatusBadge } from "@/components/common/StatusBadge";
import { ErrorState, LoadingState } from "@/components/common/StateViews";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useSystemStatus } from "@/hooks/useSystemStatus";
import { getApiErrorMessage } from "@/lib/api-helpers";

export function SystemStatusPanel() {
  const systemQuery = useSystemStatus({ refetchInterval: 30_000 });

  if (systemQuery.isLoading) {
    return <LoadingState label="Checking system status…" />;
  }

  if (systemQuery.isError || !systemQuery.data) {
    return (
      <ErrorState message={getApiErrorMessage(systemQuery.error)} onRetry={() => void systemQuery.refetch()} />
    );
  }

  const data = systemQuery.data;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Platform status</CardTitle>
          <CardDescription>{data.message}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <StatusBadge status={data.status} />
            <RelativeTime date={data.timestamp} className="text-xs text-muted-foreground" />
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-2">
              <p className="text-muted-foreground">Database</p>
              <Badge variant="outline" className="mt-1">
                {data.database.status}
              </Badge>
            </div>
            <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-2">
              <p className="text-muted-foreground">Cache</p>
              <Badge variant="outline" className="mt-1">
                {data.cache.status}
              </Badge>
            </div>
            <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-2">
              <p className="text-muted-foreground">RAG</p>
              <Badge variant="outline" className="mt-1">
                {data.rag_status}
              </Badge>
            </div>
            <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-2">
              <p className="text-muted-foreground">Setup</p>
              <Badge variant="outline" className="mt-1">
                {data.setup_complete ? "complete" : "pending"}
              </Badge>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Tool stats</CardTitle>
          <CardDescription>
            {data.tool_stats.ready}/{data.tool_stats.total} ready
            {data.tools_installing ? " · installs in progress" : ""}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-2 text-center text-xs">
            {(["ready", "installing", "failed", "pending", "disabled"] as const).map((key) => (
              <div key={key} className="rounded-md border border-border/60 bg-muted/20 px-2 py-2">
                <p className="text-muted-foreground capitalize">{key}</p>
                <p className="font-mono text-lg tabular-nums">{data.tool_stats[key]}</p>
              </div>
            ))}
          </div>
          {data.operations.length > 0 ? (
            <ul className="mt-4 space-y-2 text-xs">
              {data.operations.map((op) => (
                <li key={op.id} className="rounded-md border border-border/40 px-2 py-1.5">
                  <span className="font-medium">{op.description}</span>
                  {op.progress !== null ? (
                    <span className="ml-2 font-mono text-muted-foreground">{Math.round(op.progress)}%</span>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
