import { useEffect, useRef, useState } from "react";

import { queryClient } from "@/lib/queryClient";
import { queryKeys } from "@/lib/queryKeys";
import type { MissionEventPayload } from "@/lib/types";
import { createMissionEventsSocket } from "@/lib/ws";

const INVALIDATION_EVENTS = new Set([
  "mission_created",
  "mission_started",
  "mission_phase_changed",
  "mission_task_started",
  "mission_task_completed",
  "mission_task_failed",
  "mission_completed",
  "mission_failed",
  "mission_cancelled",
  "finding_discovered",
  "finding_verified",
  "finding_exploited",
  "tool_execution_started",
  "tool_execution_completed",
  "tool_execution_failed",
]);

export interface LiveEvent extends MissionEventPayload {
  id: string;
  receivedAt: string;
}

export function useMissionEventsFeed(maxEvents = 50) {
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const counterRef = useRef(0);

  useEffect(() => {
    const handle = createMissionEventsSocket({
      onOpen: () => setConnected(true),
      onClose: () => setConnected(false),
      onError: () => setConnected(false),
      onMessage: (event) => {
        try {
          const payload = JSON.parse(event.data) as MissionEventPayload;
          counterRef.current += 1;
          const liveEvent: LiveEvent = {
            ...payload,
            id: `${Date.now()}-${counterRef.current}`,
            receivedAt: new Date().toISOString(),
          };
          setEvents((current) => [liveEvent, ...current].slice(0, maxEvents));

          if (payload.type && INVALIDATION_EVENTS.has(payload.type)) {
            void queryClient.invalidateQueries({ queryKey: queryKeys.missions.all });
            void queryClient.invalidateQueries({ queryKey: queryKeys.findings.all });
          }
        } catch {
          counterRef.current += 1;
          setEvents((current) =>
            [
              {
                id: `${Date.now()}-${counterRef.current}`,
                type: "raw",
                data: { message: event.data },
                receivedAt: new Date().toISOString(),
              },
              ...current,
            ].slice(0, maxEvents),
          );
        }
      },
    });

    handle.connect();
    return () => handle.close();
  }, [maxEvents]);

  return { events, connected };
}
