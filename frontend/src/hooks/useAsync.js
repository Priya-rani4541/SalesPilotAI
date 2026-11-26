import { useCallback, useEffect, useRef, useState } from 'react'

// Runs an async loader and tracks loading / error / data state with a manual
// `reload`. Stale responses (from a superseded request) are discarded so rapid
// filter changes never show outdated data.
export function useAsync(loader, deps = []) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const requestId = useRef(0)

  const run = useCallback(async () => {
    const id = requestId.current + 1
    requestId.current = id
    setLoading(true)
    setError(null)
    try {
      const result = await loader()
      if (requestId.current === id) setData(result)
    } catch (err) {
      if (requestId.current === id) setError(err)
    } finally {
      if (requestId.current === id) setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    run()
    return () => {
      // Invalidate any in-flight request when the component unmounts.
      requestId.current += 1
    }
  }, [run])

  return { data, loading, error, reload: run }
}
