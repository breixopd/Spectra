import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

import { StatusBadge } from "@/components/common/StatusBadge";
import { EmptyState } from "@/components/common/StateViews";
import type { TaskTreeUITask } from "@/lib/types";
import { cn } from "@/lib/utils";

interface TaskTreeNodeProps {
  task: TaskTreeUITask;
  depth?: number;
}

function TaskTreeNode({ task, depth = 0 }: TaskTreeNodeProps) {
  const [expanded, setExpanded] = useState(depth < 2);
  const hasChildren = task.children.length > 0;

  return (
    <div className={cn(depth > 0 && "ml-4 border-l border-border/40 pl-3")}>
      <div className="flex items-center gap-2 py-1.5">
        {hasChildren ? (
          <button
            type="button"
            className="rounded p-0.5 text-muted-foreground hover:bg-muted/40"
            onClick={() => setExpanded((v) => !v)}
            aria-label={expanded ? "Collapse" : "Expand"}
          >
            {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </button>
        ) : (
          <span className="w-5" />
        )}
        <span className="min-w-0 flex-1 truncate font-mono text-xs">{task.name}</span>
        {task.tool ? <span className="text-2xs text-muted-foreground">{task.tool}</span> : null}
        <StatusBadge status={task.status} />
      </div>
      {expanded && hasChildren
        ? task.children.map((child) => <TaskTreeNode key={child.id} task={child} depth={depth + 1} />)
        : null}
    </div>
  );
}

interface MissionTaskTreeViewProps {
  tasks: TaskTreeUITask[];
}

export function MissionTaskTreeView({ tasks }: MissionTaskTreeViewProps) {
  if (!tasks.length) {
    return (
      <EmptyState
        title="No tasks yet"
        description="The attack task tree will populate as the agent plans and executes work."
      />
    );
  }

  return (
    <div className="rounded-lg border border-border/60 bg-muted/10 p-3 font-mono text-xs">
      {tasks.map((task) => (
        <TaskTreeNode key={task.id} task={task} />
      ))}
    </div>
  );
}
