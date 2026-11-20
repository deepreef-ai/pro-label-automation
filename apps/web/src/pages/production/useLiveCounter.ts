import { useEffect, useRef, useState } from 'react'
import type { CounterTick, Run } from '@contract/types'
import { API_URL, api, backendHasRoute } from '@/lib/api'
import { getRole } from '@/lib/role'

export interface LiveCounter {
  tick: CounterTick | null
  /** 'sse' = real backend stream, 'sim' = simulated in the browser (mock mode or stream unavailable) */
  source: 'sse' | 'sim' | null
  paused: boolean
  setPaused: (p: boolean) => void
}

/**
 * Live meter counter for a running run.
 * Live mode: SSE `GET /api/production/counter/stream?run_id=`. Mock mode: seed from the fixture,
 * then tick once a second in the browser (about 7% wastage, 50–60 m/min).
 */
export function useLiveCounter(run: Run | null, ups: number, repeatMm: number): LiveCounter {
  const [tick, setTick] = useState<CounterTick | null>(null)
  const [source, setSource] = useState<'sse' | 'sim' | null>(null)
  const [paused, setPaused] = useState(false)
  const pausedRef = useRef(paused)
  pausedRef.current = paused

  const runId = run?.status === 'running' ? run.id : null
  const seedCount = run?.printed_qty ?? 0

  useEffect(() => {
    setTick(null)
    setSource(null)
    if (!runId) return
    let cancelled = false
    let timer: ReturnType<typeof setInterval> | undefined
    let es: EventSource | undefined

    const simulate = (seed: CounterTick) => {
      if (cancelled) return
      setSource('sim')
      setTick(seed)
      let cur = seed
      const perMetre = ups > 0 && repeatMm > 0 ? (1000 / repeatMm) * ups : 40
      timer = setInterval(() => {
        if (pausedRef.current) return
        const speed = Math.round((50 + Math.random() * 10) * 10) / 10
        const metres = speed / 60
        const waste = 0.05 + Math.random() * 0.05
        cur = {
          run_id: cur.run_id,
          ts: new Date().toISOString(),
          count: cur.count + Math.round(metres * (1 - waste) * perMetre),
          metres: Math.round((cur.metres + metres) * 100) / 100,
          speed_mpm: speed,
          status: 'running',
        }
        setTick(cur)
      }, 1000)
    }

    const fallbackSeed = (): CounterTick => {
      const req = ups > 0 && repeatMm > 0 ? ((seedCount / ups) * repeatMm) / 1000 : 0
      return {
        run_id: runId,
        ts: new Date().toISOString(),
        count: seedCount,
        metres: Math.round(req * 1.06 * 100) / 100,
        speed_mpm: 55,
        status: 'running',
      }
    }

    if (api.mode === 'mock') {
      api
        .get<CounterTick[] | CounterTick>(`/api/production/counter/stream?run_id=${encodeURIComponent(runId)}`)
        .then((d) => {
          const arr = Array.isArray(d) ? d : [d]
          const first = arr.find((t) => t.run_id === runId)
          simulate(first ?? fallbackSeed())
        })
        .catch(() => simulate(fallbackSeed()))
    } else {
      // EventSource cannot send headers, so the role also goes on the query string.
      const url = `${API_URL}/api/production/counter/stream?run_id=${encodeURIComponent(runId)}&role=${getRole()}`
      void backendHasRoute('GET', '/api/production/counter/stream').then((served) => {
        if (cancelled) return
        if (!served) {
          simulate(fallbackSeed()) // backend has no counter stream yet
          return
        }
        openStream(url)
      })
    }

    function openStream(url: string) {
      try {
        es = new EventSource(url)
        es.onmessage = (ev) => {
          if (pausedRef.current) return
          try {
            const t = JSON.parse(ev.data as string) as CounterTick
            setSource('sse')
            setTick(t)
          } catch {
            /* ignore malformed frame */
          }
        }
        es.onerror = () => {
          es?.close()
          es = undefined
          if (!cancelled) simulate(fallbackSeed())
        }
      } catch {
        simulate(fallbackSeed())
      }
    }

    return () => {
      cancelled = true
      if (timer) clearInterval(timer)
      es?.close()
    }
  }, [runId, ups, repeatMm, seedCount])

  return { tick, source, paused, setPaused }
}
