/*
 * SessionEventsContext — single SSE subscription per dashboard session,
 * shared via React context across all consumers (AgentActivityPanel,
 * PlanStepper, TerminalCard).
 *
 * Before: each consumer called useV2SessionEvents(sessionId) directly,
 * which opened 3-4 concurrent SSE connections to the same session
 * (browser per-origin cap is 6). After: one Provider subscribes once
 * and downstream components read `events` + `status` from context.
 */
import { createContext, useContext } from 'react';
import { useV2SessionEvents } from './hooks/useV2SessionEvents';

const SessionEventsContext = createContext({ events: [], status: 'idle' });

export const SessionEventsProvider = ({ sessionId, children }) => {
  const value = useV2SessionEvents(sessionId);
  return (
    <SessionEventsContext.Provider value={value}>
      {children}
    </SessionEventsContext.Provider>
  );
};

export const useSessionEvents = () => useContext(SessionEventsContext);
