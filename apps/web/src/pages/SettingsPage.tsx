import { useState } from "react";

import { PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { ErrorState, LoadingState } from "@/components/common/StateViews";
import { BillingPanel } from "@/components/settings/BillingPanel";
import { ApiKeysPanel } from "@/components/settings/ApiKeysPanel";
import { SystemStatusPanel } from "@/components/settings/SystemStatusPanel";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useUpdateUserSettings, useUserSettings } from "@/hooks/useUserSettings";
import { getApiErrorMessage } from "@/lib/api-helpers";

export function SettingsPage() {
  const settingsQuery = useUserSettings();
  const updateMutation = useUpdateUserSettings();

  const [scanMode, setScanMode] = useState<string | null>(null);
  const [reportFormat, setReportFormat] = useState<string | null>(null);
  const [timezone, setTimezone] = useState<string | null>(null);

  const settings = settingsQuery.data;
  const effectiveScanMode = scanMode ?? settings?.default_scan_mode ?? "autonomous";
  const effectiveReportFormat = reportFormat ?? settings?.default_report_format ?? "pdf";
  const effectiveTimezone = timezone ?? settings?.timezone ?? "UTC";

  async function savePreferences() {
    await updateMutation.mutateAsync({
      default_scan_mode: effectiveScanMode as "autonomous" | "guided" | "manual",
      default_report_format: effectiveReportFormat as "pdf" | "html" | "json",
      timezone: effectiveTimezone,
      prefer_mission_approval: settings?.prefer_mission_approval,
      email_notifications: settings?.email_notifications,
      notify_on_mission_complete: settings?.notify_on_mission_complete,
      notify_on_critical_finding: settings?.notify_on_critical_finding,
      share_training_data: settings?.share_training_data,
    });
  }

  return (
    <>
      <PageHeader title="Settings" description="User preferences, API keys, and platform diagnostics." />

      <Tabs defaultValue="preferences" className="space-y-4">
        <TabsList>
          <TabsTrigger value="preferences">Preferences</TabsTrigger>
          <TabsTrigger value="billing">Billing</TabsTrigger>
          <TabsTrigger value="system">System</TabsTrigger>
          <TabsTrigger value="api-keys">API keys</TabsTrigger>
        </TabsList>

        <TabsContent value="preferences">
          {settingsQuery.isLoading ? (
            <LoadingState label="Loading settings…" />
          ) : settingsQuery.isError ? (
            <ErrorState message={getApiErrorMessage(settingsQuery.error)} onRetry={() => void settingsQuery.refetch()} />
          ) : settings ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Mission defaults</CardTitle>
                <CardDescription>Applied when starting new assessments</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label>Default scan mode</Label>
                    <Select value={effectiveScanMode} onValueChange={setScanMode}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="autonomous">Autonomous</SelectItem>
                        <SelectItem value="guided">Guided</SelectItem>
                        <SelectItem value="manual">Manual</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>Default report format</Label>
                    <Select value={effectiveReportFormat} onValueChange={setReportFormat}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="pdf">PDF</SelectItem>
                        <SelectItem value="html">HTML</SelectItem>
                        <SelectItem value="json">JSON</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="timezone">Timezone</Label>
                  <Input
                    id="timezone"
                    value={effectiveTimezone}
                    onChange={(e) => setTimezone(e.target.value)}
                    className="max-w-xs font-mono text-sm"
                  />
                </div>
                <Separator />
                <div className="space-y-2 text-sm">
                  <p className="text-muted-foreground">BYOK configuration</p>
                  <div className="flex flex-wrap gap-2">
                    <StatusBadge status={settings.llm_api_key_configured ? "ready" : "pending"} />
                    <span className="text-xs text-muted-foreground">
                      LLM {settings.llm_api_key_configured ? "configured" : "not set"}
                      {settings.llm_model ? ` · ${settings.llm_model}` : ""}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <StatusBadge status={settings.embedding_api_key_configured ? "ready" : "pending"} />
                    <span className="text-xs text-muted-foreground">
                      Embeddings {settings.embedding_api_key_configured ? "configured" : "not set"}
                    </span>
                  </div>
                </div>
                <Button onClick={() => void savePreferences()} disabled={updateMutation.isPending}>
                  {updateMutation.isPending ? "Saving…" : "Save preferences"}
                </Button>
              </CardContent>
            </Card>
          ) : null}
        </TabsContent>

        <TabsContent value="billing">
          <BillingPanel />
        </TabsContent>

        <TabsContent value="system">
          <SystemStatusPanel />
        </TabsContent>

        <TabsContent value="api-keys">
          <ApiKeysPanel />
        </TabsContent>
      </Tabs>
    </>
  );
}
