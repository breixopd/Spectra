import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useCreateMission } from "@/hooks/useMissions";
import { getApiErrorMessage } from "@/lib/api-helpers";

interface CreateMissionDialogProps {
  onCreated?: (missionId: string) => void;
}

export function CreateMissionDialog({ onCreated }: CreateMissionDialogProps) {
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState("");
  const [directive, setDirective] = useState("Perform a comprehensive security assessment");
  const [framework, setFramework] = useState("ptes");
  const [scanMode, setScanMode] = useState<"autonomous" | "guided" | "manual">("autonomous");
  const [authorized, setAuthorized] = useState(false);

  const createMutation = useCreateMission();

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!authorized) {
      toast.error("You must confirm authorization to test the target");
      return;
    }

    try {
      const mission = await createMutation.mutateAsync({
        target: target.trim(),
        directive: directive.trim(),
        pentest_framework: framework,
        scan_mode: scanMode,
        authorization_confirmed: true,
      });
      toast.success("Mission started");
      setOpen(false);
      setTarget("");
      setAuthorized(false);
      onCreated?.(mission.id);
    } catch (error) {
      toast.error(getApiErrorMessage(error));
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>New mission</Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Start assessment</DialogTitle>
          <DialogDescription>Launch a new security assessment against an authorized target.</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="target">Target</Label>
            <Input
              id="target"
              placeholder="example.com or 10.0.0.0/24"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="directive">Directive</Label>
            <Textarea
              id="directive"
              rows={3}
              value={directive}
              onChange={(e) => setDirective(e.target.value)}
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>Framework</Label>
              <Select value={framework} onValueChange={setFramework}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ptes">PTES</SelectItem>
                  <SelectItem value="owasp">OWASP</SelectItem>
                  <SelectItem value="nist">NIST</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Scan mode</Label>
              <Select value={scanMode} onValueChange={(v) => setScanMode(v as typeof scanMode)}>
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
          </div>
          <label className="flex cursor-pointer items-start gap-3 rounded-md border border-border/60 bg-muted/20 p-3 text-sm">
            <input
              type="checkbox"
              checked={authorized}
              onChange={(e) => setAuthorized(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-border accent-primary"
            />
            <span className="text-muted-foreground">
              I confirm I own this target or have explicit written authorization to test it.
            </span>
          </label>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={createMutation.isPending || !target.trim()}>
              {createMutation.isPending ? "Starting…" : "Start mission"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
