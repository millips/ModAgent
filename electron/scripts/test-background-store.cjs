const fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const {storeBackground}=require('../backgroundStore');
(async()=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'modagent-background-'));
  try{
    const dir=path.join(root,'bg'),source=path.join(root,'chosen.png');
    await fs.mkdir(dir);await fs.writeFile(path.join(dir,'old.png'),'original');await fs.writeFile(source,'new-fixture');
    for(const stage of ['open','rename']){
      await assert.rejects(storeBackground(source,dir,{...fs,[stage]:async()=>{throw Error('disk failure')}}));
      assert.equal(await fs.readFile(path.join(dir,'old.png'),'utf8'),'original');
      assert.deepEqual(await fs.readdir(dir),['old.png']);
    }
    await assert.rejects(storeBackground(source,dir,{...fs,open:async(...args)=>{
      const handle=await fs.open(...args);
      return {writeFile:async()=>{await handle.writeFile('partial');throw Error('disk full')},close:()=>handle.close()};
    }}));
    assert.deepEqual(await fs.readdir(dir),['old.png']);
    await assert.rejects(storeBackground(source,dir,fs,async()=>{throw Error('invalid image')}));
    assert.deepEqual(await fs.readdir(dir),['old.png']);
    const name=await storeBackground(source,dir);
    assert.equal(await fs.readFile(path.join(dir,name),'utf8'),'new-fixture');
    assert.equal(await fs.readFile(path.join(dir,'old.png'),'utf8'),'original');
    await assert.rejects(storeBackground(path.join(root,'missing.png'),dir));
    await assert.rejects(storeBackground('bad.exe',dir),/FORMAT_INVALID/);
    console.log('BACKGROUND STORE PASSED: failed copy/rename preserves original; complete copy readback; missing source and extension rejection');
  }finally{await fs.rm(root,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exitCode=1});
