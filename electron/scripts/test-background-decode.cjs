const {spawnSync}=require('node:child_process');
if(!process.versions.electron){
  const result=spawnSync(require('electron'),[__filename],{encoding:'utf8',windowsHide:true,timeout:20000});
  process.stdout.write(result.stdout||'');process.stderr.write(result.stderr||'');
  if(result.error)throw result.error;process.exit(result.status??1);
}else{
  const {app,BrowserWindow,nativeImage}=require('electron');
  app.on('window-all-closed',()=>{});
  app.whenReady().then(async()=>{
    const fs=require('node:fs'),path=require('node:path');
    const assert=require('node:assert/strict');
    const {validateBackgroundImage}=require('../backgroundDecode');
    for(const [name,bytes] of [
      ['png',fs.readFileSync(path.join(__dirname,'../src/assets/default-wallpaper.png'))],
      ['gif',Buffer.from('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7','base64')],
      ['webp',Buffer.from('UklGRiIAAABXRUJQVlA4IBYAAAAwAQCdASoBAAEADsD+JaQAA3AAAAAA','base64')],
    ]){await validateBackgroundImage(bytes,'.'+name,BrowserWindow);console.log('PASS '+name+' actual browser decode');}
    await validateBackgroundImage(nativeImage.createFromPath(path.join(__dirname,'../src/assets/default-wallpaper.png')).toJPEG(75),'.jpg',BrowserWindow);
    console.log('PASS jpeg actual browser decode');
    await assert.rejects(validateBackgroundImage(Buffer.from('not an image'),'.png',BrowserWindow),/BACKGROUND_IMAGE_INVALID/);
    assert.equal(BrowserWindow.getAllWindows().length,0);
    console.log('PASS corrupt image rejected; hidden decode windows cleaned up');
    app.exit(0);
  }).catch(error=>{console.error(error);app.exit(1)});
}
