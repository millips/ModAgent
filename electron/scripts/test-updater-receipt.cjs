const assert=require('node:assert/strict'),Module=require('node:module');
const load=Module._load,timeout=global.setTimeout,resources=process.resourcesPath;
const handlers={};let response,current='1.6.0';
const updater={on(){},checkForUpdates:async()=>response};
Module._load=function(name,...args){
  if(name==='electron')return {app:{isPackaged:true,getVersion:()=>current},dialog:{},ipcMain:{handle:(name,fn)=>handlers[name]=fn}};
  if(name==='electron-log')return {transports:{file:{}}};
  if(name==='electron-updater')return {autoUpdater:updater};
  if(name==='fs')return {...load.call(this,name,...args),existsSync:()=>true};
  return load.call(this,name,...args);
};
global.setTimeout=()=>0;process.resourcesPath='fixture-resources';
(async()=>{
  try{
    require('../updater').setupAutoUpdater({identity:{},diagnostics:{logsDir:'fixture-logs',logger:{info(){},error(){}}},getMainWindow:()=>null});
    for(const [version,available] of [['1.7.0',true],['1.6.0',false],['1.5.0',false]]){
      response={updateInfo:{version}};
      assert.deepEqual(await handlers['check-for-app-update'](),{ok:true,version,available,currentVersion:'1.6.0'});
    }
    for(const [installed,latest,available] of [['1.7.0-beta.2','1.7.0-beta.10',true],['1.7.0-beta.10','1.7.0-beta.2',false],['1.7.0-beta.10','1.7.0',true],['1.7.0','1.7.0-rc.1',false]]){
      current=installed;response={updateInfo:{version:latest}};
      assert.equal((await handlers['check-for-app-update']()).available,available);
    }
    for(const invalid of [null,{}, {updateInfo:{version:'bad'}},{updateInfo:{version:'1.7.0-beta.01'}}]){
      response=invalid;assert.equal((await handlers['check-for-app-update']()).ok,false);
    }
    console.log('UPDATER RECEIPT PASSED: actual handler distinguishes newer/current/older and rejects missing results without networking');
  }finally{Module._load=load;global.setTimeout=timeout;if(resources===undefined)delete process.resourcesPath;else process.resourcesPath=resources;}
})().catch(error=>{console.error(error);process.exitCode=1});
