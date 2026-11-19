export const PDF_FILENAME = 'diagnostic_report.pdf'

export const canChoosePdfLocation = () => typeof window.showSaveFilePicker === 'function'

export function getPdfDownloadMode(userId) {
  try {
    return localStorage.getItem(`ocupanel.pdfDownload.${userId}`) === 'browser' ? 'browser' : 'choose'
  } catch {
    return 'choose'
  }
}

export function setPdfDownloadMode(userId, mode) {
  localStorage.setItem(`ocupanel.pdfDownload.${userId}`, mode)
}

export function choosePdfFile() {
  return window.showSaveFilePicker({
    id: 'ocupanel-reports',
    suggestedName: PDF_FILENAME,
    types: [{ description: 'PDF', accept: { 'application/pdf': ['.pdf'] } }]
  })
}

export async function savePdf(blob, fileHandle) {
  if (fileHandle) {
    const writable = await fileHandle.createWritable()
    try {
      await writable.write(blob)
      await writable.close()
    } catch (error) {
      await writable.abort().catch(() => {})
      throw error
    }
    return
  }

  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = PDF_FILENAME
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
