<script setup>
import {ref,computed,watch,onBeforeUnmount} from 'vue'
import ChartPanel from './ChartPanel.vue'
import outlines from './assets/provinces.json'
const props=defineProps({client:Object,info:Object,batch:String})
const emit=defineEmits(['province','batch-change'])
const sections=ref({}), pending=ref(true)
const policies=props.info.dictionaries.price_policies, policyId=ref(policies[0]?.id || '')
const regions=new Map(props.info.dictionaries.regions.map(r=>[r.key,r]))
const shapeNames=new Set(outlines.features.map(f=>f.properties.name))
const names={unknown:'等级未知',conflict:'等级有分歧',unrated:'未评级',rated:'已评级'}
let serial=0

async function pages(params) {
  const items=[]
  let total, pages
  for(let page=1; ; page++) {
    const reply=await props.client.statistics({...params,batch_id:props.batch,page,page_size:100})
    if(reply.meta.batch_id!==props.batch) throw Object.assign(new Error('批次已更新。'),{code:'BATCH_MISMATCH'})
    const d=reply.data
    if(d.page!==page || (page>1 && (total!==d.total || pages!==d.total_pages))) throw new Error('分页统计发生变化，请重试。')
    pages=d.total_pages;total=d.total;items.push(...d.items)
    if(page>=pages) break
  }
  if(items.length!==total) throw new Error('统计分组未读完整，请重试。')
  return items
}
async function refresh(){
  const seq=++serial; pending.value=true; sections.value={}
  const p=policies.find(p=>p.id===policyId.value)
  const fields=p?{currency:p.currency,price_policy_id:p.id}:{}
  const tasks={province:{metric:'attraction_count',scope:'province'},city:{metric:'attraction_count',scope:'city',sort:'count_desc'},
    grade:{metric:'attraction_count',scope:'grade'},price:{metric:'price_summary',scope:'all',...fields},
    hist:{metric:'price_histogram',scope:'all',...fields}}
  const keys=Object.keys(tasks)
  const output=await Promise.allSettled(keys.map(key=>pages(tasks[key])))
  if(seq!==serial)return
  if(output.some(r=>r.status==='rejected'&&r.reason.code==='BATCH_MISMATCH')){ emit('batch-change');return }
  sections.value=Object.fromEntries(output.map((r,i)=>[keys[i],r.status==='fulfilled'?{items:r.value}:{error:r.reason.message}]))
  pending.value=false
}
watch(policyId,refresh,{immediate:true})
onBeforeUnmount(()=>serial++)
const batchRows=key=>sections.value[key]?.items || []
function shortProvince(r) {
  if(!r || r.country_code!=='CN' || r.level!=='province')return ''
  const short=r.name.replace(/(维吾尔自治区|壮族自治区|回族自治区|自治区|省|市)$/u,'')
  return shapeNames.has(short)?short:''
}
const provinceRows=computed(()=>batchRows('province').map(r=>{
  const key=r.dimensions.province_key, region=regions.get(key)
  return {name:shortProvince(region),regionKey:key,label:region?.name||key||'省级地区未知',value:r.value.count}
}))
const unknown=computed(()=>provinceRows.value.filter(r=>!r.name))
const unknownCity=computed(()=>batchRows('city').filter(r=>!r.dimensions.city_key).reduce((n,r)=>n+r.value.count,0))
const cityBars=computed(()=>batchRows('city').filter(r=>r.dimensions.city_key).slice(0,10).map(r=>({
  name:regions.get(r.dimensions.city_key)?.name || r.dimensions.city_key,value:r.value.count})))
const gradeBars=computed(()=>batchRows('grade').map(r=>({name:[r.dimensions.country_code,r.dimensions.grade_system==='UNKNOWN'?'':r.dimensions.grade_system,r.dimensions.grade_level || names[r.dimensions.grade_status]].filter(Boolean).join(' · '),value:r.value.count})))
const price=computed(()=>batchRows('price')[0])
const hist=computed(()=>batchRows('hist')[0])
const bins=computed(()=>(hist.value?.value?.bins || []).map(b=>({name:b.upper===null?b.lower+' 及以上':'['+b.lower+', '+b.upper+')',value:b.count})))
const mapOptions=computed(()=>{
 const values=provinceRows.value.filter(r=>r.name)
 return {tooltip:{trigger:'item',renderMode:'richText',formatter:p=>p.name+'　'+(p.data?p.data.value+' 条':'没有统计记录')},
   visualMap:{min:0,max:Math.max(1,...values.map(r=>r.value)),left:6,bottom:0,itemHeight:58,itemWidth:10,text:['多','少'],inRange:{color:['#d7e7cf','#87b296','#285840']}},
   series:[{type:'map',map:'atlas31',name:'候选景点',left:'7%',right:'6%',top:'3%',bottom:'7%',roam:false,
    itemStyle:{areaColor:'#e5e2d7',borderColor:'#faf8ef',borderWidth:1},emphasis:{label:{show:true},itemStyle:{areaColor:'#daa263'}},data:values}]}
})
function bars(rows) {
  return {tooltip:{trigger:'axis',renderMode:'richText'},grid:{top:10,bottom:27,left:4,right:32,containLabel:true},
    xAxis:{type:'value',minInterval:1,axisLabel:{color:'#536358'},splitLine:{lineStyle:{color:'#e4e4db'}}},
    yAxis:{type:'category',inverse:true,data:rows.map(r=>r.name),axisLabel:{color:'#334c3f',width:115,overflow:'truncate'}},
    series:[{type:'bar',barMaxWidth:22,data:rows.map(r=>r.value),label:{show:true,position:'right'},itemStyle:{color:'#53836a',borderRadius:[0,3,3,0]}}]}
}
function state(key) {return sections.value[key]?.error || (!batchRows(key).length?'没有已发布的统计分组。':'')}
</script>
<template>
  <p v-if="pending" class="state">正在读取同一批次的统计分组…</p>
  <div v-else class="chart-grid">
    <section class="chart-card map-card"><h2>省级景点分布</h2><p>按已收录候选记录计数，可点击有数据的省级地区查看景点。</p>
      <p v-if="state('province')" class="notice">{{state('province')}}</p>
      <template v-else><ChartPanel :options="mapOptions" label="统计覆盖地区的景点数量分布图" @pick="emit('province',$event)"/>
      <p>灰色表示没有统计记录。未映射或地区未知：{{unknown.reduce((n,r)=>n+r.value,0)}} 条。</p>
      <details><summary>查看各地区数量</summary><div class="region-links"><button v-for="r in provinceRows" :key="r.regionKey || r.label" :disabled="!r.regionKey || !regions.has(r.regionKey)" @click="emit('province',r.regionKey)">{{r.label}} · {{r.value}}</button></div></details></template>
      <small>底图为 Natural Earth 1:50m，展示本项目 31 个省级覆盖地区。</small></section>
    <section class="chart-card"><h2>城市景点数量前十</h2><p>当前批次中，已知城市按景点记录数降序排列。</p><p v-if="state('city')" class="notice">{{state('city')}}</p><template v-else><ChartPanel v-if="cityBars.length" :options="bars(cityBars)" label="城市候选景点数量排行榜"/><p>城市未知 {{unknownCity}} 条，单独列示。</p></template></section>
    <section class="chart-card"><h2>景区等级分布</h2><p>按原始等级体系分组，保留未知、未评级与资料冲突。</p><p v-if="state('grade')" class="notice">{{state('grade')}}</p><ChartPanel v-else :options="bars(gradeBars)" label="景区等级分布"/></section>
    <section class="chart-card"><h2>可比门票价格</h2><label v-if="policies.length>1">票价口径<select v-model="policyId"><option v-for="p in policies" :key="p.id" :value="p.id">{{p.ticket_basis}} · {{p.currency}}</option></select></label>
      <p v-if="state('price')" class="notice">{{state('price')}}</p><p v-else-if="price?.status==='pending_policy'">票价比较口径尚未确定。</p>
      <template v-else-if="price?.value"><p>可比 {{price.value.valid_count}} 条 / 候选 {{price.value.candidate_count}} 条</p><p v-if="price.status==='ok'">最低 {{price.value.min}} · 平均 {{price.value.mean}} · 最高 {{price.value.max}} {{price.dimensions.currency}}</p><p v-else>该口径下没有可比票价。</p></template>
      <p v-if="state('hist')" class="notice">{{state('hist')}}</p><ChartPanel v-else-if="bins.length" :options="bars(bins)" label="可比票价区间数量"/>
    </section>
  </div>
</template>
