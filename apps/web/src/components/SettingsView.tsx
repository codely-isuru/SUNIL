"use client";

/**
 * Settings — PORTAL_SHELL_SPEC.md §9. Minimal, and honest about being minimal.
 *
 * SAVE MODEL: per-section, explicit `SAVE`, NO autosave. Phase 1 settings include
 * security-relevant values, and silent persistence of a security setting is a bad habit to
 * establish. Save is disabled only when the section is unmodified — a state the user caused
 * and can see — and the section shows an unsaved-changes marker.
 *
 * On success the values REMAIN VISIBLE with an inline "Saved" lamp beside the button; the form
 * is never replaced by a success screen. On failure the values are NOT discarded and a RETRY
 * re-submits the same payload.
 *
 * REGIONAL is the section that closes the inherited Melbourne defect (A-10): the zone is a
 * stored IANA name, the preview is rendered through it, and "use this device's time zone"
 * stores the RESOLVED name rather than the string "auto" (§6.3).
 */
import { useEffect, useRef, useState } from "react";
import type { JSX } from "react";
import {
  Alert,
  Button,
  EmptyState,
  Field,
  Lamp,
  Panel,
  Skeleton,
  detectDeviceTimeZone,
  formatClockTime,
  isoWithOffset,
  zoneLabel,
} from "@sunil/ui";
import { fetchSessions, saveSetting } from "../lib/api/client";
import type { ApiFailureKind, SessionSummary } from "../lib/api/types";
import { useTimeZone } from "../lib/time/TimeZoneProvider";
import { useSession } from "../lib/session/SessionProvider";
import { useAppearance } from "../lib/appearance/AppearanceProvider";

type SectionId = "profile" | "regional" | "security" | "appearance" | "about";

const SECTIONS: readonly { id: SectionId; label: string }[] = [
  { id: "profile", label: "Profile" },
  { id: "regional", label: "Regional" },
  { id: "security", label: "Security" },
  { id: "appearance", label: "Appearance" },
  { id: "about", label: "About" },
];

/**
 * A short list of zones for the select. The full IANA set belongs behind the searchable
 * control §9 describes; `Intl.supportedValuesOf('timeZone')` supplies it where available, and
 * this list is the fallback so the control is never empty.
 */
const FALLBACK_ZONES = [
  "Australia/Hobart",
  "Australia/Melbourne",
  "Australia/Sydney",
  "Australia/Brisbane",
  "Australia/Adelaide",
  "Australia/Perth",
  "Australia/Darwin",
  "Pacific/Auckland",
  "Asia/Singapore",
  "Europe/London",
  "America/New_York",
  "UTC",
];

function useZoneOptions(): readonly string[] {
  const [zones, setZones] = useState<readonly string[]>(FALLBACK_ZONES);
  useEffect(() => {
    const supported = (
      Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
    ).supportedValuesOf;
    if (typeof supported === "function") {
      try {
        setZones(supported("timeZone"));
      } catch {
        setZones(FALLBACK_ZONES);
      }
    }
  }, []);
  return zones;
}

interface SaveState {
  readonly status: "idle" | "saving" | "saved" | "error";
  readonly message?: string;
}

function SaveRow({
  dirty,
  state,
  onSave,
}: {
  dirty: boolean;
  state: SaveState;
  onSave: () => void;
}): JSX.Element {
  return (
    <div className="sunil-settings__actions">
      <Button disabled={!dirty} busy={state.status === "saving"} busyLabel="Saving" onClick={onSave}>
        Save
      </Button>
      {dirty ? <span className="sunil-type-micro sunil-fg-muted">Unsaved changes</span> : null}
      {state.status === "saved" ? (
        <span className="sunil-saved sunil-type-micro">
          <Lamp state="on" label="Saved" />
          <span aria-hidden="true">Saved</span>
        </span>
      ) : null}
      {state.status === "error" ? (
        <Button variant="ghost" onClick={onSave}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}

function useSaver(): [SaveState, (key: string, value: unknown, csrfToken?: string) => void] {
  const [state, setState] = useState<SaveState>({ status: "idle" });
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    },
    [],
  );

  const save = (key: string, value: unknown, csrfToken?: string): void => {
    setState({ status: "saving" });
    void saveSetting(key, value, csrfToken).then((result) => {
      if (result.ok) {
        setState({ status: "saved" });
        // Auto-clears after 4s (§9). The saved values stay on screen.
        timerRef.current = setTimeout(() => {
          setState({ status: "idle" });
        }, 4000);
        return;
      }
      setState({
        status: "error",
        message:
          result.kind === "forbidden"
            ? "Could not save. This session does not have permission to change settings."
            : result.kind === "timeout" || result.kind === "network"
              ? "Could not save. The server did not respond."
              : "Could not save. The server rejected the request.",
      });
    });
  };

  return [state, save];
}

export function SettingsView(): JSX.Element {
  const [active, setActive] = useState<SectionId>("profile");
  const session = useSession();

  return (
    <div className="sunil-settings">
      <nav aria-label="Settings sections">
        <ul>
          {SECTIONS.map((section) => (
            <li key={section.id}>
              <a
                className="sunil-nav__item sunil-type-body-sm"
                href={`#${section.id}`}
                aria-current={active === section.id ? "true" : undefined}
                onClick={() => {
                  setActive(section.id);
                }}
              >
                <span className="sunil-nav__label">{section.label}</span>
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <div className="sunil-settings__section">
        {session.limited ? (
          <Alert tone="info">
            Your profile could not be loaded, so the values below are unavailable rather than
            wrong. Sign in again or check that the API is running.
          </Alert>
        ) : null}
        <ProfileSection />
        <RegionalSection />
        <SecuritySection />
        <AppearanceSection />
        <AboutSection />
      </div>
    </div>
  );
}

function ProfileSection(): JSX.Element {
  const session = useSession();
  const [displayName, setDisplayName] = useState(session.displayName);
  const [state, save] = useSaver();
  const dirty = displayName !== session.displayName;

  return (
    <Panel title="Profile" titleId="profile">
      {state.status === "error" ? <Alert>{state.message}</Alert> : null}
      <Field
        label="Display name"
        value={displayName}
        autoComplete="name"
        onChange={(event) => {
          setDisplayName(event.target.value);
        }}
      />
      <p className="sunil-type-caption sunil-fg-secondary">
        Role: {session.roleLabel}. Contact the system owner to change your email address or your
        role.
      </p>
      <SaveRow
        dirty={dirty}
        state={state}
        onSave={() => {
          save("profile.displayName", displayName, session.csrfToken);
        }}
      />
    </Panel>
  );
}

function RegionalSection(): JSX.Element {
  const session = useSession();
  const { timeZone, hour12, setTimeZone, setHour12 } = useTimeZone();
  const zones = useZoneOptions();
  const [pendingZone, setPendingZone] = useState(timeZone);
  const [pendingHour12, setPendingHour12] = useState(hour12);
  const [state, save] = useSaver();
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    setNow(new Date());
    const interval = setInterval(() => {
      setNow(new Date());
    }, 1000);
    return () => {
      clearInterval(interval);
    };
  }, []);

  const dirty = pendingZone !== timeZone || pendingHour12 !== hour12;
  const device = detectDeviceTimeZone();

  return (
    <Panel title="Regional" titleId="regional">
      {state.status === "error" ? <Alert>{state.message}</Alert> : null}

      <div className="sunil-field">
        <label className="sunil-field__label sunil-type-micro" htmlFor="settings-timezone">
          Time zone
        </label>
        <select
          id="settings-timezone"
          className="sunil-field__input sunil-type-body"
          value={pendingZone}
          onChange={(event) => {
            setPendingZone(event.target.value);
          }}
        >
          {zones.map((zone) => (
            <option key={zone} value={zone}>
              {zone}
            </option>
          ))}
        </select>
        <p className="sunil-field__hint sunil-type-caption">
          Stored as an IANA zone name, always. Choosing your device&apos;s zone stores the
          resolved name, not &quot;auto&quot;.
        </p>
      </div>

      <Button
        variant="ghost"
        onClick={() => {
          setPendingZone(device);
        }}
      >
        Use this device&apos;s time zone ({device})
      </Button>

      <div className="sunil-field">
        <label className="sunil-field__label sunil-type-micro" htmlFor="settings-hour12">
          Time format
        </label>
        <select
          id="settings-hour12"
          className="sunil-field__input sunil-type-body"
          value={pendingHour12 ? "12" : "24"}
          onChange={(event) => {
            setPendingHour12(event.target.value === "12");
          }}
        >
          <option value="24">24-hour</option>
          <option value="12">12-hour</option>
        </select>
      </div>

      <p
        className="sunil-type-caption sunil-fg-secondary"
        title={now === null ? undefined : isoWithOffset(now, pendingZone)}
      >
        {now === null
          ? "Preview unavailable."
          : `Preview: ${formatClockTime(now, { timeZone: pendingZone, hour12: pendingHour12 })} — ${zoneLabel(now, pendingZone)}`}
      </p>

      <SaveRow
        dirty={dirty}
        state={state}
        onSave={() => {
          // Applied locally so every timestamp in the app re-renders without a reload (§6.7),
          // and persisted through the API like every other setting.
          setTimeZone(pendingZone);
          setHour12(pendingHour12);
          save("regional.timezone", pendingZone, session.csrfToken);
        }}
      />
    </Panel>
  );
}

function SecuritySection(): JSX.Element {
  const [sessions, setSessions] = useState<readonly SessionSummary[] | null>(null);
  const [error, setError] = useState<ApiFailureKind | null>(null);

  useEffect(() => {
    void fetchSessions().then((result) => {
      if (result.ok) {
        setSessions(result.data);
        setError(null);
      } else {
        setError(result.kind);
      }
    });
  }, []);

  return (
    <Panel title="Security" titleId="security">
      <h3 className="sunil-type-body sunil-fg-primary">Multi-factor authentication</h3>
      <p className="sunil-type-caption sunil-fg-secondary">
        Enrolment is available through the API in Phase 1. The in-portal enrolment flow — QR
        code, manual key and one-time recovery codes — is not built yet, and is listed in the
        handover rather than half-shown here.
      </p>

      <h3 className="sunil-type-body sunil-fg-primary">Active sessions</h3>
      {error !== null ? (
        <>
          <Alert>Could not load sessions.</Alert>
          {/* The revoke control is HIDDEN while the list is unknown: never offer an action
              against stale data (§13). */}
        </>
      ) : sessions === null ? (
        <div className="sunil-list">
          <Skeleton height={28} />
          <Skeleton height={28} />
          <Skeleton height={28} />
        </div>
      ) : sessions.length === 0 ? (
        <EmptyState>No other sessions are active.</EmptyState>
      ) : (
        <div className="sunil-list">
          {sessions.map((item) => (
            <div className="sunil-sysrow" key={item.id}>
              <span className="sunil-sysrow__name sunil-type-caption">
                {item.device} · {item.ip}
              </span>
              <span className="sunil-sysrow__state sunil-type-micro">
                {item.current ? "This session" : item.lastSeenAt}
              </span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

function AppearanceSection(): JSX.Element {
  const session = useSession();
  const { motion, scanlines, setMotion, setScanlines } = useAppearance();
  const [state, save] = useSaver();

  return (
    <Panel title="Appearance" titleId="appearance">
      {state.status === "error" ? <Alert>{state.message}</Alert> : null}

      <div className="sunil-field">
        <label className="sunil-field__label sunil-type-micro" htmlFor="settings-theme">
          Theme
        </label>
        <select id="settings-theme" className="sunil-field__input sunil-type-body" value="dark" disabled>
          <option value="dark">Dark</option>
        </select>
        <p className="sunil-field__hint sunil-type-caption">
          The light theme arrives with a later phase.
        </p>
      </div>

      <div className="sunil-field">
        <label className="sunil-field__label sunil-type-micro" htmlFor="settings-motion">
          Motion
        </label>
        <select
          id="settings-motion"
          className="sunil-field__input sunil-type-body"
          value={motion}
          onChange={(event) => {
            const value = event.target.value as typeof motion;
            setMotion(value);
            save("appearance.motion", value, session.csrfToken);
          }}
        >
          <option value="system">Follow system</option>
          <option value="reduce">Always reduce</option>
          <option value="no-reduce">Never reduce</option>
        </select>
        <p className="sunil-field__hint sunil-type-caption">
          Overrides your operating system&apos;s reduced-motion setting in both directions.
        </p>
      </div>

      <div className="sunil-field">
        <label className="sunil-field__label sunil-type-micro" htmlFor="settings-ambience">
          Ambience
        </label>
        <select
          id="settings-ambience"
          className="sunil-field__input sunil-type-body"
          value={scanlines ? "on" : "off"}
          onChange={(event) => {
            const value = event.target.value === "on";
            setScanlines(value);
            save("appearance.scanlines", value, session.csrfToken);
          }}
        >
          <option value="on">Scanlines on</option>
          <option value="off">Scanlines off</option>
        </select>
      </div>
    </Panel>
  );
}

function AboutSection(): JSX.Element {
  return (
    <Panel title="About" titleId="about">
      <div className="sunil-list sunil-type-caption">
        <div className="sunil-list__row">
          <span className="sunil-list__row-label">Application</span>
          <span>SUNIL portal</span>
        </div>
        <div className="sunil-list__row">
          <span className="sunil-list__row-label">Phase</span>
          <span>Phase 1 — Foundation</span>
        </div>
        <div className="sunil-list__row">
          <span className="sunil-list__row-label">Theme</span>
          <span>Dark only (FR-103)</span>
        </div>
      </div>
      <p className="sunil-type-caption sunil-fg-secondary">
        Phase 1 has no assistant features, no connected business data, and no LLM provider
        verified against a live endpoint. Everything the navigation shows with a phase badge is
        planned, not built.
      </p>
    </Panel>
  );
}
