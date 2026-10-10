// The agent inspector (S14): one organism, examined.
//
// Identity, lineage in both directions, short memory, the inherited
// package, the current action with its outcome, and compute state —
// all polled from the detail route while an agent stays selected.

import { useEffect, useState } from "react";
import { api } from "./api";
import type { AgentDetail } from "./api";
import { LineageExplorer } from "./LineageExplorer";
import { buttonStyle, colors, font, headingStyle, panelStyle } from "./theme";

type Props = {
  worldId: number;
  agentId: number;
  onClose: () => void;
  onSelectAgent: (agentId: number) => void;
};

export function AgentInspector({ worldId, agentId, onClose, onSelectAgent }: Props) {
  const [detail, setDetail] = useState<AgentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [exchanges, setExchanges] = useState<{ said: string; reply: string | null }[]>([]);

  async function send() {
    const message = draft.trim();
    if (!message) return;
    setSending(true);
    setChatError(null);
    try {
      const result = await api.chat(worldId, detail?.id ?? agentId, message);
      setExchanges((previous) => [
        ...previous,
        { said: message, reply: result.reply },
      ]);
      setDraft("");
    } catch (e) {
      setChatError(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const next = await api.agentDetail(worldId, agentId);
        if (!cancelled) {
          setDetail(next);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    }
    void load();
    const timer = window.setInterval(() => void load(), 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [worldId, agentId]);

  if (error && !detail) {
    return (
      <section style={panelStyle} aria-label="agent inspector">
        <InspectorHeader id={agentId} onClose={onClose} />
        <p style={{ color: colors.error, margin: 0 }}>{error}</p>
      </section>
    );
  }
  if (!detail) {
    return (
      <section style={panelStyle} aria-label="agent inspector">
        <InspectorHeader id={agentId} onClose={onClose} />
        <p style={{ color: colors.dim, margin: 0 }}>loading…</p>
      </section>
    );
  }

  return (
    <section style={panelStyle} aria-label="agent inspector" data-testid="agent-inspector">
      <InspectorHeader id={detail.id} onClose={onClose} />

      <div style={{ fontSize: "0.75rem", display: "grid", gap: "0.2rem" }}>
        <Row label="status" value={`${detail.status} · ${detail.policy} mind`} />
        <Row
          label="position"
          value={detail.position ? `(${detail.position.x}, ${detail.position.y})` : "—"}
        />
        <Row label="goal" value={detail.goal ?? "—"} />
      </div>

      {/* S15: the ancestry — chain, navigation, drift, comparison. */}
      <div style={{ borderTop: `1px solid ${colors.border}`, paddingTop: "0.4rem" }}>
        <LineageExplorer worldId={worldId} agentId={detail.id} onSelectAgent={onSelectAgent} />
      </div>

      <Block title="current action">
        {detail.last_action ? (
          <div style={{ fontSize: "0.7rem" }}>
            <span style={{ color: detail.last_action.ok ? colors.accent : colors.warn }}>
              {detail.last_action.ok ? "executed" : "rejected"}
            </span>{" "}
            {JSON.stringify(detail.last_action.action)}
            {detail.last_action.reason ? ` — ${detail.last_action.reason}` : ""}
            <span style={{ color: colors.dim }}> (tick {detail.last_action.tick})</span>
          </div>
        ) : (
          <span style={{ color: colors.dim, fontSize: "0.7rem" }}>no actions yet</span>
        )}
      </Block>

      {/* S21: talk to this agent — the reply comes back from its own
          decision, and both utterances ride the world timeline. */}
      <div style={{ borderTop: `1px solid ${colors.border}`, paddingTop: "0.4rem" }}>
        <h2 style={headingStyle}>talk to agent {detail.id}</h2>
        <div style={{ display: "flex", gap: "0.4rem" }}>
          <input
            style={{
              flex: 1,
              backgroundColor: colors.panelAlt,
              color: colors.text,
              border: `1px solid ${colors.border}`,
              borderRadius: 3,
              padding: "0.3rem 0.5rem",
              fontFamily: font,
              fontSize: "0.72rem",
            }}
            placeholder="say something..."
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !sending) void send();
            }}
          />
          <button
            style={{ ...buttonStyle, opacity: sending ? 0.5 : 1 }}
            disabled={sending}
            onClick={() => void send()}
          >
            send
          </button>
        </div>
        {chatError && (
          <p style={{ margin: "0.3rem 0 0", fontSize: "0.68rem", color: colors.error }}>
            {chatError}
          </p>
        )}
        {exchanges.map((exchange, index) => (
          <div key={index} style={{ marginTop: "0.4rem", fontSize: "0.7rem" }}>
            <div>
              <span style={{ color: colors.dim }}>you: </span>
              <span style={{ color: colors.text }}>{exchange.said}</span>
            </div>
            <div>
              <span style={{ color: colors.dim }}>agent {detail.id}: </span>
              <span style={{ color: exchange.reply ? colors.decision : colors.dim }}>
                {exchange.reply ?? "(no reply — a scripted mind has nothing to say)"}
              </span>
            </div>
          </div>
        ))}
      </div>

      <Block title={`memory (${detail.memory.length})`}>
        <ol style={{ listStyle: "none", margin: 0, padding: 0, fontSize: "0.68rem", display: "flex", flexDirection: "column", gap: "0.15rem", maxHeight: 140, overflowY: "auto" }}>
          {detail.memory.length === 0 && <li style={{ color: colors.dim }}>empty</li>}
          {detail.memory.map((entry, index) => (
            <li key={`${entry.tick}-${index}`} style={{ display: "flex", gap: "0.4rem" }}>
              <span style={{ color: colors.dim }}>t{entry.tick}</span>
              <span style={{ color: entry.ok ? colors.text : colors.warn }}>
                {JSON.stringify(entry.action)}
              </span>
              {!entry.ok && entry.reason && (
                <span style={{ color: colors.warn }}>({entry.reason})</span>
              )}
            </li>
          ))}
        </ol>
      </Block>

      <Block title="inherited culture">
        <Row label="traits" value={JSON.stringify(detail.inheritance.traits)} />
        <Row label="knowledge" value={`${detail.inheritance.knowledge.length} facts`} />
        <Row
          label="artifacts"
          value={`${detail.inheritance.cultural_artifacts.length} carried`}
        />
        {detail.inheritance.knowledge.length > 0 && (
          <ul style={{ margin: "0.2rem 0 0", paddingLeft: "1rem", fontSize: "0.68rem", color: colors.text }}>
            {detail.inheritance.knowledge.map((fact, index) => (
              <li key={index}>{fact}</li>
            ))}
          </ul>
        )}
      </Block>

      <Block title="compute">
        <Row label="model calls" value={String(detail.compute.model_calls)} />
        <Row
          label="provider"
          value={`${detail.provider.provider ?? "—"}/${detail.provider.model ?? "—"}`}
        />
        <Row
          label="envelope"
          value={`temp ${detail.compute.envelope.temperature} · max_tokens ${detail.compute.envelope.max_tokens ?? "—"} · timeout ${detail.compute.envelope.timeout_seconds}s`}
        />
      </Block>
    </section>
  );
}

function InspectorHeader({ id, onClose }: { id: number; onClose: () => void }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <h2 style={headingStyle}>agent {id}</h2>
      <button
        style={{ background: "none", border: "none", color: colors.dim, cursor: "pointer", fontFamily: font }}
        onClick={onClose}
        aria-label="close inspector"
      >
        ×
      </button>
    </div>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ borderTop: `1px solid ${colors.border}`, paddingTop: "0.4rem" }}>
      <div style={{ fontSize: "0.65rem", color: colors.dim, letterSpacing: "0.1em", marginBottom: "0.2rem" }}>
        {title}
      </div>
      {children}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", gap: "0.5rem" }}>
      <span style={{ color: colors.dim, minWidth: "5.5rem" }}>{label}</span>
      <span style={{ color: colors.text, wordBreak: "break-word" }}>{value}</span>
    </div>
  );
}
