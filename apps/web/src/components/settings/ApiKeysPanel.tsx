import { useState } from "react";

import { RelativeTime } from "@/components/common/DisplayPrimitives";
import { ErrorState, LoadingState } from "@/components/common/StateViews";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from "@/hooks/useApiKeys";
import { getApiErrorMessage } from "@/lib/api-helpers";

export function ApiKeysPanel() {
  const keysQuery = useApiKeys();
  const createMutation = useCreateApiKey();
  const revokeMutation = useRevokeApiKey();
  const [newKeyName, setNewKeyName] = useState("");
  const [createdKey, setCreatedKey] = useState<string | null>(null);

  async function handleCreate() {
    const name = newKeyName.trim() || "API Key";
    try {
      const result = await createMutation.mutateAsync(name);
      setCreatedKey(result.key);
      setNewKeyName("");
    } catch {
      // toast handled in hook
    }
  }

  if (keysQuery.isLoading) {
    return <LoadingState label="Loading API keys…" />;
  }

  if (keysQuery.isError) {
    return <ErrorState message={getApiErrorMessage(keysQuery.error)} onRetry={() => void keysQuery.refetch()} />;
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">API keys</CardTitle>
          <CardDescription>Programmatic access for CI/CD and integrations</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Input
              placeholder="Key name"
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
              className="max-w-xs"
            />
            <Button onClick={() => void handleCreate()} disabled={createMutation.isPending}>
              Create key
            </Button>
          </div>

          {!keysQuery.data?.length ? (
            <p className="text-sm text-muted-foreground">No API keys yet.</p>
          ) : (
            <ul className="divide-y divide-border/60 rounded-lg border border-border">
              {keysQuery.data.map((key) => (
                <li key={key.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                  <div>
                    <p className="text-sm font-medium">{key.name}</p>
                    <p className="font-mono text-xs text-muted-foreground">{key.prefix}…</p>
                    <p className="text-2xs text-muted-foreground">
                      Created <RelativeTime date={key.created_at} />
                      {key.last_used_at ? (
                        <>
                          {" · "}Last used <RelativeTime date={key.last_used_at} />
                        </>
                      ) : null}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={revokeMutation.isPending}
                    onClick={() => void revokeMutation.mutateAsync(key.id)}
                  >
                    Revoke
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Dialog open={Boolean(createdKey)} onOpenChange={(open) => !open && setCreatedKey(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>API key created</DialogTitle>
            <DialogDescription>Copy this key now — it won&apos;t be shown again.</DialogDescription>
          </DialogHeader>
          <Label className="font-mono text-xs break-all">{createdKey}</Label>
          <DialogFooter>
            <Button
              onClick={() => {
                if (createdKey) void navigator.clipboard.writeText(createdKey);
              }}
            >
              Copy to clipboard
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
