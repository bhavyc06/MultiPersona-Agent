import { useEffect, useRef, useState } from "react";

export function useSSEStream(sessionId) {
  const [events, setEvents] = useState([]);
  const [status, setStatus] = useState("idle"); // idle | connecting | connected | closed | error
  const [error, setError] = useState(null);
  const sourceRef = useRef(null);

  useEffect(() => {
    if (!sessionId) return;

    const token = localStorage.getItem("access_token");
    if (!token) {
      setError("No auth token");
      setStatus("error");
      return;
    }

    // EventSource doesn't support custom headers; pass token as query param
    const url = `http://localhost:8000/api/sessions/${sessionId}/stream?token=${encodeURIComponent(token)}`;
    setStatus("connecting");

    const source = new EventSource(url);
    sourceRef.current = source;

    source.onopen = () => setStatus("connected");

    source.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data);
        setEvents((prev) => [...prev, parsed]);
        console.log("[SSE]", parsed);
      } catch {
        // keep-alive comments arrive as empty data — ignore parse errors
      }
    };

    source.onerror = (e) => {
      setError("Stream error");
      setStatus("error");
      source.close();
    };

    return () => {
      source.close();
      setStatus("closed");
    };
  }, [sessionId]);

  return { events, status, error };
}
