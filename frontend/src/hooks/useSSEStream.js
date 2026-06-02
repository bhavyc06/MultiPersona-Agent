import { useCallback, useEffect, useRef, useState } from "react";

const BASE_URL = "http://localhost:8000";
const MAX_RECONNECT_ATTEMPTS = 5;
const BASE_DELAY_MS = 1000;
const MAX_DELAY_MS = 30000;
const TERMINAL_EVENTS = new Set(["session_complete"]);

export function useSSEStream(sessionId) {
  const [events, setEvents] = useState([]);
  const [latestEvent, setLatestEvent] = useState(null);
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState(null);
  const [reconnectCount, setReconnectCount] = useState(0);

  const sourceRef = useRef(null);
  const timerRef = useRef(null);
  const attemptsRef = useRef(0);
  const terminalRef = useRef(false); // stop reconnecting after terminal event

  const cleanup = useCallback(() => {
    if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
    }
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    if (terminalRef.current || !sessionId) return;

    const token = localStorage.getItem("access_token");
    if (!token) {
      setError("No auth token — please log in");
      setStatus("error");
      return;
    }

    const url = `${BASE_URL}/api/sessions/${sessionId}/stream?token=${encodeURIComponent(token)}`;
    setStatus("connecting");

    const source = new EventSource(url);
    sourceRef.current = source;

    source.onopen = () => {
      setStatus("connected");
      attemptsRef.current = 0;
      setReconnectCount(0);
    };

    source.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data);
        setEvents((prev) => [...prev, parsed]);
        setLatestEvent(parsed);

        if (
          TERMINAL_EVENTS.has(parsed.event) ||
          (parsed.event === "error" && !parsed.recoverable)
        ) {
          terminalRef.current = true;
          source.close();
          sourceRef.current = null;
          setStatus("closed");
        }
      } catch {
        // keep-alive comments and non-JSON lines — ignore
      }
    };

    source.onerror = () => {
      source.close();
      sourceRef.current = null;

      if (terminalRef.current) return;

      const attempts = attemptsRef.current;
      if (attempts >= MAX_RECONNECT_ATTEMPTS) {
        setStatus("error");
        setError(`Connection lost after ${MAX_RECONNECT_ATTEMPTS} reconnect attempts`);
        return;
      }

      const delay = Math.min(BASE_DELAY_MS * Math.pow(2, attempts), MAX_DELAY_MS);
      attemptsRef.current = attempts + 1;
      setReconnectCount(attempts + 1);
      setStatus("connecting");

      timerRef.current = setTimeout(connect, delay);
    };
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) {
      cleanup();
      setStatus("idle");
      setEvents([]);
      setLatestEvent(null);
      setError(null);
      setReconnectCount(0);
      attemptsRef.current = 0;
      terminalRef.current = false;
      return;
    }

    terminalRef.current = false;
    attemptsRef.current = 0;
    connect();
    return cleanup;
  }, [sessionId, connect, cleanup]);

  return { events, latestEvent, status, error, reconnectCount };
}
