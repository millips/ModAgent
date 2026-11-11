import assert from 'node:assert/strict'
import {validateToggleReceipt as validate} from '../src/components/toggleReceipt.mjs'

for (const enabling of [false,true]) {
  const receipt = enabling ? {enabled:1,enabled_mods:[{id:'target'}]} : {disabled:1,disabled_mods:[{id:'target'}],verified:true}
  const list = enabling ? 'enabled_mods' : 'disabled_mods'
  const count = enabling ? 'enabled' : 'disabled'
  assert.equal(validate(receipt,'target',enabling),receipt)
  validate({...receipt,external_configs:{complete:true}},'target',enabling)
  for (const bad of [null,[],{}, {...receipt,[count]:'1'}, {...receipt,[count]:-1},
    {...receipt,[list]:[]}, {...receipt,[list]:[{id:'other'}]},
    {...receipt,[list]:[{id:'target'},{id:'target'}]}, {...receipt,[list]:[null]},
    {...receipt,verified:'true'}, {...receipt,verified:false},
    {...receipt,external_configs:{complete:false}}, {...receipt,external_configs:{complete:'true'}},
    {...receipt,external_configs:[]}, {...receipt,external_configs:{}}]) {
    assert.throws(()=>validate(bad,'target',enabling),/LOCAL_API_INVALID_RESPONSE/)
  }
}
validate({disabled:0,disabled_mods:[],already_disabled:true,verified:true},'target',false)
assert.throws(()=>validate({disabled:0,disabled_mods:[],already_disabled:'true',verified:true},'target',false))
console.log('Toggle receipts: valid enable/disable/no-op and 31 malformed cases passed')
