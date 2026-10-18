import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StudentView } from './apps/auto-extend/StudentView'
import { InstructorView } from './apps/auto-extend/InstructorView'
import { CSVGradebook } from './apps/csv-to-gradebook/CSVGradebook'

const queryClient = new QueryClient();

function App() {
  // In a real application, these would come from the LTI launch parameters
  const params = new URLSearchParams(window.location.search)
  const courseId = parseInt(new URLSearchParams(window.location.search).get('course_id') || '0');
  const userRole = new URLSearchParams(window.location.search).get('role') || 'student';
  const tool = params.get('tool')

  return (
    <QueryClientProvider client={queryClient}>
      {tool === 'csv-gradebook' ? (
          
          <CSVGradebook courseId={courseId}/>
        ) : (
      <div className="container mx-auto">
        {userRole === 'instructor' ? (
          <InstructorView courseId={courseId} />
        ) : (
          <StudentView courseId={courseId} />
        )}
      </div>
      )}
    </QueryClientProvider>
  )
}

export default App
