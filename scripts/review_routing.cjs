const assert=require('node:assert/strict');
const fs=require('node:fs');
const workflow=JSON.parse(fs.readFileSync('n8n/ai-sales-lead-routing.json','utf8'));
const classify=new Function('$json',workflow.nodes.find(n=>n.name==='Classify API Result').parameters.jsCode);
for(const [decision,expected] of [
  [{intent_level:'High',disposition:'qualified'},'high'],
  [{intent_level:'Medium',disposition:'nurture'},'medium'],
  [{intent_level:'Low',disposition:'nurture'},'low'],
  [{intent_level:'High',disposition:'spam'},'suppressed'],
  [{intent_level:'High',disposition:'qualified',needs_review:true},'manual_review'],
  [{intent_level:'Low',disposition:'manual_review'},'manual_review']]) {
  assert.equal(classify({statusCode:200,body:{validation_result:{is_valid:true},analysis_result:{decision}}}).json.route_key,expected);
}
assert.equal(classify({statusCode:200,body:{validation_result:{is_valid:false}}}).json.route_key,'invalid');
assert.equal(classify({statusCode:503,body:{}}).json.route_key,'api_error');
for(const name of ['Prepare Suppressed','Prepare Manual Review','Prepare Invalid Lead','Prepare API Error']) {
  assert.equal(workflow.connections[name].main[0][0].node,'Prepare Safe Processing Log');
}
console.log('PASS: n8n classifier precedence and non-CRM safety branches');
