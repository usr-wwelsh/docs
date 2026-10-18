document.querySelectorAll('#try-searching-for ~ ul:first-of-type li > code').forEach((code) => {
  const button = document.createElement('button')
  button.type = 'button'
  button.className = 'copy-badge'
  button.textContent = 'copy'
  button.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(code.textContent)
      button.textContent = 'copied'
    } catch {
      button.textContent = 'failed'
    }
    setTimeout(() => { button.textContent = 'copy' }, 1500)
  })
  code.after(button)
})
