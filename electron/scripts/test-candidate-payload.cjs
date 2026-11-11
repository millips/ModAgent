// Run immediately after packaging each edition, before rebuilding shared dist.
const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')
const crypto = require('node:crypto')
const asar = require('@electron/asar')
const [directory, edition, candidate, backendDirectory] = process.argv.slice(2)
assert(directory && backendDirectory && candidate, 'Usage: node test-candidate-payload.cjs PACKAGE_DIR EDITION CANDIDATE BACKEND_DIR')
assert(['free','subscription'].includes(edition), 'Invalid edition')
const root = path.resolve(__dirname, '..')
const archive = path.join(path.resolve(directory), 'resources', 'app.asar')
const read = name => asar.extractFile(archive, name)
const metadata = JSON.parse(read('package.json'))
assert.equal(metadata.modagentEdition, edition)
assert.equal(metadata.modagentChannel, 'beta')
assert.equal(metadata.modagentCandidateId, candidate)
assert.equal(metadata.version, require('../package.json').version)
const marker = JSON.parse(read(path.join('dist','edition.json')))
assert.equal(marker.edition, edition)
assert.equal(marker.channel, 'beta')
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex')
let verified = 0
function compare(relative, expected) {
  assert.equal(hash(read(relative)), hash(fs.readFileSync(expected)), `Stale packaged file: ${relative}`)
  verified++
}
for (const name of ['main.js','preload.js','browserLauncher.js','browserController.js','candidateProfile.js','credentialBroker.js','shareFile.js','backgroundStore.js','backgroundDecode.js','updater.js','diagnosticExport.js']) {
  compare(name,path.join(root,name))
}
function walk(directory, visit, prefix='') {
  for(const entry of fs.readdirSync(directory,{withFileTypes:true})) {
    const relative = path.join(prefix,entry.name)
    if(entry.isDirectory()) walk(path.join(directory,entry.name),visit,relative)
    else if(entry.isFile()) visit(relative)
    else throw Error(`Unexpected file type: ${relative}`)
  }
}
walk(path.join(root,'dist'), relative => compare(path.join('dist',relative),path.join(root,'dist',relative)))
assert.equal(JSON.parse(read(path.join('node_modules','semver','package.json'))).version, '6.3.1')
let backendFiles = 0
walk(path.resolve(backendDirectory), relative => {
  assert.equal(hash(fs.readFileSync(path.join(directory,'resources','backend',relative))),hash(fs.readFileSync(path.join(backendDirectory,relative))),`Stale backend file: ${relative}`)
  backendFiles++
})
assert(backendFiles>0)
console.log(`PAYLOAD VERIFIED: ${edition}/${candidate}; ${verified} app files, ${backendFiles} backend files; metadata and semver checked`)
