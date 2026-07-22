const $ = s => document.querySelector(s)
const ctx = new (window.AudioContext || window.webkitAudioContext)()
const buffers = new Map(), assets = new Map()
const transientCache = new Map()
let currentEvent = 'press', currentFeel = 'precise', soundVersion = 'v1', versionBanks = null
let pressStarted=0,holdTimer=null,pressHandled=false
let comboCount=0,lastComboAt=0,comboTimer=null,animationRun=0
const events = { startup: [], hover: [], press: [], downloadStart: [], downloadComplete: [], install: [], success: [], notice: [], remove: [], snapshot: [], rollback: [], warning: [], error: [], destructive: [], cancel: [], enable: [], disable: [], scanStart: [], scanComplete: [], batchComplete: [] }

const params = { volume:72, rate:100, jitter:0, duration:420, depth:8, glow:65, particle:16 }

const V2_EVENT_MAP = {
  startup: [['V2_startup.wav', 0, 100]],
  hover: [['V2_hover.wav', 0, 50]],
  press: [['V2_press.wav', 0, 100]],
  downloadStart: [['V2_download_start_coin.wav', 0, 100], ['V2_download_start_token.wav', 0, 100]],
  downloadComplete: [['V2_download_complete.wav', 0, 100]],
  install: [['V2_install.wav', 0, 100]],
  success: [['V2_success_tactile.wav', 0, 82], ['V2_success_coin.wav', 150, 48]],
  notice: [['V2_notice.wav', 0, 75]],
  remove: [['V2_remove_primary.wav', 0, 72], ['V2_remove_secondary.wav', 110, 56]],
  snapshot: [['V2_snapshot.wav', 0, 100]],
  rollback: [['V2_rollback.wav', 0, 100]],
  warning: [['V2_warning.wav', 0, 25]],
  error: [['V2_error_primary.wav', 0, 88], ['V2_error_secondary.wav', 90, 62]],
  destructive: [['V2_warning.wav', 0, 20, 1.4]],
  cancel: [['V2_cancel.wav', 0, 100]],
  enable: [['V2_toggle.wav', 0, 200]],
  disable: [['V2_toggle.wav', 0, 200]],
  scanStart: [['V2_scan.wav', 0, 100]],
  scanComplete: [['V2_notice.wav', 0, 75]],
}



const V21_EVENT_MAP = {
  startup: [['V2_21_startup.wav', 0, 100]],
  downloadStart: [['V2_21_download_start_coin.wav', 0, 100], ['V2_21_download_start_token.wav', 0, 100]],
  downloadComplete: [['V2_21_download_complete.wav', 0, 100]],
  install: [['V2_21_install.wav', 0, 100]],
  success: [['V2_21_success_tactile.wav', 0, 82], ['V2_21_success_coin.wav', 150, 48]],
}

const PAID_EVENT_MAP = {
  startup: [['商用 启动', 0, 100]],
  hover: [['商用An_extremely', 0, 50]],
  press: [['商用-按压', 0, 50]],
  downloadStart: [['商用-下载开始1', 0, 100], ['商用-下载开始2', 90, 100]],
  downloadComplete: [['商用-下载完成', 0, 100]],
  install: [['商用-安装开始', 0, 100]],
  success: [['商用-安装完成A_', 0, 82], ['商用-安装完成奖励', 150, 48]],
  notice: [['商用-轻提示', 0, 75]],
  remove: [['商用-卸载Software', 0, 72], ['商用 -卸载收尾', 110, 50]],
  snapshot: [['商用-快照保存', 0, 100]],
  rollback: [['商用-回滚', 0, 100]],
  warning: [['商用-警告', 0, 25]],
  destructive: [['商用-警告', 0, 20, 1.4]],
  cancel: [['商用 取消', 0, 100, 1, .45]],
  enable: [['商用-启用', 0, 200]],
  disable: [['商用-启用', 0, 200]],
  scanStart: [['商用扫描', 0, 100]],
  scanComplete: [['商用-轻提示', 0, 75]],
  error: [['商用 失败', 0, 88], ['商用-失败收尾', 90, 62]],
}

const cloneEventBank = bank => Object.fromEntries(Object.entries(bank).map(([key, layers]) => [key, layers.map(layer => ({...layer}))]))

function buildV2Bank() {
  const byName = name => [...assets.values()].find(asset => asset.name === name)
  const bank = Object.fromEntries(Object.keys(events).map(key => [key, []]))
  Object.entries(V2_EVENT_MAP).forEach(([event, specs]) => {
    bank[event] = specs.map(([name, delay, gain, rate = 1]) => {
      const asset = byName(name)
      return asset ? { path: asset.path, delay, gain, rate } : null
    }).filter(Boolean)
  })
  return bank
}


function buildV21Bank(v2Bank) {
  const bank = cloneEventBank(v2Bank)
  const byName = name => [...assets.values()].find(asset => asset.name === name)
  Object.entries(V21_EVENT_MAP).forEach(([event, specs]) => {
    bank[event] = specs.map(([name, delay, gain, rate = 1]) => {
      const asset = byName(name)
      return asset ? { path: asset.path, delay, gain, rate } : null
    }).filter(Boolean)
  })
  return bank
}

function buildPaidBank() {
  const bank = Object.fromEntries(Object.keys(events).map(key => [key, []]))
  const paidAssets = [...assets.values()].filter(asset => asset.path.includes('FeedbackLab_商用候选'))
  const byPart = part =>
    paidAssets.find(asset => asset.name.toLowerCase().includes(part.toLowerCase())) ||
    [...assets.values()].find(asset => asset.name.toLowerCase().includes(part.toLowerCase()))
  Object.entries(PAID_EVENT_MAP).forEach(([event, specs]) => {
    bank[event] = specs.map(([part, delay, gain, rate = 1, duration]) => {
      const asset = byPart(part)
      return asset ? { path: asset.path, delay, gain, rate, duration } : null
    }).filter(Boolean)
  })
  return bank
}

function setSoundVersion(version) {
  if (!versionBanks || !versionBanks[version]) return
  soundVersion = version
  const selected = cloneEventBank(versionBanks[version])
  Object.keys(events).forEach(key => { events[key] = selected[key] || [] })
  $('#soundV1').classList.toggle('active', version === 'v1')
  $('#soundV2').classList.toggle('active', version === 'v2')
  $('#soundV21').classList.toggle('active', version === 'v21')
  $('#soundPaid').classList.toggle('active', version === 'paid')
  document.body.dataset.soundVersion = version
  const labels = { v1: 'V1 current sound pack enabled', v2: 'V2 original sound pack enabled', v21: 'V2.1 closer sound pack enabled', paid: 'PAID commercial candidates enabled · complete event set mapped' }
  $('#audioState').textContent = labels[version] || labels.v1
  renderLayers()
}

const audioExt = name => ({mp3:'audio/mpeg',wav:'audio/wav',ogg:'audio/ogg',m4a:'audio/mp4',flac:'audio/flac'})[name.split('.').pop().toLowerCase()] || 'audio/mpeg'

async function decodeAsset(asset, picked=false) {
  if (buffers.has(asset.path)) return buffers.get(asset.path)
  const b64 = await (picked ? window.feedbackLab.readPickedAudio(asset.path) : window.feedbackLab.readAudio(asset.path))
  if (!b64) throw new Error('无法读取音频')
  const raw = Uint8Array.from(atob(b64), c => c.charCodeAt(0)).buffer
  const buffer = await ctx.decodeAudioData(raw)
  buffers.set(asset.path, buffer)
  return buffer
}

async function play(asset, options={}) {
  await ctx.resume(); const buffer = await decodeAsset(asset, asset.picked)
  const source = ctx.createBufferSource(), gain = ctx.createGain()
  source.buffer = buffer
  const jitter = params.jitter ? (Math.random()-.5)*(params.jitter/100) : 0
  source.playbackRate.value = (options.rate ?? params.rate/100) + jitter
  gain.gain.value = (options.gain ?? 1) * params.volume/100
  source.connect(gain).connect(ctx.destination)
  const when = ctx.currentTime + (options.delay || 0)/1000
  if (options.duration) source.start(when, options.offset || 0, options.duration)
  else source.start(when, options.offset || 0)
  pulseMeter(); return source
}

function friendly(name){return name.replace(/-?\d{13,}/g,'').replace(/[_#-]+/g,' ').replace(/\.\w+$/,'').trim()}
function renderAssets(filter='') {
  const list = [...assets.values()].filter(a => a.name.toLowerCase().includes(filter.toLowerCase()))
  $('#assetCount').textContent = list.length
  $('#assetList').innerHTML = list.map((a,i)=>`<div class="asset" data-path="${encodeURIComponent(a.path)}"><button class="play">▶</button><div><div class="asset-name" title="${a.name}">${friendly(a.name)}</div><div class="asset-meta">${(a.size/1024).toFixed(1)} KB · MP3</div></div><button class="add" title="加入当前事件">＋</button></div>`).join('')
  document.querySelectorAll('.asset').forEach(row=>{
    const asset=assets.get(decodeURIComponent(row.dataset.path))
    row.querySelector('.play').onclick=()=>play(asset)
    row.querySelector('.add').onclick=()=>{events[currentEvent].push({path:asset.path,delay:events[currentEvent].length*90,gain:100,rate:1});renderLayers()}
  })
}

function renderLayers(){
  const layers=events[currentEvent]
  if(currentEvent==='batchComplete'){$('#layers').innerHTML='<div class="empty">自动取“安装”音效最强 140ms 片段轮奏，并以“安装完成”组合收尾</div>';return}
  $('#layers').innerHTML=layers.length?layers.map((l,i)=>{const a=assets.get(l.path);return `<div class="layer" data-i="${i}"><span class="layer-index">L${String(i+1).padStart(2,'0')}</span><span class="layer-name">${friendly(a?.name||'missing')}</span><label><input class="delay" type="range" min="0" max="1000" value="${l.delay}"><output>${l.delay}ms</output></label><label><input class="gain" type="range" min="0" max="120" value="${l.gain}"><output>${l.gain}%</output></label><label><input class="layer-rate" type="range" min="60" max="160" value="${Math.round((l.rate||1)*100)}"><output>${(l.rate||1).toFixed(2)}×</output></label><button class="del">×</button></div>`}).join(''):'<div class="empty">从左侧素材库点击 ＋ 添加声音层</div>'
  document.querySelectorAll('.layer').forEach(row=>{const i=+row.dataset.i,l=layers[i];const d=row.querySelector('.delay'),g=row.querySelector('.gain'),r=row.querySelector('.layer-rate');d.oninput=()=>{l.delay=+d.value;d.nextElementSibling.value=l.delay+'ms'};g.oninput=()=>{l.gain=+g.value;g.nextElementSibling.value=l.gain+'%'};r.oninput=()=>{l.rate=+r.value/100;r.nextElementSibling.value=l.rate.toFixed(2)+'×'};row.querySelector('.del').onclick=()=>{layers.splice(i,1);renderLayers()}})
}

async function strongestWindow(asset, seconds=.14){
  if(transientCache.has(asset.path))return transientCache.get(asset.path)
  const b=await decodeAsset(asset,asset.picked),d=b.getChannelData(0),size=Math.max(1,Math.floor(seconds*b.sampleRate)),step=Math.max(1,Math.floor(size/8));let best=0,bestEnergy=-1
  for(let i=0;i+size<d.length;i+=step){let e=0;for(let j=i;j<i+size;j+=8)e+=d[j]*d[j];if(e>bestEnergy){bestEnergy=e;best=i}}
  const result={offset:best/b.sampleRate,duration:Math.min(seconds,b.duration-best/b.sampleRate)};transientCache.set(asset.path,result);return result
}
async function playBatch(){
  const amount=Math.max(1,Math.min(999,+$('#batchCount').value||1)),plays=amount<=6?amount:Math.min(14,Math.ceil(4+Math.log2(amount)*2))
  const installLayer=events.install[0],asset=installLayer&&assets.get(installLayer.path);if(!asset)return
  const cut=await strongestWindow(asset,.14);let elapsed=0
  for(let i=0;i<plays;i++){const progress=plays===1?1:i/(plays-1),gap=130-progress*65;play(asset,{delay:elapsed,gain:Math.max(.42,.82-Math.max(0,plays-6)*.025),rate:1,offset:cut.offset,duration:cut.duration});elapsed+=gap}
  const finishDelay=elapsed+170;events.success.forEach(l=>{const a=assets.get(l.path);if(a)play(a,{delay:finishDelay+l.delay,gain:l.gain/100,rate:l.rate||1})});animate()
}
function playCurrent(){if(currentEvent==='batchComplete'){playBatch();return}events[currentEvent].forEach(l=>{const a=assets.get(l.path);if(a)play(a,{delay:l.delay,gain:l.gain/100,rate:l.rate||1,duration:l.duration})});animate()}
function setVisualVariant(){
  const space=$('#stageSpace'),hero=$('#heroButton'),label=hero.querySelector('.label')
  const variants=['button-standard','button-slot','button-seal','button-dial','button-danger','button-scan','button-reward']
  const variant={install:'button-slot',snapshot:'button-seal',rollback:'button-dial',destructive:'button-danger',warning:'button-danger',error:'button-danger',scanStart:'button-scan',scanComplete:'button-scan',downloadStart:'button-reward',downloadComplete:'button-reward',success:'button-reward',batchComplete:'button-reward'}[currentEvent]||'button-standard'
  space.classList.remove(...variants);space.classList.add(variant)
  label.textContent={install:'INSERT MODULE',snapshot:'SEAL STATE',rollback:'REWIND',destructive:'HOLD TO CONFIRM',warning:'CAUTION',scanStart:'INITIATE SCAN',scanComplete:'SCAN COMPLETE',downloadStart:'ACQUIRE',downloadComplete:'RECEIVED',success:'LOCKED',batchComplete:'BATCH COMMIT'}[currentEvent]||'PRESS TO TEST'
}
function beginPress(e){
  const hero=$('#heroButton');pressStarted=performance.now();pressHandled=false;hero.classList.remove('is-release','is-rejected');hero.classList.add('is-pressed');if(Number.isFinite(e.pointerId))hero.setPointerCapture?.(e.pointerId)
  if(currentEvent==='destructive'){
    hero.querySelector('.label').textContent='KEEP HOLDING'
    holdTimer=setTimeout(()=>{hero.classList.add('is-held');hero.querySelector('.label').textContent='ARMED'},700)
  }else holdTimer=setTimeout(()=>hero.classList.add('is-held'),320)
}
function endPress(e,cancelled=false){
  const hero=$('#heroButton');if(!hero.classList.contains('is-pressed'))return
  clearTimeout(holdTimer);const held=performance.now()-pressStarted;hero.classList.remove('is-pressed','is-held');hero.classList.add('is-release');setTimeout(()=>hero.classList.remove('is-release'),420)
  if(!cancelled){
    if(currentEvent==='destructive'&&held<700){hero.classList.add('is-rejected');hero.querySelector('.label').textContent='HOLD REQUIRED';setTimeout(()=>{hero.classList.remove('is-rejected');setVisualVariant()},520)}
    else{pressHandled=true;playCurrent();setTimeout(setVisualVariant,80)}
  }else setVisualVariant()
  try{if(Number.isFinite(e.pointerId))hero.releasePointerCapture?.(e.pointerId)}catch{}
}
function seedResultShape(result){
  const blob=()=>`${42+Math.round(Math.random()*24)}% ${42+Math.round(Math.random()*24)}% ${42+Math.round(Math.random()*24)}% ${42+Math.round(Math.random()*24)}% / ${42+Math.round(Math.random()*24)}% ${42+Math.round(Math.random()*24)}% ${42+Math.round(Math.random()*24)}% ${42+Math.round(Math.random()*24)}%`
  result.style.setProperty('--shape-a',blob());result.style.setProperty('--shape-b',blob());result.style.setProperty('--shape-c',blob())
  const x=Math.random()*34-17,y=Math.random()*28-14,rot=Math.random()*70-35,skew=Math.random()*14-7
  result.style.setProperty('--drift-x',x.toFixed(1)+'px');result.style.setProperty('--drift-y',y.toFixed(1)+'px');result.style.setProperty('--start-x',(-x*.45).toFixed(1)+'px');result.style.setProperty('--start-y',(-y*.45).toFixed(1)+'px');result.style.setProperty('--settle-x',(x*.35).toFixed(1)+'px');result.style.setProperty('--settle-y',(-y*.25).toFixed(1)+'px')
  result.style.setProperty('--ring-rot',rot.toFixed(1)+'deg');result.style.setProperty('--start-rot',(-rot*.55).toFixed(1)+'deg');result.style.setProperty('--settle-rot',(rot*.25).toFixed(1)+'deg');result.style.setProperty('--ring-skew',skew.toFixed(1)+'deg');result.style.setProperty('--reverse-skew',(-skew*.6).toFixed(1)+'deg')
}
function resetCombo(animate=true){
  const space=$('#stageSpace');clearTimeout(comboTimer)
  if(animate&&comboCount){space.classList.add('combo-decay');setTimeout(()=>{comboCount=0;space.classList.remove('combo-active','combo-peak','combo-decay')},520)}
  else{comboCount=0;space.classList.remove('combo-active','combo-peak','combo-decay')}
}
function registerCombo(){
  const eligible=['downloadStart','downloadComplete','install','success','remove','snapshot','rollback','enable','disable','scanStart','scanComplete','batchComplete'].includes(currentEvent)
  if(['error','warning','destructive','cancel'].includes(currentEvent)){resetCombo();return{count:0,peak:false}}
  if(!eligible)return{count:0,peak:false}
  const now=performance.now();comboCount=now-lastComboAt<1250?comboCount+1:1;lastComboAt=now
  const peak=comboCount===3||comboCount===5||comboCount===10||(comboCount>10&&comboCount%5===0),space=$('#stageSpace'),combo=$('#comboFeedback')
  const power=Math.min(1,.18+comboCount*.075);combo.querySelector('span').textContent=comboCount;space.style.setProperty('--combo-power',power.toFixed(2));space.style.setProperty('--combo-glow',(42+48*power).toFixed(1)+'px');space.classList.add('combo-active');space.classList.toggle('combo-peak',peak)
  clearTimeout(comboTimer);comboTimer=setTimeout(()=>resetCombo(true),1550)
  return{count:comboCount,peak}
}
function animate(){
  const run=++animationRun,comboState=registerCombo()
  const hero=$('#heroButton'),space=$('#stageSpace'),result=$('#resultFeedback'),fxClasses=['fx-install','fx-snapshot','fx-batch','fx-scan','fx-rollback','result-success','result-error','result-warning','result-cancel','result-enable','result-disable','result-notice']
  const eventFx={install:'fx-install',snapshot:'fx-snapshot',batchComplete:'fx-batch',scanStart:'fx-scan',rollback:'fx-rollback'}[currentEvent]
  const resultFx={success:'result-success',downloadComplete:'result-success',scanComplete:'result-success',batchComplete:'result-success',error:'result-error',warning:'result-warning',destructive:'result-warning',cancel:'result-cancel',remove:'result-cancel',enable:'result-enable',disable:'result-disable',notice:'result-notice'}[currentEvent]
  const resultText={success:'CONFIRMED',downloadComplete:'RECEIVED',scanComplete:'CLEAR',batchComplete:'COMMITTED',error:'FAILED',warning:'CAUTION',destructive:'AUTHORIZED',cancel:'CANCELLED',remove:'REMOVED',enable:'ONLINE',disable:'OFFLINE',notice:'NOTICE'}[currentEvent]
  hero.style.setProperty('--pressScale',1-params.depth/100);hero.style.setProperty('--glowSize',(25+params.glow)+'px');hero.style.transitionDuration=params.duration+'ms'
  hero.classList.remove('trigger');space.classList.remove(...fxClasses);void space.offsetWidth
  if(eventFx)space.classList.add(eventFx);else hero.classList.add('trigger')
  if(resultFx){result.querySelector('span').textContent=resultText;if(resultFx==='result-success')seedResultShape(result);space.classList.add(resultFx)}
  const lifetime=currentEvent==='rollback'?950:eventFx?1500:params.duration;setTimeout(()=>{if(run!==animationRun)return;hero.classList.remove('trigger');space.classList.remove(...fxClasses)},lifetime)
  const baseParticles=currentEvent==='snapshot'?Math.ceil(params.particle*.35):currentEvent==='install'?Math.ceil(params.particle*.55):currentEvent==='batchComplete'?Math.ceil(params.particle*1.5):params.particle
  const particleCount=Math.min(comboState.peak?40:30,Math.ceil(baseParticles*(1+Math.min(comboState.count,6)*.1)))
  const palette=currentEvent==='destructive'||currentEvent==='warning'?['#ff355f','#ffb02e','#fff2cf']:currentEvent==='rollback'?['#b06cff','#45d9ff','#ffffff']:['#57f4ff','#8f7cff','#d8ffff']
  $('#particles').innerHTML='';for(let i=0;i<particleCount;i++){const p=document.createElement('i');p.className='particle';const angle=Math.random()*Math.PI*2,dist=65+Math.random()*(175+Math.min(comboState.count,6)*8),size=5+Math.random()*5+(comboState.peak?3:Math.min(comboState.count,5)*.35);p.style.setProperty('--x',Math.cos(angle)*dist+'px');p.style.setProperty('--y',Math.sin(angle)*dist+'px');p.style.setProperty('--dur',Math.max(360,params.duration)/1000+'s');p.style.setProperty('--size',size+'px');p.style.setProperty('--color',palette[i%palette.length]);$('#particles').appendChild(p)}
}
function pulseMeter(){$('#meterFill').style.width='100%';setTimeout(()=>$('#meterFill').style.width='0%',120)}

async function init(){
  const files=await window.feedbackLab.listAudio();files.forEach(a=>assets.set(a.path,a));renderAssets()
  const saved=localStorage.getItem('modagent-feedback-lab');let savedData=null;if(saved){try{savedData=JSON.parse(saved);Object.assign(params,savedData.params||{});Object.keys(events).forEach(k=>events[k]=savedData.events?.[k]||events[k]);if(savedData.batchCount)$('#batchCount').value=savedData.batchCount;syncControls()}catch{}}
  else {
    const find=part=>files.find(a=>a.name.toLowerCase().includes(part.toLowerCase()))
    const put=(event,parts)=>parts.forEach(([part,delay,gain])=>{const a=find(part);if(a)events[event].push({path:a.path,delay,gain})})
    put('hover', [['悬浮',0,45]])
    put('press', [['A_single_short',0,82]])
    put('install', [['裁切 保留右侧',0,100]])
    put('success', [['A_compact_tactile',0,82],['arcade_coin',150,48]])
    put('remove', [['charging_handle',0,72],['A_short_premium_down',110,56]])
    put('snapshot', [['A_futuristic_system',0,70],['A_premium_analog',120,50]])
  }
  if (!savedData || savedData.schemaVersion < 7) {
    const find=part=>files.find(a=>a.name.toLowerCase().includes(part.toLowerCase()))
    const layer=(part,delay,gain,rate=1)=>{const a=find(part);return a?{path:a.path,delay,gain,rate}:null}
    const fill=(event,layers,force=false)=>{if(force||!savedData||!savedData.events?.[event]?.length)events[event]=layers.filter(Boolean)}
    fill('install',[layer('裁切 保留右侧',0,100)])
    fill('startup',[layer('启动音效',0,100)])
    fill('downloadStart',[layer('universfield-coin-drop',0,120),layer('token_dispenser',0,120)])
    fill('downloadComplete',[layer('可能用作下载完成',0,100)])
    fill('success',[layer('A_compact_tactile',0,82),layer('arcade_coin',150,48)])
    fill('notice',[layer('bling-Soft',0,75)])
    fill('rollback',[layer('A_futuristic_system',0,100)])
    fill('snapshot',[layer('snapshot_#4',0,100)])
    fill('press',[layer('点击-UI_sound',0,100)],true)
    fill('warning',[layer('warning-',0,100)])
    fill('error',[layer('失败set_fail',0,88),layer('SND_037',90,62)])
    fill('destructive',[layer('warning-',0,20,1.4)],true)
    fill('cancel',[layer('Cancel_button',0,100)])
    fill('enable',[layer('ban and unban',0,100)])
    fill('disable',[layer('ban and unban',0,100)])
    fill('scanStart',[layer('scan-',0,100)])
    fill('scanComplete',[layer('bling-Soft',0,75)])
    params.rate=100
    Object.entries(events).forEach(([event,layers])=>layers.forEach(l=>{if(event!=='destructive')l.rate=1}))
  }
  const v2Bank = buildV2Bank()
  versionBanks = { v1: cloneEventBank(events), v2: v2Bank, v21: buildV21Bank(v2Bank), paid: buildPaidBank() }
  setSoundVersion('v1')
  setVisualVariant();renderLayers()
  $('#audioState').textContent=`${files.length} 个素材已载入`
}
function syncControls(){Object.keys(params).forEach(k=>{const el=$('#'+k);if(el)el.value=params[k]});updateOutputs()}
function updateOutputs(){$('#volumeOut').value=params.volume+'%';$('#rateOut').value=(params.rate/100).toFixed(2)+'×';$('#jitterOut').value=params.jitter+'%';$('#durationOut').value=params.duration+'ms';$('#depthOut').value=params.depth+'%';$('#glowOut').value=params.glow+'%';$('#particleOut').value=params.particle}

document.querySelectorAll('#eventTabs button').forEach(b=>b.onclick=()=>{document.querySelector('#eventTabs .active').classList.remove('active');b.classList.add('active');currentEvent=b.dataset.event;$('#batchCountWrap').classList.toggle('visible',currentEvent==='batchComplete');setVisualVariant();renderLayers()})
document.querySelectorAll('.feel-grid button').forEach(b=>b.onclick=()=>{document.querySelector('.feel-grid .active').classList.remove('active');b.classList.add('active');currentFeel=b.dataset.feel;const presets={precise:{duration:420,depth:8,glow:65},heavy:{duration:650,depth:12,glow:45},elastic:{duration:520,depth:15,glow:75},glitch:{duration:260,depth:5,glow:100}};Object.assign(params,presets[currentFeel]);syncControls()})
;['volume','rate','jitter','duration','depth','glow','particle'].forEach(k=>$('#'+k).oninput=e=>{params[k]=+e.target.value;updateOutputs()})
$('#heroButton').onpointerdown=beginPress
$('#heroButton').onpointerup=e=>endPress(e)
$('#heroButton').onpointercancel=e=>endPress(e,true)
$('#heroButton').onmouseenter=()=>{$('#heroButton').classList.add('is-hover');if(currentEvent==='hover')playCurrent()}
$('#heroButton').onmouseleave=e=>{$('#heroButton').classList.remove('is-hover');if($('#heroButton').classList.contains('is-pressed'))endPress(e,true)}
$('#heroButton').onkeydown=e=>{if((e.key===' '||e.key==='Enter')&&!e.repeat&&!$('#heroButton').classList.contains('is-pressed')){e.preventDefault();beginPress(e)}}
$('#heroButton').onkeyup=e=>{if(e.key===' '||e.key==='Enter'){e.preventDefault();endPress(e)}}
$('#heroButton').onclick=e=>{if(pressHandled){pressHandled=false;e.preventDefault()}}
$('#soundV1').onclick=()=>setSoundVersion('v1')
$('#soundV2').onclick=()=>setSoundVersion('v2')
$('#soundV21').onclick=()=>setSoundVersion('v21')
$('#soundPaid').onclick=()=>setSoundVersion('paid')
$('#playSequence').onclick=playCurrent
$('#search').oninput=e=>renderAssets(e.target.value)
$('#addAudio').onclick=async()=>{const files=await window.feedbackLab.pickAudio();files.forEach(a=>assets.set(a.path,{...a,picked:true}));renderAssets($('#search').value)}
$('#savePreset').onclick=async()=>{const preset={schemaVersion:7,savedAt:new Date().toISOString(),params,events,batchCount:+$('#batchCount').value||12};localStorage.setItem('modagent-feedback-lab',JSON.stringify(preset));const path=await window.feedbackLab.savePreset(preset);$('#audioState').textContent='方案已保存 · JSON 已导出';$('#audioState').title=path||'';setTimeout(()=>$('#audioState').textContent=`${assets.size} 个素材已载入`,1600)}
$('#reset').onclick=()=>{Object.assign(params,{volume:72,rate:100,jitter:0,duration:420,depth:8,glow:65,particle:16});syncControls()}
init()
