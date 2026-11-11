const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
async function storeBackground(source, directory, io = fs, validate = async () => {}) {
  const extension = path.extname(source).toLowerCase();
  if (!['.png','.jpg','.jpeg','.gif','.webp'].includes(extension)) throw Error('BACKGROUND_FORMAT_INVALID');
  const name = `bg_${Date.now()}_${crypto.randomUUID()}${extension}`;
  const destination = path.join(directory, name);
  const staging = destination + '.tmp';
  let owned = false;
  try {
    const info = await io.stat(source);
    if (!info.isFile() || info.size <= 0 || info.size > 32 * 1024 * 1024) throw Error('BACKGROUND_SIZE_INVALID');
    const bytes = await io.readFile(source);
    if (!bytes.length || bytes.length > 32 * 1024 * 1024) throw Error('BACKGROUND_SIZE_INVALID');
    await validate(bytes, extension);
    await io.mkdir(directory, {recursive:true});
    const handle = await io.open(staging, 'wx'); owned = true;
    try { await handle.writeFile(bytes); } finally { await handle.close(); }
    if (!(await io.readFile(staging)).equals(bytes)) throw Error('BACKGROUND_VERIFY_FAILED');
    await io.rename(staging, destination); owned = false;
    return name;
  } finally { if (owned) await io.unlink(staging).catch(()=>{}); }
}
module.exports = {storeBackground};
