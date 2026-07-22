const crypto = require('crypto')
const fs = require('fs')
const path = require('path')

const coreAudioDir = path.join(
  __dirname, '..', 'src', 'assets', 'themes', 'technology-core', 'audio'
)
const coreExpected = {
  'cancel.mp3': '5b76ee113f3818c48a1c6280810d17952c68a0ef0f7fda2d26a484eb8056b6ed',
  'download-item-complete.mp3': 'd2afa03c6982f7085a10b1bb0099d5ec60294779fa95ee040725b025d25b3b03',
  'download-start-coin.mp3': '64934701c6083a6a888792e9fc096a40b57ce5b85b1d6298a3bceb1b0d2665ff',
  'download-start-token.mp3': '389a6179d73cbc4eaec474dd875335421839bfd1557c94316fc2061b3f2fa616',
  'error-primary.mp3': '1ed9c9f9286a86dfb8c330e59476a5e9d68b24f15a5f8c999eeedf32fe971063',
  'error-secondary.mp3': '929c3f2a11a154f309c0334fa3ff526c8a8d5cabf0de978e27482a6d822841f4',
  'install-complete.mp3': '43baa7e78170a61bd7d1d8495be05379cf8c51d2f6efe0c013102f457307812a',
  'notice.mp3': '75f0ecd94374d3959c9b9a74823088b5b52b1a3e26fcd067ebe9c4315981893f',
  'remove-primary.mp3': '27cc208cfae5a7ec5570932ff173c9e027f2f118c131a7938873e6b28f64d370',
  'remove-secondary.mp3': '07d39d965cf9ada33bf8c6183dfd25ad567f303a082f56d12d5c843325e214ec',
  'rollback.mp3': '69700216f7cac5c7f025efb69cc4eb144cb4e8c079188b71810848ee83854e2b',
  'scan.mp3': '378905cd196896702c235f666470f70a352d37a40fdbe1144504d3ae24145a79',
  'snapshot-complete.mp3': 'a6a6cb9b28881fb9b866fd78773fde99a22f9e104ab35d1c5106bdbb7e96443f',
  'startup.mp3': '3cb160abccb0b5450b1f06c024bb4119c8251700de22aaf4e85f520aa6ec2556',
  'success-coin.mp3': 'e603c1850745aba110758fb511d25912557ef6451c9b0c234300514a950d8416',
  'success-tactile.mp3': '2f281332086dfd6270e4f45a1a2df9c8a855b2d33ab670d8c05f027f2c7c4d83',
  'toggle.mp3': 'cc5891833ea49ac734889c9e275afa63050d6236c9fca7059ad641d4dacd0541',
  'ui-hover.mp3': '80e5ac75c24ebabd74145bcf7776a42bb9484138a783cc58f5ce3360012cade5',
  'ui-press.mp3': '659e52b3bf8f76c2fb4f0946d68cb21341334b36b262c94dec9eb315195ff265',
  'warning.mp3': 'a71f1396e1b22d5efd14fc9cf7d805196bd11432e3cc9f8d935ae9221a94f567',
}

const catAudioDir = path.join(
  __dirname, '..', 'src', 'assets', 'themes', 'cat', 'audio'
)
const catExpected = {
  'batch-complete.mp3': '10464ba200066bc53a000a1e8271a79320caae4c7fc8dd9d4a15161fea91ffad',
  'cancel.mp3': '5eb9e9d87b82202dc5f7b4ba261b4328890a23e828ad8fcd92bebe85e76f83ee',
  'download-complete.mp3': 'b85542be1b276d6a3761bcc39c670b353f8704df0deabc7fe485e454f58f579a',
  'download-start.mp3': '1e46ae47eb53669729f077a2bad29a3c805d30ce2ca7517fe9e5ab064082d1b5',
  'easter-meow-natural.mp3': '2f0fc1cdc3c6d825f4fba485bd17662f286482c829731d950c73626ad232359a',
  'easter-meow-soft.mp3': '8853ca70c0c71e1bb3a5040ae26a3b44c837bcf18582491fe510617ec53e7966',
  'easter-purr.mp3': '401c522f5a3bb2c0d916d795838e698a3aa6d05db38c422dd46b60c4ca6715e5',
  'error.mp3': '1de32bc92e46cefe337eb8d82e4723f5174d8b9ce62452ae40767904d4484f70',
  'install-complete.mp3': '503d92d38b1f82940b16c7b973b0ad3b6d97a10ca8837916d4cd334624f9c804',
  'install-reward.mp3': 'd81b83a8a96b06c1ca789d45e297bfc253359163e68483c5096b241b218ec096',
  'notice.mp3': 'fa3afb61a892f0d2d9603674f4e4fa8b2cd7daace2ce219dc2baf94130a7e9f2',
  'remove.mp3': 'e9511e07503793b4f64c43c6f95926e2ab2f23680b0124eb009baf1814c5635d',
  'rollback.mp3': '1560b5920041711afb44244ff7c9a0463374c0387212b0e0577515eff895d9e7',
  'scan-complete.mp3': 'b216dc64ec723ce3a8a647484d79d16ec9c0f83d91834ef81ea6148c6f237fdc',
  'scan-finish.mp3': 'e7c2ae862045c50e360dfc5ce3290fde8222f323ea6155994212911b7aeee7c8',
  'scan-start.mp3': 'cd214d73147e193c9170717ffab2550d8f39403051c9eaaf59713fbe63b5650b',
  'startup-1.mp3': '9ebf625a781cc448c035b2035282b8f5d661485c30aff12110dcf9727799f202',
  'startup-2.mp3': '71784a59a6d7e6a196091f116248aed6faca0c0168adab56037861fe9f6940d7',
  'startup-3.mp3': 'dad035361a77a25c8755aade648b7a72d6a3d983f3391ec4709755dd0c6fff26',
  'startup-4.mp3': '662eecc9ef09b182137b7f8a833ee162cd537a0c9b9073e557caf0764bd76704',
  'toggle-off.mp3': '396e9c7bd6ab1c750c6e17698bddced84f8a0f201b92c16a9f1ebfead4187998',
  'toggle-on.mp3': '5ae23cbc80e5b0c461b6597c1d46dde0053f79a0bda6898edd010e2811e87340',
  'ui-hover.mp3': 'b4e79ab7e27e230979050a6fc6f5f1c8c45f4f9896300b6d44310343a440e4ad',
  'ui-press.mp3': 'fad96c385a2a399d8988871e9d646d341c6c2bd0d16a06e5676413cc06ce4741',
  'warning.mp3': '8ea43da43d90b4397b0b15f96ec9d5dd1ef79b236df16b0f5c4fe113f5e84478',
}

const mismatches = []
const packs = [
  ['technology-core', coreAudioDir, coreExpected],
  ['cat', catAudioDir, catExpected],
]
for (const [pack, audioDir, expected] of packs) {
  for (const [name, wanted] of Object.entries(expected)) {
    const file = path.join(audioDir, name)
    if (!fs.existsSync(file)) {
      mismatches.push(`${pack}/${name}: missing`)
      continue
    }
    const actual = crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
    if (actual !== wanted) mismatches.push(`${pack}/${name}: unexpected audio revision`)
  }
}

if (mismatches.length) {
  console.error('Commercial audio verification failed:')
  mismatches.forEach(item => console.error(`- ${item}`))
  process.exit(1)
}
const verifiedCount = packs.reduce((total, pack) => total + Object.keys(pack[2]).length, 0)
console.log(`Commercial audio verified (${verifiedCount} files across ${packs.length} theme packs).`)
