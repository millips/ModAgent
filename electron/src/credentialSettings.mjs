// Only newly typed keys enter this helper. Inherited keys remain in Electron.
export async function saveCredentialSettings(body, store) {
  for (const field of ['api_key', 'nexus_api_key', 'llm_api_key', 'tavily_api_key']) {
    if (Object.hasOwn(body, field) && /[^\x21-\x7e]/.test(String(body[field] || '').trim())) {
      throw new Error(`credential_${field === 'api_key' ? 'nexus_api_key' : field}_invalid`);
    }
  }
  if (!store) return { body, status: null };
  const updates = {};
  const mapping = { api_key: 'nexus_api_key', nexus_api_key: 'nexus_api_key', llm_api_key: 'llm_api_key',
    tavily_api_key: 'tavily_api_key', llm_endpoint: 'llm_endpoint', llm_model: 'llm_model' };
  for (const [key, target] of Object.entries(mapping)) {
    if (Object.hasOwn(body, key)) updates[target] = body[key];
  }
  const result = await store(updates);
  if (!result?.ok) throw new Error(result?.error || 'credential_save_failed');
  // The main process already applied the resolved bundle to the backend.
  // Sending a second partial route update could detach it from the key.
  return { body: Object.fromEntries(Object.entries(body).filter(([key]) => !Object.hasOwn(mapping, key))), status: result };
}
export function credentialErrorMessage(error, language) {
  const english = language === 'en';
  const fields = { credential_llm_api_key_invalid: 'LLM API Key',
    credential_nexus_api_key_invalid: 'Nexus API Key', credential_tavily_api_key_invalid: 'Tavily API Key' };
  if (fields[error?.message]) return english
    ? `${fields[error.message]} has an invalid format. Paste the key itself, without spaces, line breaks or non-ASCII characters. Existing credentials were preserved.`
    : `${fields[error.message]} 格式不正确。请粘贴密钥本身，不要包含中文、空格或换行；原凭据已保留。`;
  if (error?.message === 'credential_store_unreadable') return english
    ? 'This profile’s credential file cannot be read. It was not overwritten. Check diagnostics; do not delete the original file.'
    : '本版本的凭据文件无法读取，已停止覆盖。请查看诊断信息，不要删除原文件。';
  if (error?.message === 'credential_store_busy') return english
    ? 'The credential store is busy or cannot be locked. Close other ModAgent windows and retry; check file permissions if this persists.'
    : '凭据文件正在使用或无法锁定。请关闭其他 ModAgent 窗口后重试；持续失败请检查文件权限。';
  if (error?.message === 'credential_encryption_unavailable') return english
    ? 'Windows encrypted storage is unavailable. Nothing was saved in plaintext.'
    : 'Windows 加密存储不可用，未改用明文保存密钥。';
  if (error?.message === 'credential_endpoint_requires_key') return english
    ? 'The endpoint changed. Enter the key for this endpoint; the old key was not reused.'
    : '接口地址变了，请填写这个地址对应的密钥；没有复用旧服务的密钥。';
  if (error?.message === 'credential_backend_unavailable') return english
    ? 'Credentials were saved, but the local service did not respond. Restart the app to apply them.'
    : '密钥已保存，但本地服务未响应。请重启应用后使用。';
  return english ? 'Secure save failed. Existing credentials were preserved; try again or check diagnostics.'
    : '安全保存失败，原凭据已保留。请重试或检查诊断信息。';
}
