const fs = require('fs')
const path = require('path')

const electronDir = path.resolve(__dirname, '..')
const sourceFiles = ['main.js', 'updater.js', 'runtimeDiagnostics.js']
const failures = []

function inspect(label, content) {
  if (/\?{4,}/.test(content)) failures.push(`${label}: contains four or more consecutive question marks`)
  if (/\uFFFD/.test(content)) failures.push(`${label}: contains Unicode replacement characters`)
}

for (const relative of sourceFiles) {
  inspect(relative, fs.readFileSync(path.join(electronDir, relative), 'utf8'))
}

for (const archivePath of process.argv.slice(2)) {
  const asar = require('@electron/asar')
  for (const relative of sourceFiles) {
    try {
      inspect(`${archivePath}:${relative}`, asar.extractFile(path.resolve(archivePath), relative).toString('utf8'))
    } catch (error) {
      failures.push(`${archivePath}:${relative}: missing from app.asar (${error.message})`)
    }
  }
}

if (failures.length) {
  console.error(failures.join('\n'))
  process.exit(1)
}
console.log(`Release text verified (${sourceFiles.length} source files${process.argv.length > 2 ? ' and app.asar' : ''}).`)
