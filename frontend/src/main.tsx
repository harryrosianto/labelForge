import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, Link, RouterProvider } from 'react-router-dom'

import './index.css'
import { EditorPage } from './pages/EditorPage'
import { ProjectsPage } from './pages/ProjectsPage'
import { AutolabelTab } from './pages/project/AutolabelTab'
import { ClassesTab } from './pages/project/ClassesTab'
import { ExportTab } from './pages/project/ExportTab'
import { GalleryTab } from './pages/project/GalleryTab'
import { OverviewTab } from './pages/project/OverviewTab'
import { ProjectLayout } from './pages/project/ProjectLayout'
import { UploadTab } from './pages/project/UploadTab'
import { VersionsTab } from './pages/project/VersionsTab'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 5_000, retry: 1, refetchOnWindowFocus: false } },
})

const router = createBrowserRouter([
  { path: '/', element: <ProjectsPage /> },
  {
    path: '/projects/:projectId',
    element: <ProjectLayout />,
    children: [
      { index: true, element: <OverviewTab /> },
      { path: 'classes', element: <ClassesTab /> },
      { path: 'upload', element: <UploadTab /> },
      { path: 'gallery', element: <GalleryTab /> },
      { path: 'autolabel', element: <AutolabelTab /> },
      { path: 'versions', element: <VersionsTab /> },
      { path: 'export', element: <ExportTab /> },
    ],
  },
  { path: '/projects/:projectId/annotate/:imageId', element: <EditorPage /> },
  {
    path: '*',
    element: (
      <div className="p-10 text-center">
        Halaman tidak ditemukan. <Link to="/" className="text-brand-700">Kembali</Link>
      </div>
    ),
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
