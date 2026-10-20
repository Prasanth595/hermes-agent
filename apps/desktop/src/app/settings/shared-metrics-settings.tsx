import { useStore } from '@nanostores/react'
import { useEffect, useMemo, useState } from 'react'

import { DocsLink } from '@/components/onboarding/flow'
import { useI18n } from '@/i18n'
import { setDesktopMetricsGate } from '@/store/desktop-metrics'
import { requestGatewayForAgent } from '@/store/gateway'
import { notifyError } from '@/store/notifications'
import { $activeGatewayProfile, normalizeProfileKey } from '@/store/profile'
import { $settingsOwner, $settingsScopeProfile, settingsGatewayRequestOwnership } from '@/store/settings-scope'
import {
  readSharedMetricsConsent,
  saveSharedMetricsConsent,
  SHARED_METRICS_DOCS_URL,
  type SharedMetricsConsent,
  sharedMetricsProfileRequester
} from '@/store/shared-metrics'

import { ToggleRow } from './primitives'

/**
 * Settings › Safety › Privacy: the same two opt-ins the first-run dialog and
 * `hermes setup` write, for the profile this page applies to. Collection off
 * turns sending off with it (the backend enforces it too), so the send switch
 * is disabled until collection is on. Optimistic, rolled back on failure.
 */
export function SharedMetricsSettings() {
  const { t } = useI18n()
  const copy = t.sharedMetrics
  const scopeProfile = useStore($settingsScopeProfile)
  const settingsOwner = useStore($settingsOwner)
  const [consent, setConsent] = useState<SharedMetricsConsent | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)

  const request = useMemo(
    () =>
      sharedMetricsProfileRequester(
        <T,>(method: string, params: Record<string, unknown> = {}) => {
          if (!settingsOwner || $settingsOwner.get() !== settingsOwner) {
            throw new Error('Settings owner changed. Reopen Settings and try again.')
          }

          return requestGatewayForAgent<T>(
            settingsOwner.connectionId,
            settingsOwner.profile ?? scopeProfile,
            method,
            params,
            undefined,
            undefined,
            {
              ...settingsGatewayRequestOwnership(settingsOwner),
              spawnPriority: 'foreground'
            }
          )
        },
        scopeProfile
      ),
    [scopeProfile, settingsOwner]
  )

  useEffect(() => {
    let cancelled = false

    setBusy(false)
    setLoaded(false)
    void readSharedMetricsConsent(request).then(next => {
      if (!cancelled) {
        setConsent(next)
        setLoaded(true)
      }
    })

    return () => void (cancelled = true)
  }, [request])

  const save = async (flags: { enabled: boolean; send: boolean }) => {
    const previous = consent
    const owner = settingsOwner

    setBusy(true)
    setConsent({ ...flags, send: flags.enabled && flags.send, decided: true })

    try {
      const saved = await saveSharedMetricsConsent(request, flags)

      if (!owner || $settingsOwner.get() !== owner) {
        return
      }

      setConsent(saved)

      // This page applies to the focused profile (unscoped, or scoped to it by name): Desktop
      // telemetry follows its switch at once.
      const focused =
        scopeProfile === null || normalizeProfileKey(scopeProfile) === normalizeProfileKey($activeGatewayProfile.get())

      if (saved && focused) {
        setDesktopMetricsGate(saved.enabled ? 'on' : 'off')
      }
    } catch (err) {
      if (!owner || $settingsOwner.get() !== owner) {
        return
      }

      setConsent(previous)
      notifyError(err, copy.saveFailed)
    } finally {
      if (owner && $settingsOwner.get() === owner) {
        setBusy(false)
      }
    }
  }

  // An older backend has no shared_metrics.* methods: keep the controls, disabled and explained.
  const unavailable = loaded && consent === null
  const enabled = consent?.enabled ?? false
  const send = consent?.send ?? false

  return (
    <div className="grid gap-1" id="setting-shared-metrics">
      <ToggleRow
        checked={enabled}
        description={copy.collectDesc}
        disabled={!consent || busy}
        hint={unavailable ? copy.unavailable : undefined}
        label={copy.collectLabel}
        onChange={on => void save({ enabled: on, send: on && send })}
      />
      <ToggleRow
        below={<DocsLink href={SHARED_METRICS_DOCS_URL}>{copy.whatIsCollected}</DocsLink>}
        checked={send}
        description={copy.sendDesc}
        disabled={!consent || busy || !enabled}
        label={copy.sendLabel}
        onChange={on => void save({ enabled, send: on })}
      />
    </div>
  )
}
