import { CreditCard, ExternalLink } from "lucide-react";

import { ErrorState, LoadingState } from "@/components/common/StateViews";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ProgressBar } from "@/components/common/ProgressBar";
import { useBillingCheckout, useBillingPlans, useBillingPortal, useBillingUsage } from "@/hooks/useBilling";
import { useAuth } from "@/providers/AuthProvider";
import { getApiErrorMessage } from "@/lib/api-helpers";

function formatStorage(mb: number): string {
  if (mb >= 1024) {
    return `${(mb / 1024).toFixed(1)} GB`;
  }
  return `${mb} MB`;
}

export function BillingPanel() {
  const { user } = useAuth();
  const plansQuery = useBillingPlans();
  const usageQuery = useBillingUsage();
  const checkout = useBillingCheckout();
  const portal = useBillingPortal();

  const subscription = user?.subscription as
    | { status?: string; plan_display_name?: string; can_manage_billing?: boolean }
    | null
    | undefined;
  const plan = user?.plan as { display_name?: string; name?: string } | null | undefined;

  if (plansQuery.isLoading || usageQuery.isLoading) {
    return <LoadingState label="Loading billing…" />;
  }

  if (plansQuery.isError) {
    return <ErrorState message={getApiErrorMessage(plansQuery.error)} onRetry={() => void plansQuery.refetch()} />;
  }

  const usage = usageQuery.data;
  const currentPlanName =
    subscription?.plan_display_name ?? plan?.display_name ?? usage?.plan_name ?? "No active plan";

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <CreditCard className="h-4 w-4 text-primary" />
            Current subscription
          </CardTitle>
          <CardDescription>Plan limits, usage, and self-service checkout</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-lg font-semibold">{currentPlanName}</p>
              <p className="text-sm text-muted-foreground">
                Status: {subscription?.status ?? "none"}
                {user?.is_superuser ? " · Admin (full access)" : ""}
              </p>
            </div>
            {subscription?.can_manage_billing ? (
              <Button
                variant="outline"
                size="sm"
                disabled={portal.isPending}
                onClick={() => {
                  void portal.mutateAsync().then((data) => {
                    if (data?.portal_url) {
                      window.location.href = data.portal_url;
                    }
                  });
                }}
              >
                <ExternalLink className="mr-2 h-3.5 w-3.5" />
                Billing portal
              </Button>
            ) : null}
          </div>

          {usage && usage.max_storage_mb > 0 ? (
            <div className="space-y-2 rounded-md border border-border/60 bg-muted/20 p-4">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Evidence storage</span>
                <span className="font-mono text-xs">
                  {formatStorage(usage.storage_used_mb)} / {formatStorage(usage.max_storage_mb)}
                </span>
              </div>
              <ProgressBar value={Math.min(usage.storage_pct, 100)} />
            </div>
          ) : null}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        {plansQuery.data?.map((p) => {
          const isCurrent = p.display_name === currentPlanName || p.name === plan?.name;
          return (
            <Card key={p.id} className={isCurrent ? "border-primary/40 bg-primary/5" : undefined}>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">{p.display_name}</CardTitle>
                <CardDescription>{p.description ?? "Assessment tier"}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <ul className="space-y-1 text-muted-foreground">
                  <li>{p.max_concurrent_missions} concurrent missions</li>
                  <li>{p.max_missions_per_month ?? "Unlimited"} missions / month</li>
                  <li>{formatStorage(p.max_storage_mb)} storage</li>
                </ul>
                {isCurrent ? (
                  <p className="text-xs font-medium text-primary">Current plan</p>
                ) : p.checkout_available ? (
                  <Button
                    size="sm"
                    className="w-full"
                    disabled={checkout.isPending}
                    onClick={() => {
                      void checkout.mutateAsync(p.id).then((data) => {
                        if (data?.checkout_url) {
                          window.location.href = data.checkout_url;
                        }
                      });
                    }}
                  >
                    Upgrade
                  </Button>
                ) : (
                  <p className="text-xs text-muted-foreground">Contact sales for this tier</p>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
