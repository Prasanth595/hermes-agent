// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { $activeGatewayProfile } from '@/store/profile'
import { $connection } from '@/store/session'
import { $settingsOwner } from '@/store/settings-scope'

import { SharedMetricsSettings } from './shared-metrics-settings'

const mocks = vi.hoisted(() => ({
  gate: vi.fn(),
  notifyError: vi.fn(),
  request: vi.fn()
}))

vi.mock('@/store/desktop-metrics', () => ({
  setDesktopMetricsGate: (...args: unknown[]) => mocks.gate(...args)
}))
vi.mock('@/store/gateway', () => ({
  requestGatewayForAgent: (...args: unknown[]) => mocks.request(...args)
}))
vi.mock('@/store/notifications', () => ({
  notifyError: (...args: unknown[]) => mocks.notifyError(...args)
}))

function deferred<T>() {
  let resolve!: (value: T) => void

  const promise = new Promise<T>(yes => {
    resolve = yes
  })

  return { promise, resolve }
}

describe('SharedMetricsSettings owner isolation', () => {
  beforeEach(() => {
    $activeGatewayProfile.set('default')
    $connection.set({
      baseUrl: 'https://original.example',
      connectionId: 'same-id',
      mode: 'remote',
      profile: 'default',
      token: 'original-token'
    } as never)
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
    $connection.set(null)
  })

  it('pins consent writes to the captured owner and ignores their stale settlement', async () => {
    const save = deferred<{ decided: boolean; enabled: boolean; send: boolean }>()
    mocks.request.mockImplementation(async (_connectionId, _profile, method) => {
      if (method === 'shared_metrics.set') {
        return save.promise
      }

      return { decided: true, enabled: false, send: false }
    })

    render(<SharedMetricsSettings />)
    const collect = await screen.findByRole('switch', { name: /collect/i })
    await waitFor(() => expect((collect as HTMLButtonElement).disabled).toBe(false))
    const capturedOwner = $settingsOwner.get()!

    fireEvent.click(collect)
    await waitFor(() =>
      expect(mocks.request).toHaveBeenCalledWith(
        'same-id',
        'default',
        'shared_metrics.set',
        expect.objectContaining({ enabled: true, profile: 'default' }),
        undefined,
        undefined,
        expect.objectContaining({
          expectedConnectionOwner: capturedOwner.cacheOwner ?? capturedOwner.connectionOwner,
          expectedOwner: expect.objectContaining({ connectionOwner: capturedOwner.connectionOwner }),
          spawnPriority: 'foreground'
        })
      )
    )

    act(() => {
      $connection.set({
        baseUrl: 'https://replacement.example',
        connectionId: 'same-id',
        mode: 'remote',
        profile: 'default',
        token: 'replacement-token'
      } as never)
    })
    await act(async () => save.resolve({ decided: true, enabled: true, send: false }))

    const replacementOwner = $settingsOwner.get()!
    expect(replacementOwner).not.toBe(capturedOwner)
    await waitFor(() => expect((collect as HTMLButtonElement).disabled).toBe(false))
    expect(
      mocks.request.mock.calls.filter(
        ([, , method, , , , options]) =>
          method === 'shared_metrics.set' && options?.expectedConnectionOwner === replacementOwner.cacheOwner
      )
    ).toHaveLength(0)
    expect(mocks.gate).not.toHaveBeenCalled()
    expect(mocks.notifyError).not.toHaveBeenCalled()
  })
})