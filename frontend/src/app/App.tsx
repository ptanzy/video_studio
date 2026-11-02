import { useEffect } from 'react'
import { loadCatalog } from '../api/client'
import { Shell } from '../components/Shell'
import { ImportPage } from '../features/import/ImportPage'
import { ReviewPage } from '../features/review/ReviewPage'
import { FuturePage } from '../features/future/FuturePage'
import { useStudio } from './state'

export const App = () => {
  const { state, dispatch } = useStudio()
  useEffect(() => {
    const controller = new AbortController()
    loadCatalog(controller.signal)
      .then(() => dispatch({ type: 'backend-loaded', albums: [] }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) dispatch({ type: 'backend-error', message: `Import backend unavailable. ${error instanceof Error ? error.message : ''}` })
      })
    return () => controller.abort()
  }, [dispatch])

  return <Shell>
    {state.route === 'import' && <ImportPage />}
    {state.route === 'review' && <ReviewPage />}
    {state.route === 'metadata' && <FuturePage kind="metadata" />}
    {state.route === 'render' && <FuturePage kind="render" />}
  </Shell>
}
