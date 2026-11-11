async function validateBackgroundImage(bytes, extension, BrowserWindow) {
  const mime={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.gif':'image/gif','.webp':'image/webp'}[extension];
  if(!mime)throw Error('BACKGROUND_FORMAT_INVALID');
  const window=new BrowserWindow({show:false,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}});
  let timer;
  try{
    const decode=async()=>{
      await window.loadURL('data:text/html,<meta http-equiv="Content-Security-Policy" content="default-src %27none%27; img-src data:">');
      return window.webContents.executeJavaScript(`new Promise(resolve=>{const img=new Image();img.onload=()=>resolve(img.naturalWidth>0&&img.naturalHeight>0&&img.naturalWidth*img.naturalHeight<=64000000);img.onerror=()=>resolve(false);img.src=${JSON.stringify(`data:${mime};base64,${bytes.toString('base64')}`)}})`);
    };
    const valid=await Promise.race([decode(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('BACKGROUND_DECODE_TIMEOUT')),10000)})]);
    if(valid!==true)throw Error('BACKGROUND_IMAGE_INVALID');
  }finally{clearTimeout(timer);if(!window.isDestroyed())window.destroy();}
}
module.exports={validateBackgroundImage};
