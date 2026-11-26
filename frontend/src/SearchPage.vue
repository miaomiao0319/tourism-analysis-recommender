<script setup>
import { ref, reactive, onMounted, onBeforeUnmount } from 'vue'
const props = defineProps({client:Object, info:Object, batch:String, initialProvince:String})
const emit = defineEmits(['detail','batch-change'])
const filters = reactive({ q:'', region:props.initialProvince || '', type:'', grade:'', price:'', sort:'name_asc',
  policy: props.info.dictionaries.price_policies[0]?.id || '' })
const data = ref(null), error = ref(''), waiting = ref(false)
let submitted = {}, active = 0
function apply() {
  const input = { sort:filters.sort }
  if (filters.q.trim()) input.q = filters.q.trim()
  const dict = props.info.dictionaries
  const region = dict.regions.find(r => r.key === filters.region)
  if (region) input[region.level + '_key'] = region.key
  if (filters.type) input.type_code = filters.type
  if (filters.grade) {
    const [system, level] = filters.grade.split('|')
    if (level) Object.assign(input, {grade_system:system, grade_level:level})
    else input.grade_status = system
  }
  if (filters.price !== '' || filters.sort !== 'name_asc') {
    const policy = dict.price_policies.find(p => p.id === filters.policy)
    if (!policy) { error.value = '请选择已发布的票价口径。';data.value=null;return }
    Object.assign(input,{currency:policy.currency,price_policy_id:policy.id})
    if (filters.price !== '') input.max_price = filters.price
  }
  submitted = input
  load(1)
}
async function load(page) {
  const seq = ++active
  data.value = null; waiting.value = true; error.value = ''
  try {
    const reply = await props.client.list({...submitted, batch_id:props.batch, page,page_size:12})
    if (seq !== active) return
    if (reply.meta.batch_id !== props.batch) {emit('batch-change');return}
    data.value=reply.data
  } catch(e) {
    if(seq!==active)return
    if(e.code==='BATCH_MISMATCH') emit('batch-change')
    else error.value=e.code ? e.message : '查询服务暂时无法连接。'
  } finally { if(seq===active) waiting.value=false }
}
function ticket(r) {
  if(r.price_form==='free') return '已确认免费'
  if(r.price_form==='unknown') return '票价未知'
  if(r.price_form==='conflict') return '票价有分歧'
  const prefix = r.currency==='CNY' ? '¥' : (r.currency || '')+' '
  const money = s => s?.replace(/\.00$/,'')
  return prefix+money(r.price_min)+(r.price_form==='range'?'–'+money(r.price_max):r.price_form==='from'?' 起':'')
}
onMounted(apply)
onBeforeUnmount(()=>active++)
</script>
<template>
  <form class="explore-filters" @submit.prevent="apply">
    <label>景点名称<input v-model="filters.q" type="search" maxlength="100" placeholder="输入景点名称"></label>
    <label>地区<select v-model="filters.region"><option value="">全部地区</option><option v-for="r in info.dictionaries.regions" :value="r.key" :key="r.key">{{ r.name }}</option></select></label>
    <label>景点类型<select v-model="filters.type"><option value="">全部类型</option><option v-for="t in info.dictionaries.types" :value="t.code" :key="t.code">{{ t.label }}</option></select></label>
    <label>景区等级<select v-model="filters.grade"><option value="">全部等级</option><optgroup v-for="s in info.dictionaries.grade_systems" :label="s.label || s.code" :key="s.code"><option v-for="level in s.levels" :value="s.code+'|'+level" :key="level">{{level}}</option></optgroup><option value="unknown">等级未知</option><option value="unrated">未评级</option><option value="conflict">资料有分歧</option></select></label>
    <label>门票上限<input v-model="filters.price" :disabled="!info.dictionaries.price_policies.length" placeholder="不限金额" inputmode="decimal"></label>
    <label>结果排序<select v-model="filters.sort"><option value="name_asc">按名称</option><option :disabled="!info.dictionaries.price_policies.length" value="price_asc">门票从低到高</option><option :disabled="!info.dictionaries.price_policies.length" value="price_desc">门票从高到低</option></select></label>
    <label v-if="info.dictionaries.price_policies.length>1">票价口径<select v-model="filters.policy"><option v-for="p in info.dictionaries.price_policies" :value="p.id" :key="p.id">{{p.ticket_basis}} · {{p.currency}}</option></select></label>
    <button class="primary">查询景点 →</button>
  </form>
  <section class="results" aria-live="polite"><div class="result-head"><h2>查询结果</h2><span v-if="data">共 {{data.total}} 条</span></div>
    <p v-if="waiting" class="state">正在读取景点…</p><p v-else-if="error" role="alert" class="state">{{error}}</p>
    <template v-else-if="data"><p v-if="!data.items.length" class="state">没有符合当前筛选条件的景点。</p>
    <div v-else class="list-table"><button v-for="r in data.items" :key="r.attraction_id" @click="emit('detail',r)"><span><strong>{{r.name}}</strong><small>{{ [r.province_name,r.city_name].filter(Boolean).join(' · ') || '地区未知' }}</small></span><span>{{ticket(r)}}　↗</span></button></div>
    <div v-if="data.total_pages>1" class="pager"><button class="secondary" :disabled="data.page<=1" @click="load(data.page-1)">上一页</button><span>{{data.page}} / {{data.total_pages}}</span><button class="secondary" :disabled="data.page>=data.total_pages" @click="load(data.page+1)">下一页</button></div></template>
  </section>
</template>
