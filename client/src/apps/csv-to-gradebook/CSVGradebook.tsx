
import { useState } from 'react';

type GradeRow = {
    studentId: string;
    studentEmail: string;
    score: string;
}


function parseCsv(text: string): GradeRow[] {
    const lines = text.trim().split(/\r?\n/).filter(Boolean)
  
    if (lines.length === 0) return []
  
    const parseLine = (line: string): string[] => {
      const values: string[] = []
      let value = ''
      let quoted = false
  
      for (let i = 0; i < line.length; i++) {
        const char = line[i]
  
        if (char === '"' && line[i + 1] === '"' && quoted) {
          value += '"'
          i++
        } else if (char === '"') {
          quoted = !quoted
        } else if (char === ',' && !quoted) {
          values.push(value.trim())
          value = ''
        } else {
          value += char
        }
      }
  
      values.push(value.trim())
      return values
    }
  
    const firstRow = parseLine(lines[0])
  
    const headers = firstRow.map((value) =>
        value.toLowerCase().trim().replace(/[\s-]+/g, '_'),
    )

    const idIndex = headers.findIndex((value) =>
        /^(ufid|student_id|studentid|id)$/.test(value),
    )
  
    const emailIndex = headers.findIndex((value) =>
      /^(email|student_email|studentemail|email_address)$/.test(value),
    )
  
    const scoreIndex = headers.findIndex((value) =>
      /^(score|grade|points|mark|points_earned)$/.test(value),
    )
  
    const hasHeader =
      idIndex !== -1 || emailIndex !== -1 || scoreIndex !== -1
  
    const dataLines = hasHeader ? lines.slice(1) : lines
  
    // Without headers, assume the first column is an identifier
    // and the second column is the score.
    const identifierIndex = 0
    const fallbackScoreIndex = 1
  
    return dataLines.map((line) => {
      const columns = parseLine(line)
  
      const studentId =
        idIndex !== -1
          ? columns[idIndex] ?? ''
          : !hasHeader && /^\d+$/.test(columns[identifierIndex] ?? '')
            ? columns[identifierIndex]
            : ''
  
      const studentEmail =
        emailIndex !== -1
          ? columns[emailIndex] ?? ''
          : !hasHeader && (columns[identifierIndex] ?? '').includes('@')
            ? columns[identifierIndex]
            : ''
  
      const score =
        scoreIndex !== -1
          ? columns[scoreIndex] ?? ''
          : columns[fallbackScoreIndex] ?? ''
  
      return { studentId, studentEmail, score }
    })
  }
  

export function CSVGradebook(){
    const [csvText, setCsvText] = useState('');
    const [error, setError] = useState('');
    const rows = parseCsv(csvText);

    async function handleFile(file?: File) {
        if (!file) return;

        if(!file.name.endsWith('.csv')) {
            setError('Please upload a CSV file.');
            return;
        }

        setError('');
        setCsvText(await file.text());
    }

    return (
        <main className="mx-auto max-w-4xl space-y-8 p-8">
            <h1 className="text-3xl font-bold">CSV to Gradebook</h1>
            <p className="text-gray-700">
                Upload a CSV file with student identifiers and grades.
            </p>

            <div className="space-y-4">
                <label htmlFor="csv-upload" className="block text-sm font-medium text-gray-700">
                    Upload CSV File
                </label>
                <input
                    type="file"
                    id="csv-upload"
                    accept=".csv"
                    onChange={(e) => handleFile(e.target.files?.[0])}
                />
            </div>

            <div>
                <label htmlFor="csv-data" className="mb-2 block font-semibold">
                    Or Paste CSV data
                </label>
                <textarea
                    id="csv-data"
                    rows={6}
                    value={csvText}
                    onChange={(e) =>{
                        setCsvText(e.target.value)
                        setError('')
                    } }
                    placeholder={'student_id,email,grade\n12345678,jane@ufl.edu,92'}
                    className="w-full rounded-lg border border-gray-300 p-3 font-mono text-sm"
                  />
            </div>

            {error && <p role='alert' className="text-red-600">{error}</p>}

            <h2 className="text-2xl font-bold">Parsed grades</h2>
            <table className="w-full table-auto border-collapse border border-gray-300">
                <thead>
                    <tr className="bg-gray-100">
                        <th className="border border-gray-300 px-4 py-2">Student ID</th>
                        <th className="border border-gray-300 px-4 py-2">Email</th>
                        <th className="border border-gray-300 px-4 py-2">Grade</th>
                    </tr>
                </thead>
                <tbody>
                    {rows.map((row, index) => (
                        <tr key={index} className="border-b">
                            <td className="border border-gray-300 px-4 py-2">{row.studentId}</td>
                            <td className="border border-gray-300 px-4 py-2">{row.studentEmail}</td>
                            <td className="border border-gray-300 px-4 py-2">{row.score}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
            </main>
    )

}