import {inventoryFeedback} from './inventoryFeedback.mjs'

// Saving/selecting the game and scanning its inventory are separate outcomes.
// A missing scan receipt must not turn a confirmed save into either a zero-Mod
// success or a request to repeat the import.
export function gameImportFeedback(result, language='zh-CN') {
  const en=language==='en'
  const saved=en ? 'Game imported. ' : '游戏已导入。'
  const scan=result?.mod_scan
  const object=value=>value!==null&&typeof value==='object'&&!Array.isArray(value)
  const count=value=>Number.isSafeInteger(value)&&value>=0
  const matching=object(scan)&&typeof result?.game?.game_instance_id==='string'
    && !!result.game.game_instance_id&&scan.game_instance_id===result.game.game_instance_id
  if(matching&&scan.status==='running'&&scan.queued===true&&!scan.error&&!scan.error_code){
    return {monitor:true,kind:'info',message:saved+(en
      ? 'Scanning Mods in the background; you can keep using the app.'
      : '正在后台扫描 Mod，你可以继续使用界面。')}
  }
  let state={status:'unconfirmed'}
  if(matching&&scan.status==='failed'&&scan.queued!==true){
    state={status:'failed',error_code:scan.error_code==='SCAN_DIRECTORY_UNREADABLE'?scan.error_code:undefined}
  }else if(matching&&scan.status==='completed'&&scan.queued!==true&&!scan.error&&!scan.error_code
    &&count(scan.imported)&&count(scan.detected)&&scan.imported<=scan.detected
    &&(scan.missing_roots===undefined||(Array.isArray(scan.missing_roots)&&scan.missing_roots.every(p=>typeof p==='string')))){
    state=scan
  }
  return {...inventoryFeedback(state,language),monitor:false,
    message:saved+inventoryFeedback(state,language).message}
}
