import assert from 'node:assert/strict';
import {pendingPlanCard, taskActionLabel, taskPresentation} from '../src/components/taskPresentation.mjs';
const messages = [{id:'correct',role:'edition',payload:{plan_task_id:'a',phase:'confirm',items:[{source_id:'1'}]}},
  {id:'wrong',role:'edition',payload:{plan_task_id:'b',phase:'confirm',items:[{source_id:'2'}]}}];
assert.equal(pendingPlanCard(messages, 'a')?.id, 'correct');
assert.equal(pendingPlanCard(messages, 'missing'), null);
assert.equal(pendingPlanCard(messages.map(m=>({...m,payload:{...m.payload,phase:'planning'}})), 'a'), null);
assert.equal(pendingPlanCard(messages.map(m=>({...m,payload:{...m.payload,items:[]}})), 'a'), null);
assert.equal(taskActionLabel('waiting_for_confirmation','zh-CN'), '等待你核对清单后确认');
assert.equal(taskPresentation({state:'WAITING_CONFIRMATION',payload:{result:{completed:Array(15).fill({tool:'game_file_check'}),not_completed:[{reason:'waiting_for_confirmation'}]}}}).showCounts, false);
console.log('R11 plan presentation: exact task linkage, no raw labels, no misleading counts passed');
