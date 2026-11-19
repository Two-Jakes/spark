import { useEffect, useRef, useState } from "react";
import type { Card } from "./types";

type SpeechStatus = "starting" | "playing" | "paused" | "error";

export interface SpeechPlayback {
  id: string;
  status: SpeechStatus;
  message?: string;
}

/** Manage browser speech for one story at a time and expose its controls and state. */
export function useSpeech(): {
  playback: SpeechPlayback | null;
  listen: (card: Card) => void;
  stop: () => void;
} {
  const [playback, setPlayback] = useState<SpeechPlayback | null>(null);
  const active = useRef<SpeechSynthesisUtterance | null>(null);

  useEffect(() => () => {
    if (active.current) window.speechSynthesis.cancel();
    active.current = null;
  }, []);

  /** Stop speech and clear the controls for the previously playing story. */
  function stop(): void {
    const previous = active.current;
    active.current = null;
    if (previous) window.speechSynthesis.cancel();
    setPlayback(null);
  }

  /** Start, pause, or resume speech for the requested story. */
  function listen(card: Card): void {
    const synthesis = window.speechSynthesis;
    if (!synthesis || typeof SpeechSynthesisUtterance !== "function") {
      setPlayback({ id: card.id, status: "error", message: "Audio is unavailable in this browser." });
      return;
    }
    try {
      if (active.current && playback?.id === card.id) {
        if (playback.status === "playing") {
          synthesis.pause();
          setPlayback({ id: card.id, status: "paused" });
        } else if (playback.status === "paused") {
          synthesis.resume();
          setPlayback({ id: card.id, status: "playing" });
        }
        return;
      }

      stop();
      if (synthesis.paused) synthesis.resume();
      const utterance = new SpeechSynthesisUtterance(`${card.hook}. ${card.body}`);
      active.current = utterance;
      utterance.onstart = () => {
        if (active.current === utterance) setPlayback({ id: card.id, status: "playing" });
      };
      utterance.onend = () => {
        if (active.current === utterance) {
          active.current = null;
          setPlayback(null);
        }
      };
      utterance.onerror = () => {
        if (active.current === utterance) {
          active.current = null;
          setPlayback({ id: card.id, status: "error", message: "Audio could not play. Try again." });
        }
      };
      setPlayback({ id: card.id, status: "starting" });
      synthesis.speak(utterance);
    } catch {
      active.current = null;
      setPlayback({ id: card.id, status: "error", message: "Audio could not play. Try again." });
    }
  }

  return { playback, listen, stop };
}
