export async function writeClipboardText(text, clipboard, timeoutMs = 15000) {
  if (typeof text !== 'string' || !text.trim()) throw Error('COPY_EMPTY')
  if (typeof clipboard?.writeText !== 'function') throw Error('COPY_UNAVAILABLE')
  let timer
  try {
    await Promise.race([
      Promise.resolve().then(() => clipboard.writeText(text)),
      new Promise((_, reject) => {timer=setTimeout(()=>reject(Error('COPY_TIMEOUT')),timeoutMs)}),
    ])
  } catch (error) {
    throw Error(error?.message === 'COPY_TIMEOUT' ? 'COPY_TIMEOUT' : 'COPY_FAILED')
  } finally {clearTimeout(timer)}
}

export function clipboardFailure(error, language) {
  const en=language==='en'
  if(error?.message==='COPY_TIMEOUT')return en
    ? '[COPY_TIMEOUT] Copying was not confirmed. The clipboard may update later; check it before pasting. You can select the text and copy manually.'
    : '[COPY_TIMEOUT] 尚未确认复制成功，剪贴板可能稍后更新，粘贴前请核对。也可选中文本手动复制。'
  if(error?.message==='COPY_EMPTY')return en
    ? '[COPY_EMPTY] There is no text to copy. Fill in this field on the submission page.'
    : '[COPY_EMPTY] 没有可复制的内容，请在投稿页面补填此项。'
  return en ? '[COPY_FAILED] Could not access the clipboard. Select the text and copy manually.'
    : '[COPY_FAILED] 无法访问剪贴板，请选中文本手动复制。'
}
